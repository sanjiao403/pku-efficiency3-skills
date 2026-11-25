"""util.py - shared helpers for paper2deck.

Dependency policy: standard library only for everything except the actual
OOXML write (python-pptx) and the optional preview rasteriser (Pillow).
Nothing here touches the network, user home directories or environment
secrets.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata

# ---------------------------------------------------------------- text utils

CJK_RE = re.compile(
    "[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f\u3040-\u30ff\uac00-\ud7af]"
)

_WS = re.compile(r"[ \t\u00a0\u3000]+")
_WS_LINE = re.compile(r"[ \t\u00a0\u3000]*\n[ \t\u00a0\u3000]*")


def is_cjk(ch: str) -> bool:
    return bool(CJK_RE.match(ch))


def squish(s: str) -> str:
    """Collapse runs of inline whitespace, keep paragraph breaks of one."""
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _WS.sub(" ", s)
    s = _WS_LINE.sub("\n", s)
    return s.strip()


def one_line(s: str) -> str:
    return _WS.sub(" ", (s or "").replace("\n", " ")).strip()


def norm_key(s: str) -> str:
    """Normalised comparison key: NFKC, lower, whitespace removed."""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s\u00a0\u3000]+", "", s)
    return s


def quote_key(s: str) -> str:
    """Robust key for locating a quote in extracted text.

    PDF text extraction introduces column separators, line breaks and soft
    hyphens, so a strictly verbatim search fails on quotes that *are* in the
    paper.  This key keeps only word characters and CJK: enough to prove the
    sentence exists, while ``norm_key`` is tried first for an exact hit.
    """
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[\s\u00a0\u3000]+", "", s)
    s = re.sub(r"[\u00ad\-]{1}(?=[a-z\u4e00-\u9fff])", "", s)  # soft hyphen / line hyphen
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s, flags=re.UNICODE)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def truncate(s: str, n: int, ell: str = "\u2026") -> str:
    s = one_line(s)
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + ell


def display_width(s: str) -> float:
    """Approximate typographic advance in em units.

    Wide (CJK / fullwidth) glyphs count 1.0 em, narrow Latin ~0.53 em average,
    digits 0.56, punctuation narrower.  Used by layout.py; kept here so tests
    can pin it.
    """
    w = 0.0
    for ch in s:
        o = ord(ch)
        if ch == "\t":
            w += 2.0
        elif is_cjk(ch):
            w += 1.0
        elif ch.isdigit():
            w += 0.56
        elif ch in "ilI.,:;'|!()[]{}":
            w += 0.28
        elif ch in "mwMW@%":
            w += 0.95
        elif ch in " -+":
            w += 0.32
        elif o > 0x2000 and o < 0x2100:  # general punctuation / dashes / quotes
            w += 0.50
        elif ch.isupper():
            w += 0.68
        else:
            w += 0.53
    return w


# ---------------------------------------------------------------- file utils

def read_text(path: str) -> str:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def write_text(path: str, text: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def write_json(path: str, obj) -> str:
    return write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def load_json_if(path: str):
    try:
        return read_json(path)
    except Exception:
        return None


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def rel_posix(path: str) -> str:
    return path.replace("\\", "/")


def find_first(root: str, names, exts=()) -> str | None:
    """Find the first file under *root* matching one of *names* (case-insens.)."""
    want = {n.lower() for n in names}
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            low = fn.lower()
            if low in want:
                hits.append(os.path.join(dirpath, fn))
            elif exts and os.path.splitext(low)[1] in exts:
                hits.append(os.path.join(dirpath, fn))
    hits.sort(key=lambda p: (len(p), p))
    return hits[0] if hits else None


# ---------------------------------------------------------------- misc

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def pct(a: float, b: float) -> float:
    return 0.0 if not b else round(100.0 * a / b, 1)


class Log:
    """Tiny append-only run log that is also printable."""

    def __init__(self, path: str | None = None, echo: bool = True):
        self.path = path
        self.echo = echo
        self.lines: list[str] = []
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def __call__(self, msg: str, level: str = "INFO"):
        line = f"[{level}] {msg}"
        self.lines.append(line)
        if self.echo:
            print(line, file=sys.stderr if level in ("WARN", "ERROR") else sys.stdout)
        if self.path:
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")

    def warn(self, msg):
        self(msg, "WARN")

    def error(self, msg):
        self(msg, "ERROR")

    def save(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(self.lines) + "\n")
