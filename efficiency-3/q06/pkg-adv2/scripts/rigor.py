"""rigor.py - re-prove a single evidence item against the material, from a shell.

Every evidence entry in ``inventory.json`` / ``result.json`` carries a
``verify_cmd`` of the form

    python3 scripts/rigor.py --case <case.json> --item number:3.7:degC

so a reviewer (or an auditor agent) can re-run one claim without reading any of
the plan's intermediate state.  ``--all`` walks the whole ledger of a case and
prints one line per item.

Exit codes: 0 = every requested item was found verbatim (or normalised-verbatim),
1 = at least one item was not found, 2 = the material could not be read.

This is deliberately independent of ``plan_validate.py``: it re-extracts the
material and searches it directly, so an error in the plan layer cannot hide an
error in the evidence layer.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import inventory as I
import papertext as P
from util import norm_key, one_line, quote_key, truncate

KINDS = ("number", "figure", "table", "equation", "quote", "citation", "claim", "limit")


def material(case_path: str, case: dict):
    base = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    decl = []
    for key in ("materials", "material", "sources", "inputs", "paper", "files"):
        v = case.get(key)
        decl += [v] if isinstance(v, str) else ([x for x in v if isinstance(x, str)]
                                                if isinstance(v, list) else [])
    paths = []
    for d in decl:
        p = d if os.path.isabs(d) else os.path.join(base, d)
        if os.path.exists(p):
            paths.append(p)
    if not paths:
        paths = [os.path.join(base, f) for f in sorted(os.listdir(base))
                 if os.path.splitext(f)[1].lower() in P.SUPPORTED
                 and os.path.abspath(os.path.join(base, f)) != os.path.abspath(case_path or "")] \
            if os.path.isdir(base) else []
    src = P.Source()
    for p in paths:
        part = P.ingest(p, exclude=(case_path,))
        src.segments.extend(part.segments)
        src.files.extend(part.files)
        src.notes.extend(part.notes)
        src.bib.update(part.bib)
    if (case.get("material_text") or "").strip():
        for i, line in enumerate([x for x in case["material_text"].split("\n") if x.strip()]):
            src.add(line, kind="para", source="material_text", line=i + 1)
    return src


def show(seg, src) -> dict:
    return {"locator": src.locator(seg), "line": seg.get("line"), "page": seg.get("page"),
            "segment": seg.get("id"), "verbatim": truncate(seg.get("text"), 220)}


def check(src, inv, item: str) -> dict:
    """item = '<kind>:<value>[:<unit>]' or '<kind>:<substring>'."""
    parts = item.split(":", 2)
    kind = parts[0].lower()
    value = parts[1] if len(parts) > 1 else ""
    unit = parts[2] if len(parts) > 2 else ""
    out = {"item": item, "kind": kind, "value": value, "unit": unit,
           "found": False, "match": None, "evidence": None, "reason": ""}
    if kind == "number":
        v = I.verify_value(inv, value, unit)
        out["found"] = v["ok"]
        if v["ok"]:
            for n in inv.numbers:
                if n["value"] == v["value"]:
                    out["evidence"] = show(n["seg"], src)
                    out["match"] = "verbatim"
                    break
        else:
            out["reason"] = v["reason"]
        return out
    if kind in ("figure", "table", "equation", "section"):
        label = f"{kind.title()} {value}" if value else kind
        v = I.verify_locator(inv, label)
        out["found"] = v["ok"]
        if v["ok"]:
            cap = v["caption"] or ""
            out["evidence"] = {"locator": _loc_of_label(inv, src, label), "line": None,
                               "page": None, "segment": None, "verbatim": truncate(cap, 220)}
            out["match"] = "caption" if cap else "reference"
        else:
            out["reason"] = v["reason"]
        return out
    if kind == "citation":
        for c in inv.citations:
            if norm_key(value) in norm_key(c["key"]):
                out["found"] = True
                out["match"] = "bib" if c.get("bib") else "in-text"
                out["evidence"] = show(c["seg"], src)
                break
        if not out["found"]:
            out["reason"] = f"citation key {value!r} not cited in the material"
        return out
    # quote / claim / limit: substring search over the located source text
    seg, loc, kind_match = src.quote_locator(value)
    if seg is None:
        out["reason"] = f"{kind} not found verbatim in the material: {value[:80]!r}"
        return out
    out["found"] = True
    out["match"] = kind_match
    out["evidence"] = show(seg, src)
    return out


def _loc_of_label(inv, src, label: str) -> str:
    cap = inv.caption_for(label)
    if cap is not None:
        return src.locator(cap["seg"])
    for r in inv.refs:
        if I._ref_key(r["label"]) == I._ref_key(label):
            return src.locator(r["seg"])
    return "not located"


def ledger_items(inv) -> list[str]:
    """Every evidence item in a case, as rigour items.

    The value/unit pair comes from the *normalised* ledger fields, not from the
    raw span: ``raw`` keeps the extracted glyphs (``"5%"``, ``"3.7 °C"``), which
    would make the item string re-parse into a different value than the one the
    ledger proved.
    """
    out = []
    for n in inv.numbers:
        out.append(f"number:{n['value']}:{n['unit']}" if n.get("unit")
                   else f"number:{n['value']}")
    for c in inv.captions:
        out.append(f"{c['kind']}:{c['num']}")
    for c in inv.citations:
        out.append(f"citation:{c['key']}")
    for t in inv.claims[:8]:
        out.append("claim:" + one_line(t["text"])[:60])
    for t in inv.limits[:6]:
        out.append("limit:" + one_line(t["text"])[:60])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="re-prove one evidence item against the material")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--item", action="append", default=[],
                    help="kind:value[:unit]; repeatable")
    ap.add_argument("--all", action="store_true", help="walk the whole ledger")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    case = {}
    if args.case and os.path.isfile(args.case):
        import json
        with open(args.case, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
    try:
        src = material(args.case, case)
    except Exception as exc:
        print(f"ERROR cannot read material: {exc}")
        return 2
    if not src.segments:
        print("ERROR no readable material for this case")
        return 2
    inv = I.build(src)
    items = list(args.item) or (ledger_items(inv) if args.all else [])
    if not items:
        print("ERROR nothing to check: pass --item or --all")
        return 2

    rows = [check(src, inv, it) for it in items]
    if args.json:
        import json
        print(json.dumps({"case": args.case, "items": rows,
                          "found": sum(1 for r in rows if r["found"]),
                          "total": len(rows)}, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            flag = "FOUND" if r["found"] else "MISSING"
            where = (r["evidence"] or {}).get("locator") or "-"
            print(f"{flag:>7} {r['kind']:<8} {truncate(r['value'], 46):<48} "
                  f"{where}{' [' + str(r['match']) + ']' if r['match'] else ''}")
            if not r["found"]:
                print(f"        {r['reason']}")
        print(f"{sum(1 for r in rows if r['found'])}/{len(rows)} items re-proved from the material")
    return 0 if all(r["found"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
