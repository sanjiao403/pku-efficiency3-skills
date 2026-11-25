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


def _pack_rel(p) -> str:
    """Package-relative path when possible, else the basename (never a machine path)."""
    if not p:
        return ""
    try:
        root = os.path.dirname(HERE)
        rel = os.path.relpath(os.path.abspath(str(p)), root)
        if not rel.startswith(".."):
            return rel.replace("\\", "/")
    except (ValueError, OSError):
        pass
    return os.path.basename(str(p))


def report_for(case_path: str) -> dict:
    """The machine-readable rigor ledger for one case (first-class artefact)."""
    case = {}
    if case_path and os.path.isfile(case_path):
        import json
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
    src = material(case_path, case)
    inv = I.build(src)
    items = ledger_items(inv)
    rows = [check(src, inv, it) for it in items]
    return {
        "case": _pack_rel(case_path),
        "case_id": case.get("case_id") or os.path.splitext(os.path.basename(case_path))[0],
        "material": [_pack_rel(f["path"]) for f in src.files],
        "rule": "every number / caption label / citation / claim / limit is re-extracted "
                "from the material and looked up verbatim; no plan state is read",
        "found": sum(1 for r in rows if r["found"]),
        "total": len(rows),
        "items": [{"item": r["item"], "kind": r["kind"], "value": truncate(r["value"], 60),
                   "found": r["found"], "match": r["match"],
                   "locator": _pack_rel((r["evidence"] or {}).get("locator") or ""),
                   "line": (r["evidence"] or {}).get("line"), "reason": r["reason"]}
                  for r in rows],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="re-prove one evidence item against the material")
    ap.add_argument("--case", action="append", default=None,
                    help="case.json; repeatable (each case gets its own ledger)")
    ap.add_argument("--item", action="append", default=[],
                    help="kind:value[:unit]; repeatable")
    ap.add_argument("--all", action="store_true", help="walk the whole ledger")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", default=None,
                    help="write the machine-readable ledger here (aggregates repeated --case)")
    args = ap.parse_args(argv)

    cases = args.case or ["/input/case.json"]
    if args.report and (args.case or args.all) and not args.item:
        reps, bad = [], 0
        for cp in cases:
            try:
                rep = report_for(cp)
            except Exception as exc:
                print(f"ERROR cannot read material for {cp}: {exc}")
                return 2
            if not rep["material"]:
                print(f"ERROR no readable material for {cp}")
                return 2
            bad += rep["total"] - rep["found"]
            reps.append(rep)
            print(f"{rep['found']}/{rep['total']} items re-proved from the material "
                  f"({os.path.basename(cp)})")
        doc = {"what": "evidence re-proof ledger, regenerated from the material",
               "generated_by": "scripts/rigor.py --all --report reports/rigor-report.json",
               "cases": reps,
               "summary": {"cases": len(reps),
                           "items": sum(r["total"] for r in reps),
                           "found": sum(r["found"] for r in reps),
                           "missing": bad}}
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8", newline="\n") as fh:
            import json
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"wrote {args.report} "
              f"({doc['summary']['found']}/{doc['summary']['items']} items across "
              f"{doc['summary']['cases']} case(s))")
        return 1 if bad else 0

    case_path = cases[0]
    case = {}
    if case_path and os.path.isfile(case_path):
        import json
        with open(case_path, "r", encoding="utf-8-sig") as fh:
            case = json.load(fh)
    try:
        src = material(case_path, case)
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
        print(json.dumps({"case": case_path, "items": rows,
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
