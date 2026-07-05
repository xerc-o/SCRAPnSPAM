#!/usr/bin/env python3
"""
gui.py - Fase 2: GUI konfigurasi mode pengisian tiap field hasil scraping.
Dark mode by default.
Butuh python3-tk (biasanya sudah bawaan, kalau belum: `sudo apt install python3-tk`).
"""

import argparse
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

MODES_TEXT = [
    "skip", "fixed", "random_string", "random_int", "sequential", "wordlist",
    "random_choice", "random_choice_weighted", "multi_random", "multi_fixed", "mirror",
]
CHARSET_OPTIONS = ["alnum", "letters", "upper", "lower", "digits", "custom"]

# ---------------------------------------------------------------------------
# Dark theme
# ---------------------------------------------------------------------------
BG = "#1e1e1e"
BG_ALT = "#252526"
FG = "#e0e0e0"
FG_MUTED = "#9a9a9a"
ENTRY_BG = "#2d2d2d"
ACCENT = "#3b82f6"
BORDER = "#3c3c3c"
SELECT_BG = "#094771"


def apply_dark_theme(root):
    root.configure(bg=BG)
    root.tk_setPalette(background=BG, foreground=FG, activeBackground=SELECT_BG, activeForeground=FG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG,
                     bordercolor=BORDER, lightcolor=BG, darkcolor=BG)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TButton", background=BG_ALT, foreground=FG, bordercolor=BORDER, focusthickness=1)
    style.map("TButton", background=[("active", SELECT_BG)], foreground=[("active", FG)])
    style.configure("TEntry", fieldbackground=ENTRY_BG, foreground=FG, insertcolor=FG, bordercolor=BORDER)
    style.configure("TCombobox", fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=FG,
                     arrowcolor=FG, bordercolor=BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", ENTRY_BG)], foreground=[("readonly", FG)])
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TRadiobutton", background=BG, foreground=FG)
    style.map("TRadiobutton", background=[("active", BG)])
    style.configure("TNotebook", background=BG, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=BG_ALT, foreground=FG_MUTED, padding=[10, 4])
    style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
    style.configure("TSeparator", background=BORDER)
    style.configure("Vertical.TScrollbar", background=BG_ALT, troughcolor=BG, bordercolor=BORDER, arrowcolor=FG)
    style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=FG)

    # dropdown listbox untuk Combobox pakai opsi tk global (bukan ttk)
    root.option_add("*TCombobox*Listbox.background", ENTRY_BG)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", FG)


def styled_toplevel(root, **kwargs):
    top = tk.Toplevel(root, bg=BG, **kwargs)
    return top


def styled_canvas(parent):
    return tk.Canvas(parent, bg=BG, highlightthickness=0)


# ---------------------------------------------------------------------------
# Per-field configuration dialog
# ---------------------------------------------------------------------------
class FieldConfigDialog(tk.Toplevel):
    def __init__(self, parent, field, existing_settings, all_fields):
        super().__init__(parent, bg=BG)
        self.field = field
        self.all_fields = all_fields
        self.result = None
        self.title(f"Konfigurasi: {field.get('label') or field.get('name') or field.get('id')}")
        self.geometry("460x520")
        self.resizable(False, False)
        self.configure(bg=BG)

        settings = existing_settings or {}
        self.mode_var = tk.StringVar(value=settings.get("mode", "skip"))

        is_group_type = field["tag"] == "select" or field["type"] in ("radio", "checkbox")
        available_modes = list(MODES_TEXT)
        if not is_group_type:
            available_modes = [m for m in available_modes
                                if m not in ("random_choice", "random_choice_weighted", "multi_random", "multi_fixed")]
        else:
            # multi_* cuma masuk akal untuk checkbox grup (banyak elemen, name sama)
            if field["type"] != "checkbox" or len(field.get("options") or []) < 2:
                available_modes = [m for m in available_modes if m not in ("multi_random", "multi_fixed")]

        ttk.Label(self, text=f"Field: {field.get('label') or field.get('name') or field.get('id')}",
                  font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Label(self, text="Mode isian:").pack(anchor="w", padx=10, pady=(8, 0))
        mode_combo = ttk.Combobox(self, textvariable=self.mode_var, values=available_modes, state="readonly")
        mode_combo.pack(fill="x", padx=10)
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self.render_mode_options())

        self.options_frame = ttk.Frame(self)
        self.options_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.vars = {}
        self._settings = settings
        self._weight_rows = []
        self.render_mode_options()

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_frame, text="Simpan", command=self.on_save).pack(side="right")
        ttk.Button(btn_frame, text="Batal", command=self.destroy).pack(side="right", padx=5)

        self.transient(parent)
        self.grab_set()

    def clear_options_frame(self):
        for w in self.options_frame.winfo_children():
            w.destroy()
        self.vars = {}
        self._weight_rows = []

    def _add_labeled_entry(self, label, key, default):
        ttk.Label(self.options_frame, text=label + ":").pack(anchor="w", pady=(6, 0))
        v = tk.StringVar(value=default)
        ttk.Entry(self.options_frame, textvariable=v).pack(fill="x")
        self.vars[key] = v

    def _other_field_choices(self):
        """List (display_label, field_key) untuk semua field selain field ini sendiri."""
        choices = []
        my_key = self.field.get("name") or self.field.get("id") or f"field_{self.field['index']}"
        for f in self.all_fields:
            k = f.get("name") or f.get("id") or f"field_{f['index']}"
            if k == my_key:
                continue
            label = f.get("label") or k
            choices.append((f"{label}  [{k}]", k))
        return choices

    def render_mode_options(self):
        self.clear_options_frame()
        mode = self.mode_var.get()
        s = self._settings

        if mode == "fixed":
            ttk.Label(self.options_frame, text="Nilai tetap (misal: USER):").pack(anchor="w")
            v = tk.StringVar(value=s.get("fixed_value", ""))
            ttk.Entry(self.options_frame, textvariable=v).pack(fill="x")
            self.vars["fixed_value"] = v

        elif mode == "random_string":
            rs = s.get("random_string", {})
            self._add_labeled_entry("Panjang minimal", "rs_len_min", str(rs.get("length_min", 8)))
            self._add_labeled_entry("Panjang maksimal", "rs_len_max", str(rs.get("length_max", 8)))

            ttk.Label(self.options_frame, text="Charset:").pack(anchor="w", pady=(6, 0))
            cs_var = tk.StringVar(value=rs.get("charset", "alnum"))
            ttk.Combobox(self.options_frame, textvariable=cs_var, values=CHARSET_OPTIONS,
                         state="readonly").pack(fill="x")
            self.vars["rs_charset"] = cs_var

            self._add_labeled_entry("Custom charset (dipakai jika charset='custom')",
                                     "rs_custom_charset", rs.get("custom_charset", ""))
            self._add_labeled_entry("Prefix (teks tetap di depan, misal 'batam, ')",
                                     "rs_prefix", rs.get("prefix", ""))
            self._add_labeled_entry("Suffix (teks tetap di belakang, misal '@gmail.com')",
                                     "rs_suffix", rs.get("suffix", ""))
            ttk.Label(self.options_frame,
                      text="Hasil: [prefix] + random(charset,panjang) + [suffix]",
                      foreground=FG_MUTED).pack(anchor="w", pady=(6, 0))

        elif mode == "random_int":
            ri = s.get("random_int", {})
            self._add_labeled_entry("Min", "ri_min", str(ri.get("min", 0)))
            self._add_labeled_entry("Max", "ri_max", str(ri.get("max", 9999)))
            self._add_labeled_entry("Jumlah digit tetap (kosongkan jika tidak perlu, misal '4' -> 0231)",
                                     "ri_digits", str(ri.get("digits", "") or ""))

        elif mode == "sequential":
            sq = s.get("sequential", {})
            self._add_labeled_entry("Mulai dari", "sq_start", str(sq.get("start", 1)))
            self._add_labeled_entry("Prefix (misal 'user')", "sq_prefix", sq.get("prefix", ""))
            self._add_labeled_entry("Suffix", "sq_suffix", sq.get("suffix", ""))
            self._add_labeled_entry("Zero-pad (misal 3 -> 001, 0 = tanpa padding)",
                                     "sq_pad", str(sq.get("pad", 0)))
            ttk.Label(self.options_frame, text="Hasil contoh: user1, user2, user3, ...",
                      foreground=FG_MUTED).pack(anchor="w", pady=(6, 0))

        elif mode == "wordlist":
            wl = s.get("wordlist", {})
            path_var = tk.StringVar(value=wl.get("path", ""))
            ttk.Label(self.options_frame, text="File wordlist (.txt, satu kata per baris):").pack(anchor="w")
            row = ttk.Frame(self.options_frame)
            row.pack(fill="x")
            ttk.Entry(row, textvariable=path_var).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Browse",
                       command=lambda: path_var.set(filedialog.askopenfilename() or path_var.get())
                       ).pack(side="left")
            self.vars["wl_path"] = path_var
            self._add_labeled_entry("Prefix", "wl_prefix", wl.get("prefix", ""))
            self._add_labeled_entry("Suffix", "wl_suffix", wl.get("suffix", ""))

        elif mode == "random_choice":
            opts = self.field.get("options") or []
            txt = ", ".join(o.get("value", "") or o.get("text", "") for o in opts) or "(tidak ada opsi terdeteksi)"
            ttk.Label(self.options_frame, text="Pilih 1 opsi acak dari yang tersedia tiap run:",
                      wraplength=420).pack(anchor="w")
            ttk.Label(self.options_frame, text=txt, wraplength=420, foreground=FG_MUTED).pack(anchor="w", pady=(6, 0))

        elif mode == "random_choice_weighted":
            opts = self.field.get("options") or []
            w = s.get("weights", [])
            w_by_value = {x["value"]: x.get("weight", 1) for x in w}
            ttk.Label(self.options_frame, text="Atur bobot (%) tiap opsi (boleh tidak 100% pas, dinormalisasi otomatis):",
                      wraplength=420).pack(anchor="w")
            grid = ttk.Frame(self.options_frame)
            grid.pack(fill="x", pady=(6, 0))
            for i, o in enumerate(opts):
                val = o.get("value", "")
                ttk.Label(grid, text=(o.get("text") or val)).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
                wv = tk.StringVar(value=str(w_by_value.get(val, 1)))
                ttk.Entry(grid, textvariable=wv, width=6).grid(row=i, column=1, pady=2)
                self._weight_rows.append((val, wv))
            if not opts:
                ttk.Label(self.options_frame, text="(tidak ada opsi terdeteksi)", foreground=FG_MUTED).pack(anchor="w")

        elif mode == "multi_random":
            mr = s.get("multi_random", {})
            self._add_labeled_entry("Jumlah opsi dicentang - minimal", "mr_min", str(mr.get("count_min", 1)))
            self._add_labeled_entry("Jumlah opsi dicentang - maksimal", "mr_max", str(mr.get("count_max", 2)))
            opts = self.field.get("options") or []
            txt = ", ".join(o.get("value", "") for o in opts) or "(tidak ada opsi terdeteksi)"
            ttk.Label(self.options_frame, text=f"Opsi tersedia: {txt}", wraplength=420,
                      foreground=FG_MUTED).pack(anchor="w", pady=(6, 0))

        elif mode == "multi_fixed":
            opts = self.field.get("options") or []
            ttk.Label(self.options_frame, text="Centang opsi yang selalu dipilih tiap run:").pack(anchor="w")
            existing_vals = set(s.get("multi_fixed", {}).get("values", []))
            self._mf_checks = []
            for o in opts:
                val = o.get("value", "")
                cv = tk.BooleanVar(value=val in existing_vals)
                ttk.Checkbutton(self.options_frame, text=(o.get("text") or val), variable=cv).pack(anchor="w")
                self._mf_checks.append((val, cv))
            if not opts:
                ttk.Label(self.options_frame, text="(tidak ada opsi terdeteksi)", foreground=FG_MUTED).pack(anchor="w")

        elif mode == "mirror":
            ttk.Label(self.options_frame,
                      text="Isi field ini SAMA PERSIS dengan hasil field lain (berguna untuk re-enter password, "
                           "confirm email, dll). Berlaku untuk field rujukan mode apapun.",
                      wraplength=420).pack(anchor="w")
            choices = self._other_field_choices()
            display_to_key = {d: k for d, k in choices}
            key_to_display = {k: d for d, k in choices}
            current_ref = s.get("mirror_of", "")
            init_display = key_to_display.get(current_ref, "")
            ref_var = tk.StringVar(value=init_display)
            ttk.Label(self.options_frame, text="Field rujukan:").pack(anchor="w", pady=(8, 0))
            combo = ttk.Combobox(self.options_frame, textvariable=ref_var,
                                  values=[d for d, k in choices], state="readonly")
            combo.pack(fill="x")
            self.vars["mirror_display"] = ref_var
            self._mirror_display_to_key = display_to_key

        elif mode == "skip":
            ttk.Label(self.options_frame, text="Field ini akan dilewati (tidak diisi saat submit).").pack(anchor="w")

    def on_save(self):
        mode = self.mode_var.get()
        settings = {"mode": mode}

        try:
            if mode == "fixed":
                settings["fixed_value"] = self.vars["fixed_value"].get()

            elif mode == "random_string":
                settings["random_string"] = {
                    "length_min": int(self.vars["rs_len_min"].get()),
                    "length_max": int(self.vars["rs_len_max"].get()),
                    "charset": self.vars["rs_charset"].get(),
                    "custom_charset": self.vars["rs_custom_charset"].get(),
                    "prefix": self.vars["rs_prefix"].get(),
                    "suffix": self.vars["rs_suffix"].get(),
                }

            elif mode == "random_int":
                digits_raw = self.vars["ri_digits"].get().strip()
                settings["random_int"] = {
                    "min": int(self.vars["ri_min"].get()),
                    "max": int(self.vars["ri_max"].get()),
                    "digits": int(digits_raw) if digits_raw else None,
                }

            elif mode == "sequential":
                settings["sequential"] = {
                    "start": int(self.vars["sq_start"].get()),
                    "prefix": self.vars["sq_prefix"].get(),
                    "suffix": self.vars["sq_suffix"].get(),
                    "pad": int(self.vars["sq_pad"].get() or 0),
                }

            elif mode == "wordlist":
                if not self.vars["wl_path"].get():
                    messagebox.showerror("Input tidak valid", "Pilih file wordlist terlebih dahulu.")
                    return
                settings["wordlist"] = {
                    "path": self.vars["wl_path"].get(),
                    "prefix": self.vars["wl_prefix"].get(),
                    "suffix": self.vars["wl_suffix"].get(),
                }

            elif mode == "random_choice_weighted":
                weights = []
                for val, wv in self._weight_rows:
                    weights.append({"value": val, "weight": float(wv.get() or 0)})
                settings["weights"] = weights

            elif mode == "multi_random":
                settings["multi_random"] = {
                    "count_min": int(self.vars["mr_min"].get()),
                    "count_max": int(self.vars["mr_max"].get()),
                }

            elif mode == "multi_fixed":
                settings["multi_fixed"] = {
                    "values": [val for val, cv in getattr(self, "_mf_checks", []) if cv.get()]
                }

            elif mode == "mirror":
                display = self.vars.get("mirror_display", tk.StringVar(value="")).get()
                ref_key = self._mirror_display_to_key.get(display) if hasattr(self, "_mirror_display_to_key") else None
                if not ref_key:
                    messagebox.showerror("Input tidak valid", "Pilih field rujukan terlebih dahulu.")
                    return
                settings["mirror_of"] = ref_key

        except ValueError as e:
            messagebox.showerror("Input tidak valid", f"Periksa kembali input angka: {e}")
            return

        self.result = settings
        self.destroy()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
class MainApp(tk.Tk):
    def __init__(self, config_path):
        super().__init__()
        apply_dark_theme(self)
        self.title("Form Automator - Konfigurasi (Fase 2)")
        self.geometry("820x640")

        self.config_path = config_path
        self.scraped = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.field_settings = {}

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.fields_tab = ttk.Frame(notebook)
        self.run_tab = ttk.Frame(notebook)
        notebook.add(self.fields_tab, text="Fields")
        notebook.add(self.run_tab, text="Run Settings")

        self.build_fields_tab()
        self.build_run_tab()

        ttk.Button(self, text="Simpan Konfigurasi -> field_config.json",
                   command=self.save_config).pack(pady=8)

    def build_fields_tab(self):
        canvas = styled_canvas(self.fields_tab)
        scrollbar = ttk.Scrollbar(self.fields_tab, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(scroll_frame, text="Field", font=("", 10, "bold")).grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Label(scroll_frame, text="Mode Saat Ini", font=("", 10, "bold")).grid(row=0, column=1, padx=8, pady=6, sticky="w")

        self.mode_labels = {}
        fields = self.scraped.get("fields", [])
        if not fields:
            ttk.Label(scroll_frame, text="Tidak ada field terdeteksi dari hasil scraping.").grid(
                row=1, column=0, columnspan=3, padx=8, pady=10, sticky="w")

        for i, field in enumerate(fields, start=1):
            label = field.get("label") or field.get("name") or field.get("id") or f"field_{field['index']}"
            ttk.Label(scroll_frame, text=f"{label}  ({field['tag']}/{field['type']})").grid(
                row=i, column=0, padx=8, pady=4, sticky="w")

            mode_lbl = ttk.Label(scroll_frame, text="skip", foreground=FG_MUTED)
            mode_lbl.grid(row=i, column=1, padx=8, pady=4, sticky="w")
            self.mode_labels[field["index"]] = mode_lbl

            ttk.Button(scroll_frame, text="Configure",
                       command=lambda f=field: self.open_field_dialog(f)).grid(row=i, column=2, padx=8, pady=4)

    def open_field_dialog(self, field):
        existing = self.field_settings.get(field["index"])
        dialog = FieldConfigDialog(self, field, existing, self.scraped.get("fields", []))
        apply_dark_theme(dialog)
        self.wait_window(dialog)
        if dialog.result:
            self.field_settings[field["index"]] = dialog.result
            self.mode_labels[field["index"]].config(text=dialog.result["mode"], foreground=ACCENT)

    def build_run_tab(self):
        pad = {"padx": 10, "pady": 6}

        ttk.Label(self.run_tab, text="Jumlah run:").grid(row=0, column=0, sticky="w", **pad)
        self.count_var = tk.StringVar(value="10")
        ttk.Entry(self.run_tab, textvariable=self.count_var, width=12).grid(row=0, column=1, sticky="w", **pad)
        self.endless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.run_tab, text="Endless (tidak terbatas, stop manual/Ctrl+C)",
                         variable=self.endless_var).grid(row=0, column=2, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Session mode:").grid(row=1, column=0, sticky="w", **pad)
        self.session_var = tk.StringVar(value="new")
        ttk.Radiobutton(self.run_tab, text="Context baru tiap run", variable=self.session_var,
                         value="new").grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(self.run_tab, text="Reuse session", variable=self.session_var,
                         value="reuse").grid(row=1, column=2, sticky="w")

        ttk.Label(self.run_tab, text="Jumlah thread paralel:").grid(row=2, column=0, sticky="w", **pad)
        self.thread_var = tk.StringVar(value="5")
        ttk.Entry(self.run_tab, textvariable=self.thread_var, width=8).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(self.run_tab, text="(otomatis jadi 1/sekuensial kalau session mode = 'Reuse session')",
                  foreground=FG_MUTED).grid(row=2, column=2, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Target butuh login manual dulu?").grid(row=3, column=0, sticky="w", **pad)
        self.login_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.run_tab, variable=self.login_var).grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Delay mode:").grid(row=4, column=0, sticky="w", **pad)
        self.delay_mode_var = tk.StringVar(value="none")
        ttk.Combobox(self.run_tab, textvariable=self.delay_mode_var,
                     values=["none", "fixed", "random", "smart"], state="readonly", width=12
                     ).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(self.run_tab, text="(smart = delay diperpanjang otomatis kalau ada gagal beruntun)",
                  foreground=FG_MUTED).grid(row=4, column=2, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Delay tetap (detik, untuk mode 'fixed'/'smart'):").grid(
            row=5, column=0, sticky="w", **pad)
        self.delay_fixed_var = tk.StringVar(value="1")
        ttk.Entry(self.run_tab, textvariable=self.delay_fixed_var, width=10).grid(row=5, column=1, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Delay random min/max (detik, untuk mode 'random'):").grid(
            row=6, column=0, sticky="w", **pad)
        self.delay_min_var = tk.StringVar(value="1")
        self.delay_max_var = tk.StringVar(value="3")
        ttk.Entry(self.run_tab, textvariable=self.delay_min_var, width=6).grid(row=6, column=1, sticky="w", **pad)
        ttk.Entry(self.run_tab, textvariable=self.delay_max_var, width=6).grid(row=6, column=2, sticky="w", **pad)

        ttk.Separator(self.run_tab, orient="horizontal").grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Label(self.run_tab, text="Auto-detect hasil submit (cari kata kunci umum):").grid(
            row=8, column=0, sticky="w", **pad)
        self.autodetect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.run_tab, variable=self.autodetect_var).grid(row=8, column=1, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Override: selector sukses (CSS, opsional):").grid(
            row=9, column=0, sticky="w", **pad)
        self.success_sel_var = tk.StringVar(value="")
        ttk.Entry(self.run_tab, textvariable=self.success_sel_var, width=40).grid(
            row=9, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(self.run_tab, text="Override: selector error (CSS, opsional):").grid(
            row=10, column=0, sticky="w", **pad)
        self.error_sel_var = tk.StringVar(value="")
        ttk.Entry(self.run_tab, textvariable=self.error_sel_var, width=40).grid(
            row=10, column=1, columnspan=2, sticky="w", **pad)

    def save_config(self):
        fields_out = []
        for field in self.scraped.get("fields", []):
            f = dict(field)
            f["settings"] = self.field_settings.get(field["index"], {"mode": "skip"})
            fields_out.append(f)

        # validasi ringan: pastikan tidak ada mirror_of yang circular / menunjuk field tak ada
        by_key = {f.get("name") or f.get("id") or f"field_{f['index']}": f for f in fields_out}
        for f in fields_out:
            settings = f["settings"]
            if settings.get("mode") != "mirror":
                continue
            ref = settings.get("mirror_of")
            visited = {f.get("name") or f.get("id") or f"field_{f['index']}"}
            cur = ref
            while cur:
                cur_field = by_key.get(cur)
                if cur_field is None:
                    messagebox.showerror("Konfigurasi tidak valid",
                                          f"Field mirror merujuk ke '{cur}' yang tidak ditemukan.")
                    return
                if cur_field["settings"].get("mode") != "mirror":
                    break
                if cur in visited:
                    messagebox.showerror("Konfigurasi tidak valid",
                                          f"Circular mirror reference terdeteksi pada rantai: {' -> '.join(visited)} -> {cur}")
                    return
                visited.add(cur)
                cur = cur_field["settings"].get("mirror_of")

        try:
            run_settings = {
                "count": "endless" if self.endless_var.get() else self.count_var.get(),
                "session_mode": self.session_var.get(),
                "thread_count": int(self.thread_var.get() or 1),
                "delay": {
                    "mode": self.delay_mode_var.get(),
                    "fixed_seconds": float(self.delay_fixed_var.get() or 1),
                    "random_min": float(self.delay_min_var.get() or 1),
                    "random_max": float(self.delay_max_var.get() or 3),
                },
            }
        except ValueError as e:
            messagebox.showerror("Input tidak valid", f"Periksa input di Run Settings: {e}")
            return

        detection = {
            "auto_detect": self.autodetect_var.get(),
            "success_selector": self.success_sel_var.get() or None,
            "error_selector": self.error_sel_var.get() or None,
        }

        output = {
            "url": self.scraped["url"],
            "login_required": self.login_var.get(),
            "submit_selector": self.scraped.get("submit_selector"),
            "fields": fields_out,
            "run_settings": run_settings,
            "detection": detection,
        }

        out_path = Path("field_config.json")
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        messagebox.showinfo(
            "Tersimpan",
            f"Konfigurasi disimpan ke {out_path.resolve()}\n\n"
            f"Lanjutkan dengan:\npython runner.py --config field_config.json"
        )


def main():
    ap = argparse.ArgumentParser(description="GUI konfigurasi mode isian field (Fase 2).")
    ap.add_argument("--config", default="config.json", help="Path config.json hasil scraper.py")
    args = ap.parse_args()

    app = MainApp(args.config)
    app.mainloop()


if __name__ == "__main__":
    main()