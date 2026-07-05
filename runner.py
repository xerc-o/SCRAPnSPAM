#!/usr/bin/env python3
"""
runner.py - Fase 3: Eksekusi loop pengisian & submit form otomatis.
Mendukung mode isian: fixed, random_string, random_int, sequential, wordlist,
mirror (ikut field lain), fixed_choice, random_choice, multi_fixed, multi_random
(untuk select/radio/checkbox). Mendukung multi-threading (banyak browser paralel).

PENTING (etika/legal): Jalankan HANYA terhadap target yang sudah diotorisasi
secara eksplisit untuk pengujian (scope pentest resmi / lab milik sendiri).
"""

import argparse
import csv
import json
import random
import threading
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import generators

SUCCESS_HINTS = ["success", "berhasil", "thank you", "terima kasih", "sukses", "welcome", "dashboard"]
ERROR_HINTS = ["error", "gagal", "invalid", "salah", "failed", "tidak valid"]


def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def field_key(field):
    return field.get("name") or field.get("id") or f"field_{field['index']}"


# ---------------------------------------------------------------------------
# Value resolution (termasuk mode 'mirror' 2-fase resolve, & choice/multi modes)
# ---------------------------------------------------------------------------

def compute_single_value(field, settings, state):
    """Hitung value untuk field non-mirror, non-skip."""
    mode = settings.get("mode", "skip")
    tag = field["tag"]
    ftype = field["type"]

    if tag == "select" or ftype in ("radio", "checkbox"):
        if mode == "fixed_choice" or mode == "fixed":
            return settings.get("fixed_value")
        if mode == "random_choice":
            opts = field.get("options") or []
            return random.choice(opts).get("value") if opts else None
        if mode == "random_choice_weighted":
            opts = field.get("options") or []
            weights_cfg = {w["value"]: max(0.0, float(w.get("weight", 0))) for w in settings.get("weights", [])}
            values = [o.get("value") for o in opts]
            weights = [weights_cfg.get(v, 0) for v in values]
            if not values or sum(weights) <= 0:
                return random.choice(values) if values else None
            return random.choices(values, weights=weights, k=1)[0]
        if mode == "multi_fixed":
            return list((settings.get("multi_fixed") or {}).get("values", []))
        if mode == "multi_random":
            opts = field.get("options") or []
            mr = settings.get("multi_random", {})
            n_max = min(int(mr.get("count_max", 1)), len(opts))
            n_min = min(int(mr.get("count_min", 1)), n_max) if n_max else 0
            n = random.randint(n_min, n_max) if n_max else 0
            chosen = random.sample(opts, n) if n else []
            return [o.get("value") for o in chosen]
        return None

    # text-like input/textarea: fixed, random_string, random_int, sequential, wordlist
    return generators.generate_value(settings, state)


def resolve_all_values(fields, state):
    """
    Resolve value semua field untuk 1 run, termasuk field 'mirror'
    (mengikuti value field rujukan lain; resolve berantai + deteksi cycle).
    Return: dict field_key -> value (None = skip/gagal).
    """
    resolved = {}
    mirror_pending = []

    for field in fields:
        key = field_key(field)
        settings = dict(field.get("settings", {}))
        settings["_field_key"] = key
        mode = settings.get("mode", "skip")

        if mode == "skip":
            resolved[key] = None
        elif mode == "mirror":
            mirror_pending.append((field, settings))
        else:
            resolved[key] = compute_single_value(field, settings, state)

    for _ in range(len(mirror_pending) + 1):
        if not mirror_pending:
            break
        still_pending = []
        for field, settings in mirror_pending:
            key = field_key(field)
            ref = settings.get("mirror_of")
            if ref in resolved:
                resolved[key] = resolved[ref]
            else:
                still_pending.append((field, settings))
        if len(still_pending) == len(mirror_pending):
            for field, settings in still_pending:
                key = field_key(field)
                resolved[key] = None
                print(f"    [!] Mirror field '{key}' gagal resolve "
                      f"(circular reference / field rujukan tidak ditemukan), dilewati")
            break
        mirror_pending = still_pending

    return resolved


def fill_field(page, field, value):
    if value is None:
        return
    tag = field["tag"]
    ftype = field["type"]
    selector = field["selector"]
    name = field.get("name")

    try:
        if isinstance(value, list):
            for v in value:
                sel = f'[name="{name}"][value="{v}"]' if name else selector
                page.check(sel)
            return
        if tag == "select":
            page.select_option(selector, value)
        elif ftype in ("checkbox", "radio"):
            sel = f'[name="{name}"][value="{value}"]' if name else selector
            page.check(sel)
        else:
            page.fill(selector, str(value))
    except Exception as e:
        print(f"    [!] Gagal isi field '{name or field.get('id')}': {e}")


def detect_result(page, response_status, detection_cfg):
    manual_success = detection_cfg.get("success_selector")
    manual_error = detection_cfg.get("error_selector")

    if manual_success and page.query_selector(manual_success):
        return "success", "matched success_selector"
    if manual_error and page.query_selector(manual_error):
        return "error", "matched error_selector"

    if detection_cfg.get("auto_detect", True):
        try:
            content = page.content().lower()
        except Exception:
            content = ""
        for hint in SUCCESS_HINTS:
            if hint in content:
                return "success", f"auto-detect keyword '{hint}'"
        for hint in ERROR_HINTS:
            if hint in content:
                return "error", f"auto-detect keyword '{hint}'"

    if response_status is not None:
        if 200 <= response_status < 400:
            return "unknown-ok", f"status {response_status}, no keyword matched"
        return "unknown-fail", f"status {response_status}"

    return "unknown", "no signal detected"


def compute_delay(delay_cfg):
    mode = delay_cfg.get("mode", "none")
    if mode == "none":
        return 0
    if mode == "fixed":
        return float(delay_cfg.get("fixed_seconds", 1))
    if mode == "random":
        lo = float(delay_cfg.get("random_min", 1))
        hi = float(delay_cfg.get("random_max", 3))
        return random.uniform(min(lo, hi), max(lo, hi))
    if mode == "smart":
        return float(delay_cfg.get("fixed_seconds", 1))
    return 0


# ---------------------------------------------------------------------------
# Eksekusi 1 run
# ---------------------------------------------------------------------------

def execute_one_run(context, run_index, url, fields, submit_selector,
                     detection_cfg, state, print_lock, close_page_only=False):
    page = context.new_page()
    last_status = {"code": None}

    def on_response(resp, _page=page, _status=last_status):
        if resp.url == _page.url or resp.request.resource_type == "document":
            _status["code"] = resp.status

    page.on("response", on_response)

    run_result = {
        "run": run_index,
        "timestamp": datetime.utcnow().isoformat(),
        "values": {},
        "result": None,
        "detail": None,
        "status_code": None,
    }

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        values = resolve_all_values(fields, state)
        for field in fields:
            key = field_key(field)
            value = values.get(key)
            if value is not None:
                run_result["values"][key] = ",".join(map(str, value)) if isinstance(value, list) else value
                fill_field(page, field, value)

        if submit_selector:
            page.click(submit_selector)
        else:
            page.keyboard.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass

        status, detail = detect_result(page, last_status["code"], detection_cfg)
        run_result["result"] = status
        run_result["detail"] = detail
        run_result["status_code"] = last_status["code"]

    except Exception as e:
        run_result["result"] = "exception"
        run_result["detail"] = str(e)

    page.close()

    with print_lock:
        print(f"[{run_index}] {run_result['result']} - {run_result['detail']}")

    return run_result


# ---------------------------------------------------------------------------
# Mode sekuensial (dipakai kalau session_mode == 'reuse', threading dinonaktifkan)
# ---------------------------------------------------------------------------

def run_sequential(config, run_count, browser, storage_state, url, fields, submit_selector,
                    detection_cfg, delay_cfg, session_mode):
    state = {"sequential": {}, "wordlist": {}}
    results = []
    print_lock = threading.Lock()
    consecutive_fail_streak = 0

    shared_context = browser.new_context(storage_state=storage_state) if session_mode == "reuse" else None

    i = 0
    endless = run_count is None
    try:
        while endless or i < run_count:
            i += 1
            context = shared_context or browser.new_context(storage_state=storage_state)

            run_result = execute_one_run(context, i, url, fields, submit_selector,
                                          detection_cfg, state, print_lock)
            results.append(run_result)

            if not shared_context:
                context.close()

            consecutive_fail_streak = consecutive_fail_streak + 1 if run_result["result"] in \
                ("error", "unknown-fail", "exception") else 0

            delay = compute_delay(delay_cfg)
            if delay_cfg.get("mode") == "smart" and consecutive_fail_streak >= 3:
                delay = max(delay, 5) * consecutive_fail_streak
                print(f"    [!] Gagal beruntun {consecutive_fail_streak}x, delay diperpanjang jadi {delay:.1f}s")
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna.")

    if shared_context:
        shared_context.close()

    return results


# ---------------------------------------------------------------------------
# Mode multi-threaded (session_mode == 'new', tiap run dapat context sendiri,
# tiap thread punya browser Playwright sendiri karena sync API tidak thread-safe
# lintas thread untuk 1 instance browser yang sama)
# ---------------------------------------------------------------------------

def run_threaded(run_count, thread_count, headless, channel, storage_state,
                  url, fields, submit_selector, detection_cfg, delay_cfg):
    state = {"sequential": {}, "wordlist": {}}
    results = []
    results_lock = threading.Lock()
    print_lock = threading.Lock()
    stop_event = threading.Event()
    run_counter = {"value": 0, "lock": threading.Lock()}

    def worker(thread_id):
        consecutive_fail_streak = 0
        launch_kwargs = {"headless": headless}
        if channel:
            launch_kwargs["channel"] = channel

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            try:
                while not stop_event.is_set():
                    with run_counter["lock"]:
                        if run_count is not None and run_counter["value"] >= run_count:
                            break
                        run_counter["value"] += 1
                        i = run_counter["value"]

                    context = browser.new_context(storage_state=storage_state)
                    run_result = execute_one_run(context, i, url, fields, submit_selector,
                                                  detection_cfg, state, print_lock)
                    context.close()

                    with results_lock:
                        results.append(run_result)

                    consecutive_fail_streak = consecutive_fail_streak + 1 if run_result["result"] in \
                        ("error", "unknown-fail", "exception") else 0

                    delay = compute_delay(delay_cfg)
                    if delay_cfg.get("mode") == "smart" and consecutive_fail_streak >= 3:
                        delay = max(delay, 5) * consecutive_fail_streak
                        with print_lock:
                            print(f"    [!] Thread-{thread_id}: gagal beruntun {consecutive_fail_streak}x, "
                                  f"delay diperpanjang jadi {delay:.1f}s")
                    if delay > 0:
                        time.sleep(delay)
            finally:
                browser.close()

    threads = [threading.Thread(target=worker, args=(t + 1,), daemon=True) for t in range(thread_count)]
    for t in threads:
        t.start()

    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna, menunggu thread aktif selesai...")
        stop_event.set()
        for t in threads:
            t.join()

    results.sort(key=lambda r: r["run"])
    return results


# ---------------------------------------------------------------------------
# Orkestrasi utama
# ---------------------------------------------------------------------------

def run(config, run_count, output_csv):
    url = config["url"]
    fields = config["fields"]
    submit_selector = config.get("submit_selector")
    run_settings = config.get("run_settings", {})
    detection_cfg = config.get("detection", {})
    delay_cfg = run_settings.get("delay", {"mode": "none"})
    session_mode = run_settings.get("session_mode", "new")
    login_required = config.get("login_required", False)
    channel = config.get("browser_channel") or None

    thread_count = int(run_settings.get("thread_count", 5) or 1)
    if session_mode == "reuse" and thread_count > 1:
        print("[!] Session mode 'reuse' tidak kompatibel dengan multi-thread, fallback ke 1 thread (sekuensial).")
        thread_count = 1

    storage_state_path = Path("auth_state.json")
    storage_state = str(storage_state_path) if storage_state_path.exists() else None

    with sync_playwright() as p:
        login_headless = not login_required
        browser = p.chromium.launch(headless=login_headless, **({"channel": channel} if channel else {}))

        if login_required and not storage_state:
            login_ctx = browser.new_context()
            login_page = login_ctx.new_page()
            login_page.goto(url, wait_until="domcontentloaded")
            print("\n[!] Silakan login manual di browser yang terbuka.")
            input("[!] Setelah login selesai, tekan ENTER untuk menyimpan sesi & lanjut...\n")
            login_ctx.storage_state(path=str(storage_state_path))
            storage_state = str(storage_state_path)
            login_ctx.close()

        if thread_count <= 1:
            results = run_sequential(config, run_count, browser, storage_state, url, fields,
                                      submit_selector, detection_cfg, delay_cfg, session_mode)
            browser.close()
        else:
            browser.close()  # browser login ditutup, worker thread bikin browser sendiri-sendiri
            print(f"[*] Menjalankan {thread_count} thread paralel...")
            results = run_threaded(run_count, thread_count, headless=True, channel=channel,
                                    storage_state=storage_state, url=url, fields=fields,
                                    submit_selector=submit_selector, detection_cfg=detection_cfg,
                                    delay_cfg=delay_cfg)

    write_csv(results, output_csv)

    detail_txt = str(Path(output_csv).with_name(Path(output_csv).stem + "_detail.txt"))
    detail_jsonl = str(Path(output_csv).with_name(Path(output_csv).stem + "_detail.jsonl"))
    write_detail_log(results, detail_txt, detail_jsonl)

    print(f"\n[+] Selesai. Total run: {len(results)}.")
    print(f"    - Ringkasan CSV : {output_csv}")
    print(f"    - Detail (txt)  : {detail_txt}")
    print(f"    - Detail (jsonl): {detail_jsonl}")


def write_csv(results, path):
    if not results:
        return
    all_field_names = sorted({k for r in results for k in r["values"].keys()})

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "timestamp", "result", "detail", "status_code"] + all_field_names)
        for r in results:
            row = [r["run"], r["timestamp"], r["result"], r["detail"], r["status_code"]]
            row += [r["values"].get(fn, "") for fn in all_field_names]
            writer.writerow(row)


def write_detail_log(results, txt_path, jsonl_path):
    """
    Log human-readable per-run (txt) + machine-readable per-run (jsonl),
    isinya seluruh value yang dipakai saat submit (login, password, email, dst).
    """
    with open(txt_path, "w", encoding="utf-8") as f_txt, open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
        for r in results:
            f_txt.write(
                f"[Run {r['run']}] {r['timestamp']} - result: {r['result']} "
                f"({r['detail']}, status={r['status_code']})\n"
            )
            if r["values"]:
                for k, v in r["values"].items():
                    f_txt.write(f"    {k}: {v}\n")
            else:
                f_txt.write("    (tidak ada field yang diisi)\n")
            f_txt.write("\n")

            f_jsonl.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Jalankan automasi pengisian form (Fase 3).")
    ap.add_argument("--config", default="field_config.json", help="Path field_config.json hasil GUI")
    ap.add_argument("--count", default=None, help="Override jumlah run (angka) atau 'endless'")
    ap.add_argument("--output", default=None, help="Path output CSV log")
    args = ap.parse_args()

    config = load_config(args.config)

    count_arg = args.count or config.get("run_settings", {}).get("count", "10")
    run_count = None if str(count_arg).lower() == "endless" else int(count_arg)

    output_csv = args.output or f"logs/run_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)

    run(config, run_count, output_csv)


if __name__ == "__main__":
    main()