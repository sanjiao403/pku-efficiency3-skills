"""inventory.py - build the *evidence inventory* the deck must stay inside.

The central idea of this skill: a slide may only assert what the source itself
contains.  So before any page is planned we index, with locators:

* numbers with units       ``3.7 degC``, ``0.86``, ``24.5%``, ``12 stations``
* figure / table / eq refs ``Figure 3``, ``Table 2``, ``Eq. (1)``
* captions                 what each figure/table actually is
* definitions / claims     sentences carrying the paper's main verbs
* limitations              sentences with explicit limitation wording
* citations                citation keys + bib metadata

``verify_value`` / ``verify_locator`` are the two functions the page validator
calls; they are the reason the deck cannot silently rewrite a number or cite a
figure that does not exist.
"""
from __future__ import annotations

import re

from util import norm_key, one_line, squish

# ------------------------------------------------------------------ patterns

_UNIT = (r"(?:%|‰|°C|℃|K|km2|km²|km|m2|m²|m|cm|mm|nm|µm|μm|kg|g|mg|t|s|ms|µs|μs|"
         r"min|h|hr|Hz|kHz|MHz|GHz|Pa|kPa|MPa|GPa|J|kJ|MJ|W|kW|MW|GW|Wh|kWh|"
         r"V|mV|kV|A|mA|dB|mol|L|mL|M|mM|ppm|ppb|×|x|σ|R2|R²|"
         r"degC|days?|years?|stations?|samples?|pixels?|cells?|epochs?|layers?|"
         r"participants?|subjects?|images?|patients?|sites?|plots?|trials?|runs?)")

_NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<num>[-+−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+−]?\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>" + _UNIT + r")(?![\w]))?"
)

_PCT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>%|percent\b|‰)")

# metric = value  (R2 = 0.86 / MAE: 3.7 / RMSE 1.24 / IoU 0.71)
_METRIC_RE = re.compile(
    r"(?<![A-Za-z])(?P<metric>R\s*[\u00b2\u2070-\u2079]|R2|RMSE|MAE|MAPE|AUC|ROC[\s-]?AUC|"
    r"F1|IoU|mIoU|PSNR|SSIM|Accuracy|Precision|Recall|kappa|NSE|KGE|Bias|"
    r"coverage|RMSEA|CFI|TLI|p[\s-]?value|n)(?![A-Za-z])"
    r"\s*(?:=|:|is|of)\s*(?P<num>[-+]?\d+(?:\.\d+)?)",
    re.I)

# fallback: "0.86 (R2)" or "R2, 0.86"
_METRIC_TRAIL_RE = re.compile(
    r"(?P<num>[-+]?\d+(?:\.\d+)?)\s*\(?(?P<metric>R\s*[\u00b2\u2070-\u2079]|R2|RMSE|MAE|AUC|F1|IoU|"
    r"kappa|SSIM|PSNR|NSE)(?![A-Za-z])", re.I)

_REF_RE = re.compile(
    r"\b(?:Figure|Fig\.|Table|Tab\.|Algorithm|Eq\.|Equation|Section|Sec\.|"
    r"Appendix|Supplementary (?:Table|Fig(?:ure)?)|图|表|式)"
    r"\s*\(?(\d+(?:[.\-]\d+)?|[IVX]+|[A-Z]\d+)\)?",
    re.I,
)

_CITE_KEY_RE = re.compile(r"\[([A-Za-z][\w:.\-]*(?:\s*,\s*[A-Za-z][\w:.\-]*)*)\]")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_CLAIM_VERBS = re.compile(
    r"\b(we (?:propose|present|introduce|develop|show|find|demonstrate|report|observe|"
    r"estimate|argue|conclude)|our (?:method|approach|model|framework|results?)|"
    r"results? (?:show|suggest|indicate)|this (?:paper|study|work))\b", re.I)

_LIMIT_CUES = re.compile(
    r"\b(limitation|limited to|only|not (?:yet )?(?:account|consider|include|capture)|"
    r"remains? (?:unclear|open|unknown)|future work|caveat|however|"
    r"cann?ot|fail(?:s|ed)? to|underestimate|overestimate|"
    r"assum(?:e|es|ption)|constrain(?:ed|t)|敏感|局限|不足|尚不)\b", re.I)

_RESULT_CUES = re.compile(
    r"\b(improv\w*|reduc\w*|outperform\w*|achiev\w*|reach\w*|increase\w*|decrease\w*|"
    r"higher|lower|better than|compared (?:to|with)|cuts?\b|saves?\b|"
    r"\u63d0\u5347|\u964d\u4f4e|\u51cf\u5c11|\u4f18\u4e8e|\u8fbe\u5230)\b", re.I)

_OBJECT_LINE = re.compile(r"^(objective|goal|aim|purpose|question|hypothesis)\b", re.I)


def _clean_num(num: str) -> str:
    n = num.replace("−", "-").replace(",", "")
    if n.startswith("+"):
        n = n[1:]
    return n


def norm_number(raw: str) -> str:
    """Canonical numeric form so 0.860 == 0.86 and 3.70 == 3.7."""
    s = _clean_num(raw)
    try:
        v = float(s)
    except ValueError:
        return s
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    out = f"{v:.8f}".rstrip("0").rstrip(".")
    return out or "0"


def norm_unit(unit: str | None) -> str:
    if not unit:
        return ""
    u = unit.strip().lower()
    alias = {
        "℃": "°c", "degc": "°c", "c": "°c",
        "%": "%", "percent": "%", "‰": "‰",
        "r2": "r²", "r²": "r²",
        "km2": "km²", "km²": "km²", "m2": "m²", "m²": "m²",
        "μm": "μm", "µm": "μm",
        "hr": "h", "hours": "h", "hour": "h",
        "years": "year", "days": "day", "stations": "station", "samples": "sample",
        "participants": "participant", "subjects": "subject", "sites": "site",
        "images": "image", "patients": "patient", "layers": "layer",
        "epochs": "epoch", "cells": "cell", "plots": "plot", "runs": "run",
        "trials": "trial", "pixels": "pixel",
    }
    u = u.rstrip(".")
    return alias.get(u, u)


# ------------------------------------------------------------------ class

class Inventory:
    def __init__(self):
        self.numbers: list[dict] = []     # {value, raw, unit, unit_norm, seg}
        self.refs: list[dict] = []        # {label:'Figure 3', kind, num, seg}
        self.captions: list[dict] = []    # {label, kind, num, text, seg}
        self.claims: list[dict] = []      # {text, seg, score}
        self.limits: list[dict] = []      # {text, seg}
        self.citations: list[dict] = []   # {key, seg, bib}
        self.objectives: list[dict] = []
        self.headings: list[dict] = []
        self.tables: list[dict] = []      # {label, header, rows, seg, source}
        self.bib: dict[str, dict] = {}
        self.notes: list[str] = []

    # --------------------------------------------------------- serialisation
    def to_dict(self, src=None, cap: int = 400) -> dict:
        def loc(seg):
            return src.locator(seg) if src is not None else seg.get("source", "")

        return {
            "counts": {
                "segments": len(src.segments) if src is not None else None,
                "numbers": len(self.numbers),
                "figure_refs": sum(1 for r in self.refs if r["kind"] == "figure"),
                "table_refs": sum(1 for r in self.refs if r["kind"] == "table"),
                "captions": len(self.captions),
                "claims": len(self.claims),
                "limitations": len(self.limits),
                "citations": len(self.citations),
                "headings": len(self.headings),
            },
            "numbers": [
                {"value": n["value"], "raw": n["raw"], "unit": n["unit_norm"],
                 "locator": loc(n["seg"]), "verbatim": n.get("verbatim", ""),
                 "line": n.get("line"), "page": n.get("page"),
                 "verify_cmd": n.get("verify_cmd", "")}
                for n in self.numbers[:cap]
            ],
            "captions": [
                {"label": c["label"], "kind": c["kind"], "text": c["text"][:220],
                 "locator": loc(c["seg"]), "verbatim": c.get("verbatim", ""),
                 "line": c.get("line"), "page": c.get("page"),
                 "verify_cmd": c.get("verify_cmd", "")}
                for c in self.captions[:cap]
            ],
            "tables": [
                {"label": t["label"], "header": t["header"], "rows": t["rows"][:12],
                 "locator": loc(t["seg"])}
                for t in self.tables[:20]
            ],
            "refs": [
                {"label": r["label"], "kind": r["kind"], "locator": loc(r["seg"])}
                for r in self.refs[:cap]
            ],
            "citations": [
                {"key": c["key"], "locator": loc(c["seg"]),
                 "bib": self.bib.get(c["key"])}
                for c in self.citations[:cap]
            ],
            "limitations": [
                {"text": t["text"][:300], "locator": loc(t["seg"]),
                 "verbatim": t.get("verbatim", ""), "line": t.get("line"),
                 "verify_cmd": t.get("verify_cmd", "")}
                for t in self.limits[:cap]
            ],
            "claims": [
                {"text": t["text"][:300], "locator": loc(t["seg"]), "score": t["score"],
                 "verbatim": t.get("verbatim", ""), "line": t.get("line"),
                 "verify_cmd": t.get("verify_cmd", "")}
                for t in self.claims[:cap]
            ],
            "triples": triples(self)[:cap],
            "notes": self.notes,
        }

    # --------------------------------------------------------- lookups
    def has_number(self, raw: str, unit: str | None = None) -> bool:
        """Is this value present with this unit?

        A unitless occurrence in the source does **not** license an assertion that
        carries a unit: "3.7" in a table cell proves the number, not that it is
        "3.7 kg".  Bearing a unit therefore requires an exact unit match.
        """
        v = norm_number(raw)
        u = norm_unit(unit)
        for n in self.numbers:
            if n["value"] != v:
                continue
            if not u:
                return True
            if n["unit_norm"] == u:
                return True
        return False

    def number_units(self, raw: str) -> set[str]:
        v = norm_number(raw)
        return {n["unit_norm"] for n in self.numbers if n["value"] == v}

    def has_ref(self, label: str) -> bool:
        want = _ref_key(label)
        return any(_ref_key(r["label"]) == want for r in self.refs)

    def caption_for(self, label: str):
        want = _ref_key(label)
        for c in self.captions:
            if _ref_key(c["label"]) == want:
                return c
        return None

    def table_for(self, label: str):
        want = _ref_key(label)
        exact = [t for t in self.tables if t["label"] and _ref_key(t["label"]) == want]
        if exact:
            return exact[0]
        return self.tables[0] if len(self.tables) == 1 else None

    @property
    def table_captions(self):
        return [c for c in self.captions if c["kind"] == "table"]

    def max_kind(self, kind: str) -> int:
        best = 0
        for c in self.captions:
            if c["kind"] == kind:
                best = max(best, c["num"])
        for r in self.refs:
            if r["kind"] == kind:
                best = max(best, r["num"])
        return best


def _ref_key(label: str) -> str:
    low = norm_key(label)
    low = (low.replace("figure", "fig").replace("fig.", "fig")
              .replace("table", "tab").replace("tab.", "tab")
              .replace("equation", "eq").replace("eq.", "eq")
              .replace("section", "sec").replace("sec.", "sec"))
    low = re.sub(r"[^a-z0-9.\u4e00-\u9fff]", "", low)
    m = re.match(r"^(fig|tab|eq|sec|alg|sfig|stab)([\da-z.\-]+)$", low)
    return f"{m.group(1)}:{m.group(2)}" if m else low


_KIND_MAP = [("figure", "figure"), ("fig", "figure"), ("table", "table"),
             ("tab", "table"), ("equation", "equation"), ("eq", "equation"),
             ("section", "section"), ("sec", "section"), ("algorithm", "algorithm"),
             ("alg", "algorithm")]


def _kind_of(label: str) -> str:
    low = norm_key(label)
    for pre, kind in _KIND_MAP:
        if low.startswith(pre):
            return kind
    if low.startswith("图"):
        return "figure"
    if low.startswith("表"):
        return "table"
    return "other"


def _num_of(label: str) -> int:
    m = re.search(r"(\d+)", label)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------ builder

def build(src) -> Inventory:
    inv = Inventory()
    inv.bib = dict(src.bib)
    _collect_tables(src, inv)
    for seg in src.segments:
        text = seg["text"]
        if seg["kind"] == "table-row":
            _scan_numbers(text, seg, inv)
            continue
        if seg["kind"] == "heading":
            inv.headings.append({"text": text, "seg": seg})
            continue
        if seg["kind"] == "caption":
            m = _REF_RE.match(text)
            if m:
                label = f"{_kind_of(text)} {m.group(1)}".title()
                label = label.replace("Fig 1", "Figure 1").replace("Tab ", "Table ")
                kind = _kind_of(text)
                label = {"figure": "Figure", "table": "Table",
                         "equation": "Equation"}.get(kind, "Figure") + f" {m.group(1)}"
                inv.captions.append({"label": label, "kind": kind,
                                     "num": _num_of(m.group(1)),
                                     "text": text, "seg": seg})
            else:
                inv.notes.append(f"caption-like segment without a number: {text[:60]}")
            _scan_numbers(text, seg, inv)
            continue
        _scan_numbers(text, seg, inv)
        for m in _REF_RE.finditer(text):
            kind = _kind_of(m.group(0).split()[0] if m.group(0).split() else "figure")
            if kind == "other":
                continue
            inv.refs.append({
                "label": f"{ {'figure': 'Figure', 'table': 'Table', 'equation': 'Equation',
                              'section': 'Section', 'algorithm': 'Algorithm'}.get(kind, 'Figure') } {m.group(1)}",
                "kind": kind, "num": _num_of(m.group(1)), "seg": seg,
            })
        for m in _CITE_KEY_RE.finditer(text):
            keys = [k.strip() for k in m.group(1).split(",")]
            if len(keys) > 4 or any(" " in k for k in keys):
                continue
            if not any(re.search(r"[A-Za-z]{3}", k) for k in keys):
                continue
            for k in keys:
                inv.citations.append({"key": k, "seg": seg, "bib": src.bib.get(k)})
        if _OBJECT_LINE.match(text) or re.search(r"\bwe (?:aim|address|ask|seek)\b", text, re.I):
            inv.objectives.append({"text": one_line(text), "seg": seg})
        if _LIMIT_CUES.search(text) and len(text) > 40:
            inv.limits.append({"text": one_line(text), "seg": seg})
        has_number = bool(re.search(r"\d", text))
        if (_CLAIM_VERBS.search(text) or _YEAR_RE.search(text)
                or (_RESULT_CUES.search(text) and has_number)
                or (has_number and re.search(r"\b(tabl|fig)", text, re.I))):
            inv.claims.append({"text": one_line(text), "seg": seg,
                               "score": _claim_score(text)})
    # de-dup refs by (label, locator)
    seen = set()
    uniq = []
    for r in inv.refs:
        k = (r["label"], id(r["seg"]))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    inv.refs = uniq
    inv.captions = _dedupe_captions(inv.captions, inv.notes)
    _bind_tables(inv)
    inv.claims.sort(key=lambda c: -c["score"])
    if not inv.captions:
        inv.notes.append("no numbered figure/table captions located")
    for kind in ("figure", "table"):
        if inv.max_kind(kind) == 0:
            inv.notes.append(f"source declares no {kind}")
    step_enrich(inv, src)
    return inv


# --------------------------------------------------------------------------
# Rigour triples: every evidence entry gets verbatim + line + verify command
# --------------------------------------------------------------------------

TRIAL_LEN = 60


def _triplets(entry: dict, seg, src, item: str, verbatim: str) -> dict:
    """Attach {verbatim, line, page, locator, segment, verify_cmd} to an entry."""
    entry["verbatim"] = one_line(verbatim)
    entry["line"] = seg.get("line") if seg is not None else None
    entry["page"] = seg.get("page") if seg is not None else None
    entry["segment_id"] = seg.get("id") if seg is not None else None
    entry["locator"] = src.locator(seg) if seg is not None else ""
    entry["verify_cmd"] = (f"python3 scripts/rigor.py --case <this case.json> "
                           f"--item {item}")
    return entry


def step_enrich(inv: Inventory, src) -> Inventory:
    """Give every number / caption / citation / claim / limit a rigour triple.

    The triple is *(verbatim fragment, line, verify command)* - enough for a
    reviewer to re-prove the item without trusting this ledger.
    """
    for n in inv.numbers:
        value = norm_number(n["raw"].split()[0] if n["raw"].split() else n["value"])
        _triplets(n, n["seg"], src, f"number:{value}:{n['unit_norm']}", n["raw"])
    for c in inv.captions:
        _triplets(c, c["seg"], src, f"{c['kind']}:{c['num']}", c["text"])
    for c in inv.citations:
        _triplets(c, c["seg"], src, f"citation:{c['key']}", c["key"])
    for t in inv.claims:
        _triplets(t, t["seg"], src, "claim:" + one_line(t["text"])[:TRIAL_LEN], t["text"])
    for t in inv.limits:
        _triplets(t, t["seg"], src, "limit:" + one_line(t["text"])[:TRIAL_LEN], t["text"])
    return inv


def triples(inv: Inventory) -> list[dict]:
    """Flat list of every rigour triple, for reports and the auditor."""
    out = []
    for kind, entries in (("number", inv.numbers), ("caption", inv.captions),
                          ("citation", inv.citations), ("claim", inv.claims),
                          ("limit", inv.limits)):
        for e in entries:
            out.append({"entry": kind, "label": (e.get("label") or e.get("key")
                                                 or e.get("raw") or e.get("value") or ""),
                        "verbatim": e.get("verbatim", ""), "line": e.get("line"),
                        "page": e.get("page"), "locator": e.get("locator", ""),
                        "segment_id": e.get("segment_id"),
                        "verify_cmd": e.get("verify_cmd", "")})
    return out


def _collect_tables(src, inv: Inventory):
    """Group consecutive table-row segments into tables (header heuristics)."""
    run: list[dict] = []
    label = None

    def flush():
        nonlocal run, label
        if not run:
            return
        rows = [r["_cells"] for r in run]
        header, body = [], rows
        if len(rows) >= 2 and _looks_header(rows[0], rows[1]):
            header, body = rows[0], rows[1:]
        if _informative(header, body):
            inv.tables.append({"label": label, "header": header, "rows": body,
                               "seg": run[0]})
        run, label = [], None

    for seg in src.segments:
        if seg["kind"] == "table-row":
            cells = [c.strip() for c in seg["text"].split("|") if c.strip()]
            item = dict(seg)
            item["_cells"] = cells
            if label is None:
                label = seg.get("label")
            elif seg.get("label") and seg.get("label") != label:
                flush()
                label = seg.get("label")
            run.append(item)
        else:
            flush()
    flush()
    if inv.tables:
        inv.notes.append(f"{len(inv.tables)} table(s) reconstructed from source rows")


_CAP_PROPER = re.compile(r"^(Figure|Fig\.?|Table|Tab\.?|Equation|Eq\.?)\s*\d+\s*[.:\u2014-]", re.I)


def _dedupe_captions(captions: list[dict], notes: list[str]) -> list[dict]:
    """One caption per label; prefer the one that really reads like a caption."""
    best: dict[str, dict] = {}
    for c in captions:
        key = _ref_key(c["label"])
        cur = best.get(key)
        if cur is None:
            best[key] = c
            continue
        cur_ok = bool(_CAP_PROPER.match(cur["text"]))
        new_ok = bool(_CAP_PROPER.match(c["text"]))
        if new_ok and not cur_ok:
            notes.append(f"{c['label']}: preferred the punctuated caption over a body "
                         f"sentence that only looked like one")
            best[key] = c
        elif new_ok == cur_ok and len(c["text"]) > len(cur["text"]):
            best[key] = c
    order = {"figure": 0, "table": 1, "equation": 2}
    return sorted(best.values(),
                  key=lambda c: (order.get(c["kind"], 9), c["num"]))


def _informative(header: list[str], body: list[list[str]]) -> bool:
    """Reject figure-label rows masquerading as tables."""
    if len(body) < 2:
        return False
    ncols = max(len(r) for r in body)
    if ncols < 2:
        return False
    numeric = 0
    for row in body:
        for cell in row:
            if re.fullmatch(r"\s*[-+−]?\d+(?:[.,]\d+)?\s*[%\u00b0]?\w{0,4}\s*", cell):
                numeric += 1
    return numeric >= 2 or len(body) >= 3


def _bind_tables(inv: Inventory):
    """Attach caption labels to tables that arrived without one (PDF path)."""
    caps = [c for c in inv.captions if c["kind"] == "table"]
    unlabeled = [t for t in inv.tables if not t["label"]]
    for cap in caps:
        match = [t for t in inv.tables if t["label"] == cap["label"]]
        if match:
            continue
        if not unlabeled:
            break
        page = cap["seg"].get("page")
        pool = sorted(unlabeled, key=lambda t: (
            abs((t["seg"].get("page") or 0) - (page or 0)),
            -len(t["rows"])))
        pick = pool[0]
        pick["label"] = cap["label"]
        unlabeled.remove(pick)
        inv.notes.append(f"{cap['label']} bound to a table recovered on page "
                         f"{pick['seg'].get('page')}")


def _looks_header(first: list[str], second: list[str]) -> bool:
    if len(first) != len(second):
        return False
    def numeric(cell: str) -> bool:
        return bool(re.fullmatch(r"\s*[-+−]?\d+(?:[.,]\d+)?\s*[%\u00b0]?[A-Za-z]*\s*", cell))
    first_num = sum(1 for c in first if numeric(c))
    second_num = sum(1 for c in second if numeric(c))
    return first_num == 0 and second_num >= 1


def _claim_score(text: str) -> float:
    s = 0.0
    if _CLAIM_VERBS.search(text):
        s += 2.0
    if re.search(r"\d", text):
        s += 1.5
    if re.search(r"\b(we|our)\b", text, re.I):
        s += 1.0
    if re.search(r"\b(improv|reduc|outperform|achiev|reach|increase|decrease)\w*", text, re.I):
        s += 1.5
    if re.search(r"\b(reduc|cut|lower|decreas)\w*\b.{0,40}\b(by|to)\b\s*\d", text, re.I):
        s += 2.0          # a quantified outcome is the strongest result signal
    if 40 <= len(text) <= 320:
        s += 1.0
    if len(text) > 600:
        s -= 1.0
    return round(s, 2)


def _scan_numbers(text: str, seg, inv: Inventory):
    claimed: set[str] = set()

    def add(raw_num: str, unit: str, raw: str):
        key = (norm_number(raw_num), norm_unit(unit))
        if key in claimed:
            return
        claimed.add(key)
        inv.numbers.append({
            "value": key[0], "raw": raw.strip(), "unit": unit,
            "unit_norm": key[1], "seg": seg,
        })

    for m in _PCT_RE.finditer(text):
        add(m.group("num"), m.group("unit"), m.group(0))
    for m in _METRIC_RE.finditer(text):
        metric = m.group("metric").strip()
        if norm_key(metric) in ("n", "p") and len(text) > 40:
            pass  # keep: "n = 12" is still evidence
        add(m.group("num"), metric, m.group(0))
    for m in _METRIC_TRAIL_RE.finditer(text):
        add(m.group("num"), m.group("metric"), m.group(0))
    for m in _NUM_RE.finditer(text):
        num = m.group("num")
        unit = m.group("unit")
        if unit is None and len(_clean_num(num).replace(".", "")) <= 1:
            continue  # bare single digit ("3 stages") is not evidence by itself
        add(num, unit or "", m.group(0))


# ------------------------------------------------------------------ verifying

def verify_value(inv: Inventory, raw: str, unit: str | None = None) -> dict:
    """Can this exact number (and unit) be found in the source?"""
    value = norm_number(raw)
    u = norm_unit(unit)
    units = inv.number_units(value)
    ok = inv.has_number(raw, unit)
    return {
        "ok": ok,
        "value": value,
        "unit": u,
        "unit_ok": (not u) or ok,
        "known_units": sorted(x for x in units if x),
        "reason": "" if ok else (
            f"number {raw}{(' ' + unit) if unit else ''} not found in source "
            f"(known values with this magnitude: {sorted(units) or 'none'})"
        ),
    }


def verify_locator(inv: Inventory, label: str) -> dict:
    """Does the referenced figure/table/equation exist in the source?"""
    kind = _kind_of(label)
    num = _num_of(label)
    cap = inv.caption_for(label)
    exists = inv.has_ref(label) or cap is not None
    return {
        "ok": exists,
        "label": label,
        "kind": kind,
        "num": num,
        "caption": cap["text"] if cap else None,
        "source_max": inv.max_kind(kind),
        "reason": "" if exists else (
            f"{label} is not present in the source "
            f"(highest {kind} number found: {inv.max_kind(kind) or 'none'})"
        ),
    }


def numbers_in(text: str) -> list[tuple[str, str]]:
    """Yield (raw_number, unit) pairs from arbitrary slide text."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def push(n: str, u: str):
        k = (norm_number(n), norm_unit(u))
        if k in seen:
            return
        seen.add(k)
        out.append((n, u))

    for m in _METRIC_RE.finditer(text):
        push(m.group("num"), m.group("metric").strip())
    for m in _METRIC_TRAIL_RE.finditer(text):
        push(m.group("num"), m.group("metric"))
    for m in _PCT_RE.finditer(text):
        push(m.group("num"), m.group("unit"))
    for m in _NUM_RE.finditer(text):
        num, unit = m.group("num"), m.group("unit") or ""
        if unit or "." in num or len(_clean_num(num)) >= 2:
            push(num, unit)
    return out


def refs_in(text: str) -> list[str]:
    labels = []
    for m in _REF_RE.finditer(text):
        kind = _kind_of(m.group(0).split()[0])
        if kind == "other":
            if m.group(0)[0] in "图表":
                kind = "figure" if m.group(0)[0] == "图" else "table"
            else:
                continue
        name = {"figure": "Figure", "table": "Table", "equation": "Equation",
                "section": "Section", "algorithm": "Algorithm"}.get(kind, "Figure")
        labels.append(f"{name} {m.group(1)}")
    return labels
