#!/usr/bin/env python3
"""
scraper.py - Fase 1: Kunjungi target & ekstrak field form untuk automasi.

PENTING (etika/legal): Gunakan HANYA pada target yang sudah diotorisasi
secara eksplisit untuk pengujian (scope pentest resmi / lab milik sendiri).
Tool ini murni scraping struktur form + auto-fill data uji, tidak melakukan
bypass otentikasi atau eksploitasi apapun.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

EXTRACT_JS = r"""
() => {
    const allEls = Array.from(document.querySelectorAll('input, select, textarea'));
    const results = [];
    const seenRadioCheckbox = {};

    function getLabelText(el) {
        if (el.id) {
            const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (lbl) return lbl.innerText.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.innerText.trim();
        if (el.getAttribute('placeholder')) return el.getAttribute('placeholder');
        if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
        return null;
    }

    allEls.forEach((el, idx) => {
        const tag = el.tagName.toLowerCase();
        const rawType = el.getAttribute('type');
        const type = (rawType || (tag === 'select' ? 'select' : tag === 'textarea' ? 'textarea' : 'text')).toLowerCase();
        if (['submit', 'button', 'reset', 'hidden', 'image'].includes(type)) return;

        const name = el.getAttribute('name') || null;
        const id = el.id || null;

        if ((type === 'radio' || type === 'checkbox') && name && seenRadioCheckbox[name]) {
            seenRadioCheckbox[name].options.push({
                value: el.value,
                text: getLabelText(el) || el.value,
                checked: el.checked
            });
            return;
        }

        const entry = {
            index: idx,
            tag: tag,
            type: type,
            name: name,
            id: id,
            label: getLabelText(el),
            required: !!el.required,
            maxlength: (el.maxLength && el.maxLength > 0) ? el.maxLength : null,
            pattern: el.getAttribute('pattern') || null,
            placeholder: el.getAttribute('placeholder') || null,
            form_id: el.form ? (el.form.id || null) : null,
            options: null
        };

        if (tag === 'select') {
            entry.options = Array.from(el.options).map(o => ({ value: o.value, text: o.text.trim() }));
        } else if (type === 'radio' || type === 'checkbox') {
            entry.options = [{ value: el.value, text: getLabelText(el) || el.value, checked: el.checked }];
            if (name) seenRadioCheckbox[name] = entry;
        }

        results.push(entry);
    });

    return results;
}
"""

SUBMIT_JS = r"""
() => {
    const btn = document.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
    if (!btn) return null;
    if (btn.id) return '#' + btn.id;
    if (btn.name) return `[name="${btn.name}"]`;
    return null;
}
"""


def build_selector(field):
    """Prioritas selector: name > id > xpath index fallback."""
    if field.get("name"):
        return f'[name="{field["name"]}"]'
    if field.get("id"):
        return f'#{field["id"]}'
    return f'xpath=(//input|//select|//textarea)[{field["index"] + 1}]'


def scrape(url, headless=True, wait_for_login=False, timeout=30000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless and not wait_for_login)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        if wait_for_login:
            print("\n[!] Browser dibuka. Silakan login manual di jendela browser.")
            input("[!] Setelah selesai login dan berada di halaman form target, "
                  "tekan ENTER di sini untuk lanjut scraping...\n")

        raw_fields = page.evaluate(EXTRACT_JS)
        submit_selector = page.evaluate(SUBMIT_JS)

        fields = []
        for f in raw_fields:
            f["selector"] = build_selector(f)
            fields.append(f)

        result = {
            "url": url,
            "submit_selector": submit_selector,
            "scraped_fields_count": len(fields),
            "fields": fields,
        }

        context.close()
        browser.close()
        return result


def main():
    ap = argparse.ArgumentParser(description="Scrape form fields dari halaman target (Fase 1).")
    ap.add_argument("--url", required=True, help="URL target yang akan di-scrape")
    ap.add_argument("--login", action="store_true",
                     help="Buka browser headful & jeda untuk login manual dulu")
    ap.add_argument("--output", default="config.json", help="Path output JSON hasil scraping")
    args = ap.parse_args()

    print(f"[*] Mengunjungi target: {args.url}")
    data = scrape(args.url, headless=not args.login, wait_for_login=args.login)

    out_path = Path(args.output)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[+] Ditemukan {data['scraped_fields_count']} field.")
    for f in data["fields"]:
        label = f.get("label") or f.get("name") or f.get("id") or f"(field #{f['index']})"
        print(f"    - {label}  [tag={f['tag']} type={f['type']} name={f.get('name')}]")
    if data.get("submit_selector"):
        print(f"[+] Submit button terdeteksi: {data['submit_selector']}")
    else:
        print("[!] Submit button tidak otomatis terdeteksi, runner akan fallback ke tombol Enter.")

    print(f"[+] Hasil disimpan ke: {out_path.resolve()}")
    print(f"[*] Lanjutkan ke: python gui.py --config {args.output}")


if __name__ == "__main__":
    main()