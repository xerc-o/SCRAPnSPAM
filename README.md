# SCRAPnSPAM

SCRAPnSPAM adalah alat otomatisasi form berbasis Playwright untuk membantu
mengambil struktur form, mengonfigurasi mode pengisian, lalu menjalankan loop
submit dengan logging hasil. Proyek ini dirancang untuk penggunaan lokal dan
pengujian yang sah pada target yang Anda miliki izin eksplisit.

> **Penting — Etika & Legal**
> Gunakan tool ini hanya pada target yang Anda punya izin eksplisit untuk diuji,
> seperti scope pentest resmi, lab internal, atau aplikasi milik sendiri.
> Tool ini hanya melakukan scraping struktur form dan autofill data uji; tidak
> melakukan bypass autentikasi atau eksploitasi.

## Fitur

- Scraping elemen form dari halaman target
- Konfigurasi field melalui GUI
- Mode pengisian: fixed, random_string, random_int, sequential, wordlist,
  random_choice, dan skip
- Eksekusi loop submit dengan delay dan logging hasil
- Simpan sesi autentikasi lokal ke file auth_state.json

## Prasyarat

- Python 3.9+
- Playwright
- Browser Chromium
- Tkinter (biasanya sudah tersedia pada instalasi Python desktop)

## Instalasi

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
```

Pada Linux, jika tkinter belum tersedia:

```bash
sudo apt install python3-tk
```

## Alur Penggunaan

### 1. Scraping struktur form

```bash
python scraper.py --url "https://target.com/form" --output config.json
```

Untuk target yang membutuhkan login manual:

```bash
python scraper.py --url "https://target.com/form" --login --output config.json
```

### 2. Konfigurasi GUI

```bash
python gui.py --config config.json
```

### 3. Jalankan eksekusi

```bash
python runner.py --config field_config.json
```

Opsional:

```bash
python runner.py --config field_config.json --count 50
python runner.py --config field_config.json --count endless
```

## Output yang Dibuat

- config.json: hasil scraping form
- field_config.json: konfigurasi isian field
- auth_state.json: sesi browser yang disimpan lokal
- logs/run_log_<timestamp>.csv: log hasil eksekusi

## Keamanan & Praktik Baik

- File hasil run, konfigurasi, dan session browser secara default diabaikan oleh Git
- Jangan menambahkan data sensitif, kredensial, atau hasil scraping ke repo
- Hapus auth_state.json dan file log jika tidak lagi dibutuhkan

## Struktur Proyek

```text
scraper/
├── scraper.py
├── gui.py
├── runner.py
├── generators.py
├── config.json
├── field_config.json
├── requirements.txt
├── README.md
├── .gitignore
└── logs/
```

## Lisensi

Proyek ini menggunakan lisensi MIT.
