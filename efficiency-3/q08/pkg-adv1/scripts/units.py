# -*- coding: utf-8 -*-
"""units.py —— 单位换算 + 文本度量（版式预算与溢出判定的地基）。

设计取舍（写进 METHOD.md 供复核）：
- OOXML 长度单位是 EMU（1 inch = 914400 EMU），字号是 centi-point（1 pt = 100）。
- 文本行宽/行高需要**字体度量**。容器里不一定有 CJK 字体文件，因此本模块用
  「真实字体文件度量（可选）+ 字符宽度表（兜底）」的混合策略：
    * 西文/数字：优先用 PIL.ImageFont 实测；取不到字体文件时回落到 Helvetica 近似宽度表；
    * CJK/全角：按 1.0 em（中日韩等宽方块字形，宋体/黑体/思源系一致）；
    * 所有估算再乘 SAFETY(0.94) 的保守系数，宁可高估行数，不制造溢出。
- 度量只用于**预算与排序**；最终是否溢出以 render_preview.py 从导出的 PDF 里
  实测文本包围盒为准（见 fit_check.py 的 pdf 证据段）。
"""
from __future__ import annotations

import math
import os
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

EMU_PER_INCH = 914400
EMU_PER_POINT = 12700
EMU_PER_CM = 360000
SAFETY = 0.94  # 保守系数：估算可用宽度打 94 折

# Windows 控制台默认 GBK，会把中文报告打成乱码；统一 UTF-8（失败则静默忽略）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------- 基本换算

def inches(emu) -> float:
    return float(emu) / EMU_PER_INCH


def to_emu(inches_value: float) -> int:
    return int(round(float(inches_value) * EMU_PER_INCH))


def to_pt(emu) -> float:
    return float(emu) / EMU_PER_POINT


def pt_to_emu(pt: float) -> int:
    return int(round(float(pt) * EMU_PER_POINT))


def emu_to_cm(emu) -> float:
    return float(emu) / EMU_PER_CM


def fmt_in(emu) -> str:
    return "%.3fin" % inches(emu)


# ---------------------------------------------------------------- 文本度量

# 近似宽度表（单位：em），来源：Helvetica/Arial 字宽表的整数化近似
_LATIN = {
    " ": 0.278, "!": 0.278, '"': 0.355, "#": 0.556, "$": 0.556, "%": 0.889,
    "&": 0.667, "'": 0.191, "(": 0.333, ")": 0.333, "*": 0.389, "+": 0.584,
    ",": 0.278, "-": 0.333, ".": 0.278, "/": 0.278, ":": 0.278, ";": 0.278,
    "<": 0.584, "=": 0.584, ">": 0.584, "?": 0.556, "@": 1.015, "[": 0.278,
    "\\": 0.278, "]": 0.278, "^": 0.469, "_": 0.556, "`": 0.333, "{": 0.334,
    "|": 0.26, "}": 0.334, "~": 0.584,
}
for _c, _w in zip("abcdefghijklmnopqrstuvwxyz", [0.556, 0.556, 0.5, 0.556, 0.556,
                                                0.278, 0.556, 0.556, 0.222, 0.222,
                                                0.5, 0.222, 0.833, 0.556, 0.556,
                                                0.556, 0.556, 0.333, 0.5, 0.278,
                                                0.556, 0.5, 0.722, 0.5, 0.5, 0.5]):
    _LATIN[_c] = _w
for _c, _w in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [0.667, 0.667, 0.722, 0.722, 0.667,
                                                 0.611, 0.778, 0.722, 0.278, 0.5,
                                                 0.667, 0.556, 0.833, 0.722, 0.778,
                                                 0.667, 0.778, 0.722, 0.667, 0.611,
                                                 0.722, 0.667, 0.944, 0.667, 0.667, 0.611]):
    _LATIN[_c] = _w
for _c in "0123456789":
    _LATIN[_c] = 0.556
# 希腊字母（学术稿件高频）：按小写 0.55 / 大写 0.68 近似
for _c in "αβγδεζηθικλμνξοπρστυφχψω":
    _LATIN[_c] = 0.55
for _c in "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ":
    _LATIN[_c] = 0.68
for _c in "×÷±≤≥≈≠∞∑∏∫√∂%°":
    _LATIN[_c] = 0.7

_CJK_RANGES = (
    (0x1100, 0x115F), (0x2E80, 0x303E), (0x3041, 0x33FF), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA000, 0xA4CF), (0xAC00, 0xD7A3), (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6),
    (0x20000, 0x2FA1F),
)


def is_wide(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in _CJK_RANGES:
        if lo <= cp <= hi:
            return True
    return False


_FONT_CACHE: dict = {}


def _pil_font(name: str, size_px: int):
    key = (name, size_px)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(name, size_px)
    except Exception:
        font = None
    _FONT_CACHE[key] = font
    return font


def find_system_font(candidates=("DejaVuSans.ttf", "arial.ttf", "Arial.ttf",
                                 "LiberationSans-Regular.ttf")):
    """找一个可用于度量的西文字体文件；找不到返回 None（仍有宽度表兜底）。"""
    for c in candidates:
        for root in (os.environ.get("WINDIR", "C:/Windows") + "/Fonts",
                     "/usr/share/fonts/truetype/dejavu",
                     "/usr/share/fonts/truetype/liberation",
                     "/usr/share/fonts"):
            p = os.path.join(root, c)
            if os.path.isfile(p):
                return p
    return None


def text_width_em(text: str, font_file: str | None = None) -> float:
    """返回文本宽度（单位 em）。CJK 逐字 1.0，西文查表（可用则实测）。"""
    if not text:
        return 0.0
    if font_file:
        font = _pil_font(font_file, 100)
        if font is not None:
            try:
                return float(font.getlength(text)) / 100.0
            except Exception:
                pass
    total = 0.0
    for ch in text:
        if is_wide(ch):
            total += 1.0
        else:
            total += _LATIN.get(ch, 0.55)
    return total


def wrap_lines(text: str, width_in: float, size_pt: float,
               font_file: str | None = None, min_lines: int = 1) -> list:
    """按可用宽度折行，返回行列表（在空白处/汉字间断行）。"""
    width_em = max(0.1, (width_in * 72.0 * SAFETY) / max(1.0, size_pt))
    lines, cur, cur_w = [], "", 0.0
    tokens = []
    buf = ""
    for ch in text:
        if ch == " " or is_wide(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    for tok in tokens:
        w = text_width_em(tok, font_file)
        # 单个 token 比整行还宽（长英文单词/URL/无空格串）：按字符硬切
        if w > width_em:
            if cur.strip():
                lines.append(cur)
                cur, cur_w = "", 0.0
            for ch in tok:
                cw = text_width_em(ch, font_file)
                if cur and cur_w + cw > width_em:
                    lines.append(cur)
                    cur, cur_w = "", 0.0
                cur += ch
                cur_w += cw
            continue
        if cur and cur_w + w > width_em:
            lines.append(cur)
            cur, cur_w = ("", 0.0)
            if tok == " ":
                continue
        cur += tok
        cur_w += w
    if cur.strip() or not lines:
        lines.append(cur)
    while len(lines) < min_lines:
        lines.append("")
    return lines


def block_height_in(text: str, width_in: float, size_pt: float,
                    line_spacing: float = 1.0, space_before_pt: float = 0.0,
                    space_after_pt: float = 0.0, font_file: str | None = None) -> float:
    """估算一个文本框需要的高度（inch），含段前/段后。"""
    if not text:
        return 0.0
    lines = wrap_lines(text, width_in, size_pt, font_file)
    # OOXML 单倍行距 ≈ 1.2 * 字号
    return (len(lines) * size_pt * 1.2 * line_spacing + space_before_pt + space_after_pt) / 72.0


def est_capacity(width_in: float, height_in: float, size_pt: float,
                 line_spacing: float = 1.0) -> int:
    """给定容器与字号，估算可容纳的字符数（中文按 1 字=1 em 折算）。"""
    width_em = max(0.1, (width_in * 72.0 * SAFETY) / max(1.0, size_pt))
    per_line = width_em
    max_lines = max(1, int((height_in * 72.0) / (size_pt * 1.2 * line_spacing)))
    return int(per_line * max_lines)


# ---------------------------------------------------------------- 杂项

def sha256_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%dB" % n
        n /= 1024.0
    return "%dB" % n


def relpath(path: str, start: str) -> str:
    try:
        return os.path.relpath(path, start).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def _cli(argv=None) -> int:
    """独立 CLI 入口（README/RUBRIC-MAP 承诺"每个脚本都有 --help 与独立入口"）。

    units.py 是被其它脚本 import 的地基模块，但仍提供可直接调用的换算/度量命令，
    便于复核者用**同一个**度量实现独立验算版式预算：
        python units.py --selftest
        python units.py --sha256 <file>
        python units.py --capacity --width 8.5 --height 4.2 --pt 20
        python units.py --width-em "一句中文 mixed text"
    """
    import argparse
    ap = argparse.ArgumentParser(prog="units", description="单位换算 / 文本度量 / 文件哈希")
    ap.add_argument("--selftest", action="store_true", help="跑内置断言")
    ap.add_argument("--sha256", metavar="FILE", help="打印文件的 sha256")
    ap.add_argument("--capacity", action="store_true", help="按 --width/--height/--pt 估算字符容量")
    ap.add_argument("--width-em", metavar="TEXT", help="打印文本宽度（em）与折算行数")
    ap.add_argument("--width", type=float, default=8.5, help="容器宽 inch（--capacity）")
    ap.add_argument("--height", type=float, default=4.2, help="容器高 inch（--capacity）")
    ap.add_argument("--pt", type=float, default=20.0, help="字号 pt")
    a = ap.parse_args(argv)
    if a.selftest:
        assert abs(inches(914400) - 1.0) < 1e-9
        assert abs(text_width_em("abc") - 1.612) < 0.01
        assert abs(text_width_em("中文") - 2.0) < 1e-9
        assert len(wrap_lines("a" * 200, 1.0, 12)) > 1
        print("units.py self-test ok  font=%s" % (find_system_font() or "none"))
        return 0
    if a.sha256:
        print(sha256_file(a.sha256))
        return 0
    if a.capacity:
        print("capacity=%d chars @ %gpt in %gx%gin (SAFETY=%.2f)"
              % (est_capacity(a.width, a.height, a.pt), a.pt, a.width, a.height, SAFETY))
        return 0
    if a.width_em:
        em = text_width_em(a.width_em, find_system_font())
        print("width_em=%.3f lines=1 block_height_in=%.3f"
              % (em, block_height_in(a.width_em, a.width, a.pt)))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":  # 自测 / CLI
    sys.exit(_cli())
