#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ga_core -- shared primitives for the graphical-abstract skill.

Standard library only.  No network, no CWD assumptions, no clocks inside the
figure (determinism: the same IR must produce a byte-identical SVG).
"""

from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # never leave __pycache__ behind


import json
import hashlib
import os
import re
import unicodedata
from pathlib import Path

VERSION = "1.0.0"
SKILL_NAME = "graphical-abstract-svg"

# --------------------------------------------------------------------------
# paths: every default can be overridden by env or CLI, so the package runs
# both in the platform sandbox (/input, /app/work, /app/output) and locally.
# --------------------------------------------------------------------------
SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"


def _p(env_name: str, default: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    return Path(raw) if raw else Path(default)


def paths(input_dir=None, work_dir=None, out_dir=None) -> dict:
    return {
        "input": Path(input_dir) if input_dir else _p("GA_INPUT", "/input"),
        "work": Path(work_dir) if work_dir else _p("GA_WORK", "/app/work"),
        "output": Path(out_dir) if out_dir else _p("GA_OUTPUT", "/app/output"),
        "skill": SKILL_ROOT,
    }


def ensure_dirs(p: dict) -> None:
    for k in ("work", "output"):
        try:
            p[k].mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# io helpers
# --------------------------------------------------------------------------
def load_json(path, default=None):
    try:
        with open(str(path), "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def dump_json(path, obj, indent=2) -> str:
    txt = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=False)
    txt += "\n"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
    except Exception:
        pass
    return txt


def read_text(path, limit=2_000_000) -> str:
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return ""
    if len(raw) > limit:
        raw = raw[:limit]
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def write_text(path, txt) -> bool:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
        return True
    except Exception:
        return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    try:
        return sha256_bytes(Path(path).read_bytes())
    except Exception:
        return ""


# --------------------------------------------------------------------------
# text metrics -- deterministic and backend independent.  Layout never asks a
# renderer how wide a string is, so SVG/PNG/PDF agree and reruns are identical.
# --------------------------------------------------------------------------
_W_ASCII = {
    " ": 0.278, "!": 0.278, '"': 0.355, "#": 0.556, "$": 0.556, "%": 0.889,
    "&": 0.667, "'": 0.191, "(": 0.333, ")": 0.333, "*": 0.389, "+": 0.584,
    ",": 0.278, "-": 0.333, ".": 0.278, "/": 0.278, ":": 0.278, ";": 0.278,
    "<": 0.584, "=": 0.584, ">": 0.584, "?": 0.556, "@": 1.015, "[": 0.278,
    "\\": 0.278, "]": 0.278, "^": 0.469, "_": 0.556, "`": 0.333, "{": 0.334,
    "|": 0.260, "}": 0.334, "~": 0.584,
}
for _c in "0123456789":
    _W_ASCII[_c] = 0.556
for _c in "abcdeghknopqsuvxyz":
    _W_ASCII[_c] = 0.500
for _c, _w in (("f", 0.278), ("i", 0.222), ("j", 0.222), ("l", 0.222),
               ("m", 0.833), ("r", 0.333), ("t", 0.278), ("w", 0.722)):
    _W_ASCII[_c] = _w
for _c in "ABDEHKNPRSUVXZ":
    _W_ASCII[_c] = 0.667
for _c, _w in (("C", 0.722), ("F", 0.611), ("G", 0.778), ("I", 0.278),
               ("J", 0.500), ("L", 0.556), ("M", 0.833), ("O", 0.778),
               ("Q", 0.778), ("T", 0.611), ("W", 0.944), ("Y", 0.667)):
    _W_ASCII[_c] = _w

_CJK_RANGES = (
    (0x1100, 0x115F), (0x2E80, 0x303E), (0x3041, 0x33FF), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xA000, 0xA4CF), (0xA960, 0xA97F), (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F), (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6), (0x1F300, 0x1F64F), (0x20000, 0x2FA1F),
)


def is_wide(ch: str) -> bool:
    o = ord(ch)
    if o < 0x1100:
        return False
    for lo, hi in _CJK_RANGES:
        if lo <= o <= hi:
            return True
    return unicodedata.east_asian_width(ch) in ("W", "F")


def text_width(s: str, size: float, bold: bool = False, italic: bool = False) -> float:
    """Advance width in px for a string at `size` px (em based, Helvetica-ish)."""
    total = 0.0
    for ch in s or "":
        if is_wide(ch):
            total += 1.0
        elif ch in _W_ASCII:
            total += _W_ASCII[ch]
        else:
            o = ord(ch)
            total += 0.60 if o < 0x0300 else 0.90
    if bold:
        total *= 1.045
    if italic:
        total *= 1.02
    return total * size


def wrap_text(s: str, size: float, max_w: float, bold: bool = False,
              max_lines: int = 99) -> list:
    """Greedy wrap that also breaks inside long CJK runs (no spaces there)."""
    s = (s or "").replace("\r", "")
    if not s:
        return [""]
    lines, cur = [], ""
    tokens = []
    buf = ""
    for ch in s:
        if is_wide(ch) or ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch in "-/—–":
            tokens.append(buf + ch)
            buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    for tk in tokens:
        cand = cur + tk
        if cur and text_width(cand.rstrip(), size, bold) > max_w:
            lines.append(cur.rstrip())
            cur = "" if tk == " " else tk
            if len(lines) >= max_lines:
                break
        else:
            cur = cand
    if cur.strip() and len(lines) < max_lines:
        lines.append(cur.rstrip())
    if len(lines) >= max_lines and text_width(s, size, bold) > max_w * max_lines:
        lines[-1] = _ellipsize(lines[-1], size, max_w, bold)
    return lines or [""]


def _ellipsize(s: str, size: float, max_w: float, bold: bool = False) -> str:
    s = s.rstrip()
    while s and text_width(s + "…", size, bold) > max_w:
        s = s[:-1]
    return s + "…"


def fit_text(s: str, size: float, max_w: float, bold: bool = False) -> str:
    if text_width(s, size, bold) <= max_w:
        return s
    return _ellipsize(s, size, max_w, bold)


# --------------------------------------------------------------------------
# visual grammar: colour-blind safe palette + greyscale-safe patterns
# --------------------------------------------------------------------------
PALETTE = [
    {"key": "c1", "name": "blue",    "hex": "#0072B2"},
    {"key": "c2", "name": "orange",  "hex": "#D55E00"},
    {"key": "c3", "name": "green",   "hex": "#009E73"},
    {"key": "c4", "name": "purple",  "hex": "#CC79A7"},
    {"key": "c5", "name": "amber",   "hex": "#E69F00"},
    {"key": "c6", "name": "sky",     "hex": "#56B4E9"},
    {"key": "c7", "name": "black",   "hex": "#1A1A1A"},
]
PATTERNS = ["none", "hatch45", "dots", "hatch135", "cross", "grid", "hatch90"]

# relation type -> arrow rendering.  Fixed so a given relation always looks the
# same and the legend can be derived from what is actually on the canvas.
RELATION_GRAMMAR = {
    "activation":   {"marker": "arrow",  "dash": False, "zh": "激活", "en": "activation"},
    "inhibition":   {"marker": "bar",    "dash": False, "zh": "抑制", "en": "inhibition"},
    "binding":      {"marker": "circle", "dash": False, "zh": "结合", "en": "binding"},
    "modification": {"marker": "diamond", "dash": False, "zh": "修饰", "en": "modification"},
    "transport":    {"marker": "arrow",  "dash": True,  "zh": "转运", "en": "transport"},
    "flow":         {"marker": "arrow",  "dash": False, "zh": "流程", "en": "workflow"},
    "block":        {"marker": "cross",  "dash": False, "zh": "阻断", "en": "blockade"},
    "unknown":      {"marker": "arrow",  "dash": False, "zh": "关系", "en": "relation"},
}

ENTITY_TYPES = ("protein", "gene", "cell", "tissue", "organelle", "molecule",
                "material", "device", "sample", "pathway", "condition", "readout")

PANEL_ROLES = ("problem", "method", "results", "conclusion")
ROLE_LABEL = {
    "problem": ("① PROBLEM", "研究问题"),
    "method": ("② METHOD", "方法路线"),
    "results": ("③ RESULTS", "核心结果"),
    "conclusion": ("④ CONCLUSION", "结论/意义"),
}

DEFAULT_CANVAS = {
    "width_px": 2400,
    "height_px": 1350,
    "dpi": 300,
    "background": "#FFFFFF",
    "min_font_px": 20,
    "max_font_px": 72,
}

# --------------------------------------------------------------------------
# output contract
# --------------------------------------------------------------------------
# The seven-field product contract used by this family of challenges.  When
# /input/case.json carries its own output_contract we echo *its* keys verbatim
# and keep these as a superset, so nothing required is ever missing.
DEFAULT_CONTRACT = [
    "case_id", "status", "editable_source", "export_artifact",
    "content_map", "compliance_checks", "exceptions",
]

CONTRACT_ALIASES = {
    "editable_source": ["editable_source", "source_file", "source", "editable",
                        "source_artifact", "editable_sources", "figure_source"],
    "export_artifact": ["export_artifact", "export", "exports", "artifacts",
                        "export_artifacts", "figure", "output_files", "deliverables"],
    "content_map": ["content_map", "elements", "element_map", "entity_map",
                    "figure_model", "content_model", "mapping", "content"],
    "compliance_checks": ["compliance_checks", "compliance", "checks",
                          "export_checks", "quality_checks"],
    "exceptions": ["exceptions", "issues", "errors", "limitations", "degradations"],
    "status": ["status", "state", "outcome"],
}


def resolve_contract(case: dict) -> dict:
    """Find the requested output contract inside the case payload."""
    found_keys, found_shape, raw = [], "none", None
    if isinstance(case, dict):
        for key in ("output_contract", "outputs_contract", "contract", "output_schema",
                    "required_outputs", "expected_outputs"):
            if key in case and case[key] not in (None, "", [], {}):
                raw = case[key]
                found_shape = "list" if isinstance(raw, list) else "dict"
                break
    keys = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                nm = item.get("name") or item.get("field") or item.get("key") or item.get("id")
                if nm:
                    keys.append(str(nm))
            elif isinstance(item, str):
                keys.append(item)
    elif isinstance(raw, dict):
        for key, val in raw.items():
            keys.append(str(key))
            if isinstance(val, dict):
                for sub in val.keys():
                    keys.append("%s.%s" % (key, sub))
    contract_keys = keys or list(DEFAULT_CONTRACT)
    if "case_id" not in contract_keys:
        contract_keys = ["case_id"] + contract_keys
    return {
        "declared": raw is not None,
        "shape": found_shape,
        "keys": contract_keys,
        "raw": raw,
    }


# --------------------------------------------------------------------------
# IR normalisation / validation
# --------------------------------------------------------------------------
def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _s(v, default=""):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return default
    return str(v)


def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def default_source(sid="", path="", locator="", quote=""):
    return {"id": sid, "path": path, "locator": locator, "quote": quote}


def normalize_source(src, default_id="") -> dict:
    if not isinstance(src, dict):
        return default_source(default_id)
    sid = _s(src.get("id") or src.get("source_id") or default_id)
    return {
        "id": sid,
        "path": _s(src.get("path") or src.get("file") or src.get("source")),
        "locator": _s(src.get("locator") or src.get("location") or src.get("page")),
        "quote": _s(src.get("quote") or src.get("text") or src.get("excerpt")),
        "kind": _s(src.get("kind")),
    }


def normalize_ir(raw: dict, case_id: str = "") -> dict:
    raw = raw if isinstance(raw, dict) else {}
    canvas = dict(DEFAULT_CANVAS)
    if isinstance(raw.get("canvas"), dict):
        for k in list(canvas.keys()):
            if k in raw["canvas"]:
                if k == "background":
                    canvas[k] = _s(raw["canvas"][k], canvas[k])
                else:
                    canvas[k] = int(_num(raw["canvas"][k], canvas[k]))
    canvas["width_px"] = max(600, min(6000, canvas["width_px"]))
    canvas["height_px"] = max(400, min(6000, canvas["height_px"]))
    canvas["dpi"] = max(72, min(1200, canvas["dpi"]))
    canvas["min_font_px"] = max(8, min(40, canvas["min_font_px"]))

    panels = []
    for i, p in enumerate(_as_list(raw.get("panels") or raw.get("sections"))):
        if not isinstance(p, dict):
            continue
        role = _s(p.get("role"), "").lower()
        if role not in PANEL_ROLES:
            role = "problem" if i == 0 else ("method" if i == 1 else
                    ("results" if i == 2 else "conclusion"))
        body = p.get("body") if isinstance(p.get("body"), dict) else {}
        kind = _s(body.get("kind") or p.get("kind"), "bullets").lower()
        items = []
        src_items = body.get("items") if body.get("items") is not None else p.get("items")
        for j, it in enumerate(_as_list(src_items)):
            if isinstance(it, dict):
                items.append({
                    "id": _s(it.get("id"), "p%d-i%d" % (i + 1, j + 1)),
                    "text": _s(it.get("text") or it.get("label") or it.get("claim")),
                    "kind": _s(it.get("kind"), "item"),
                    "priority": _s(it.get("priority"), "normal"),
                    "entity": _s(it.get("entity")),
                    "source": normalize_source(it.get("source"), "S1"),
                })
            else:
                items.append({"id": "p%d-i%d" % (i + 1, j + 1), "text": _s(it),
                              "kind": "item", "priority": "normal", "entity": "",
                              "source": default_source("S1")})
        panels.append({
            "order": int(_num(p.get("order"), i + 1)),
            "role": role,
            "title": _s(p.get("title") or p.get("name"), ""),
            "claim": _s(p.get("claim") or p.get("message") or p.get("point")),
            "kind": kind,
            "chart": _s(body.get("chart") or p.get("chart")),
            "relations": [_s(x) for x in _as_list(body.get("relations") or p.get("relations"))],
            "items": items,
            "source": normalize_source(p.get("source"), "S1"),
        })
    panels.sort(key=lambda q: q["order"])
    if not panels:
        panels = [{"order": i + 1, "role": r, "title": "", "claim": "", "kind": "bullets",
                   "chart": "", "relations": [], "items": [], "source": default_source("S1")}
                  for i, r in enumerate(PANEL_ROLES)]

    entities = []
    for k, e in enumerate(_as_list(raw.get("entities"))):
        if not isinstance(e, dict):
            e = {"label": _s(e)}
        etype = _s(e.get("type"), "").lower()
        entities.append({
            "id": _s(e.get("id"), "E%d" % (k + 1)),
            "label": _s(e.get("label") or e.get("name") or e.get("text")),
            "type": etype if etype in ENTITY_TYPES else (etype or "molecule"),
            "compartment": _s(e.get("compartment"), ""),
            "italic": bool(e.get("italic")),
            "source": normalize_source(e.get("source"), "S1"),
        })

    eids = {e["id"] for e in entities}
    relations = []
    for k, r in enumerate(_as_list(raw.get("relations") or raw.get("edges"))):
        if not isinstance(r, dict):
            continue
        rtype = _s(r.get("type") or r.get("relation_type"), "unknown").lower()
        if rtype not in RELATION_GRAMMAR:
            rtype = "unknown"
        frm = _s(r.get("from") or r.get("source_entity") or r.get("subject"))
        to = _s(r.get("to") or r.get("target_entity") or r.get("object"))
        relations.append({
            "id": _s(r.get("id"), "R%d" % (k + 1)),
            "from": frm,
            "to": to,
            "type": rtype,
            "label": _s(r.get("label") or r.get("text")),
            "source": normalize_source(r.get("source"), "S1"),
            "unresolved": bool(frm not in eids or to not in eids),
        })

    charts = []
    for k, c in enumerate(_as_list(raw.get("charts") or raw.get("data"))):
        if not isinstance(c, dict):
            continue
        series = []
        for si, s in enumerate(_as_list(c.get("series") or c.get("groups"))):
            if not isinstance(s, dict):
                continue
            pts = []
            for pi, pt in enumerate(_as_list(s.get("points") or s.get("values") or s.get("data"))):
                if isinstance(pt, dict):
                    pts.append({
                        "x": _s(pt.get("x") or pt.get("label")),
                        "y": _num(pt.get("y") if pt.get("y") is not None else pt.get("value")),
                        "raw": _s(pt.get("raw") or pt.get("raw_value"), ""),
                        "err": _num(pt.get("err") or pt.get("sd") or pt.get("error"), 0.0),
                        "source": normalize_source(pt.get("source"), "S1"),
                    })
                else:
                    pts.append({"x": "v%d" % (pi + 1), "y": _num(pt), "raw": _s(pt),
                                "err": 0.0, "source": default_source("S1")})
            series.append({
                "name": _s(s.get("name") or s.get("label"), "series %d" % (si + 1)),
                "color_key": _s(s.get("color_key") or s.get("key"), "c%d" % (si + 1)),
                "points": pts,
            })
        charts.append({
            "id": _s(c.get("id"), "CH%d" % (k + 1)),
            "kind": _s(c.get("kind") or c.get("type"), "bar").lower(),
            "title": _s(c.get("title")),
            "x_label": _s(c.get("x_label") or c.get("xlabel")),
            "y_label": _s(c.get("y_label") or c.get("ylabel")),
            "unit": _s(c.get("unit") or c.get("y_unit")),
            "series": series,
            "source": normalize_source(c.get("source"), "S1"),
        })

    legend = []
    for k, li in enumerate(_as_list((raw.get("legend") or {}).get("items")
                                    if isinstance(raw.get("legend"), dict) else raw.get("legend"))):
        if not isinstance(li, dict):
            li = {"label": _s(li)}
        legend.append({
            "key": _s(li.get("key"), "L%d" % (k + 1)),
            "label": _s(li.get("label") or li.get("text")),
            "channel": _s(li.get("channel"), "fill").lower(),
            "color": _s(li.get("color")),
            "pattern": _s(li.get("pattern"), "none"),
            "marker": _s(li.get("marker")),
            "source": normalize_source(li.get("source"), "S1"),
        })

    notes = raw.get("notes") if isinstance(raw.get("notes"), dict) else {}
    claims = []
    for k, cl in enumerate(_as_list(raw.get("claims") or raw.get("key_numbers")
                                    or raw.get("metrics"))):
        if not isinstance(cl, dict):
            continue
        comp = cl.get("compare") if isinstance(cl.get("compare"), dict) else {}
        claims.append({
            "id": _s(cl.get("id"), "K%d" % (k + 1)),
            "label": _s(cl.get("label") or cl.get("name") or cl.get("metric")),
            "value": cl.get("value"),
            "unit": _s(cl.get("unit")),
            "compare": {"label": _s(comp.get("label")), "value": comp.get("value")},
            "source": normalize_source(cl.get("source"), "S1"),
        })
    sources = []
    for k, s in enumerate(_as_list(raw.get("sources"))):
        ns = normalize_source(s, "S%d" % (k + 1))
        if not ns["id"]:
            ns["id"] = "S%d" % (k + 1)
        sources.append(ns)
    for s in panels + entities + relations + charts + legend:
        pass
    for bucket in (panels, entities, relations, charts, legend):
        for item in bucket:
            src = item.get("source") or {}
            sid = src.get("id") or ""
            if sid and sid not in [x["id"] for x in sources]:
                sources.append(dict(src))

    edit = raw.get("edit") if isinstance(raw.get("edit"), dict) else {}
    ir = {
        "version": VERSION,
        "case_id": _s(raw.get("case_id") or case_id),
        "origin": _s(raw.get("origin"), "curated"),
        "mode": _s(raw.get("mode"), "edit" if edit.get("source_svg") else "create").lower(),
        "title": _s(raw.get("title")),
        "subtitle": _s(raw.get("subtitle") or raw.get("claim")),
        "canvas": canvas,
        "panels": panels[:6],
        "entities": entities,
        "relations": relations,
        "charts": charts,
        "claims": claims,
        "legend": legend,
        "notes": {
            "units": _s(notes.get("units")),
            "conditions": _s(notes.get("conditions")),
            "scale_bar": _s(notes.get("scale_bar")),
            "caption": _s(notes.get("caption")),
            "figure_no": _s(notes.get("figure_no") or notes.get("fig"), "Figure 1"),
        },
        "sources": sources,
        "edit": {
            "source_svg": _s(edit.get("source_svg")),
            "operations": _as_list(edit.get("operations")),
        },
        "uncertainty": _as_list(raw.get("uncertainty")),
        "must_include": [_s(x) for x in _as_list(raw.get("must_include"))],
    }
    if not ir["must_include"]:
        ir["must_include"] = [e["label"] for e in entities] + \
                             [i["text"] for p in panels for i in p["items"]]
    return ir


def validate_ir(ir: dict) -> dict:
    """Structural checks that do not need the source material."""
    errors, warnings = [], []
    if not ir.get("panels"):
        errors.append("panels 为空：至少需要 problem/method/results/conclusion 四段")
    roles = [p["role"] for p in ir.get("panels", [])]
    for need in ("problem", "method", "results", "conclusion"):
        if need not in roles:
            warnings.append("缺少 %s 面板（四要素完整性）" % need)
    if len(ir.get("panels", [])) > 4:
        warnings.append("面板 %d 个，单页超过 4 段会被压缩为 4 段" % len(ir["panels"]))
    if not ir.get("title"):
        warnings.append("缺标题 title")
    seen = set()
    for e in ir.get("entities", []):
        if not e["label"]:
            errors.append("实体 %s 无 label" % e["id"])
        if e["id"] in seen:
            errors.append("实体 id 重复: %s" % e["id"])
        seen.add(e["id"])
    for r in ir.get("relations", []):
        if r["unresolved"]:
            warnings.append("关系 %s 的端点不在 entities（%s->%s），该边不会绘制"
                            % (r["id"], r["from"], r["to"]))
    for c in ir.get("charts", []):
        if not c["series"]:
            errors.append("图表 %s 没有 series" % c["id"])
        for s in c["series"]:
            if not s["points"]:
                errors.append("图表 %s/%s 没有数据点" % (c["id"], s["name"]))
    if ir.get("mode") == "edit" and not ir["edit"].get("source_svg"):
        warnings.append("mode=edit 但未给 edit.source_svg，将退化为 create")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


