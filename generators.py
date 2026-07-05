#!/usr/bin/env python3
"""
generators.py - Helper untuk generate nilai isian field:
random string (custom charset & panjang, prefix/suffix), random integer,
sequential counter, dan wordlist picker.
"""

import random
import string
import threading


def random_string(length_min, length_max, charset_type="alnum", custom_charset=None,
                   prefix="", suffix=""):
    length_min = max(0, int(length_min))
    length_max = max(length_min, int(length_max))
    length = random.randint(length_min, length_max)

    if charset_type == "custom" and custom_charset:
        chars = custom_charset
    elif charset_type == "letters":
        chars = string.ascii_letters
    elif charset_type == "upper":
        chars = string.ascii_uppercase
    elif charset_type == "lower":
        chars = string.ascii_lowercase
    elif charset_type == "digits":
        chars = string.digits
    else:  # alnum (default)
        chars = string.ascii_letters + string.digits

    if not chars:
        chars = string.ascii_letters + string.digits

    body = "".join(random.choice(chars) for _ in range(length))
    return f"{prefix}{body}{suffix}"


def random_int(min_val=0, max_val=9999, digits=None):
    if digits:
        digits = int(digits)
        return str(random.randint(0, 10 ** digits - 1)).zfill(digits)
    return str(random.randint(int(min_val), int(max_val)))


class SequentialCounter:
    """Thread-safe: aman dipakai bareng banyak thread tanpa loncat/dobel nilai."""
    def __init__(self, start=1, prefix="", suffix="", pad=0):
        self.counter = int(start)
        self.prefix = prefix
        self.suffix = suffix
        self.pad = int(pad or 0)
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            val = str(self.counter).zfill(self.pad) if self.pad else str(self.counter)
            result = f"{self.prefix}{val}{self.suffix}"
            self.counter += 1
            return result


class WordlistPicker:
    """Thread-safe: load sekali, pick() aman dipanggil dari banyak thread."""
    def __init__(self, path, prefix="", suffix=""):
        with open(path, "r", encoding="utf-8") as f:
            self.words = [line.strip() for line in f if line.strip()]
        if not self.words:
            raise ValueError(f"Wordlist kosong: {path}")
        self.prefix = prefix
        self.suffix = suffix
        self._lock = threading.Lock()

    def pick(self):
        with self._lock:
            word = random.choice(self.words)
        return f"{self.prefix}{word}{self.suffix}"


def generate_value(field_settings, state):
    """
    field_settings: dict konfigurasi mode dari GUI (settings key pada field).
    state: dict shared antar-run untuk menyimpan counter/wordlist per field,
           harus punya key 'sequential' dan 'wordlist' (dict kosong di awal),
           dan 'field_key' unik untuk field ini disisipkan oleh caller.
    """
    mode = field_settings.get("mode", "skip")
    field_key = field_settings.get("_field_key", "unknown")

    if mode == "skip":
        return None

    if mode == "fixed":
        return field_settings.get("fixed_value", "")

    if mode == "random_string":
        rs = field_settings.get("random_string", {})
        return random_string(
            rs.get("length_min", 8),
            rs.get("length_max", 8),
            rs.get("charset", "alnum"),
            rs.get("custom_charset"),
            rs.get("prefix", ""),
            rs.get("suffix", ""),
        )

    if mode == "random_int":
        ri = field_settings.get("random_int", {})
        return random_int(ri.get("min", 0), ri.get("max", 9999), ri.get("digits"))

    if mode == "sequential":
        if field_key not in state["sequential"]:
            sq = field_settings.get("sequential", {})
            state["sequential"][field_key] = SequentialCounter(
                sq.get("start", 1), sq.get("prefix", ""), sq.get("suffix", ""), sq.get("pad", 0)
            )
        return state["sequential"][field_key].next()

    if mode == "wordlist":
        if field_key not in state["wordlist"]:
            wl = field_settings.get("wordlist", {})
            state["wordlist"][field_key] = WordlistPicker(
                wl.get("path"), wl.get("prefix", ""), wl.get("suffix", "")
            )
        return state["wordlist"][field_key].pick()

    return None