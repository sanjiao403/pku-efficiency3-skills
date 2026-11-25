#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_ir.py -- 只判**中间表示**（figure.ir.json）是否符合 references/ir_schema.md。

不读 SVG/材料/result.json（跨产物一致性属 check_consistency.py）。额外做"契约与实现同源"：
IR 用到的每个 kind 都必须能在 references/symbol_library.md 里找到，漏写即硬失败。

    python3 scripts/validate_ir.py --ir <ir.json> [--library <symbol_library.md>]
退出码 0 = 合规 / 1 = 有错误。
"""
from __future__ import annotations

import argparse, json, os, sys

SCHEMA = "apparatus/ir/1"
FIGURE_TYPES = ("apparatus", "route")
KINDS = ("unit.vessel", "unit.instrument", "unit.utility", "unit.sensor", "unit",
         "step.main", "step.parallel", "step.loop", "step.terminal", "phase")
REL_KINDS = ("material", "energy", "signal", "loop", "dependency")
CERTAINTY = ("quoted", "inferred")
HERE = os.path.dirname(os.path.abspath(__file__))


def run(ir_path, library=None):
    """返回 {ok, errors[], warnings[], items[], stats{}}。"""
    errs, warns, items = [], [], []

    def ck(name, ok, detail, hard=True):
        items.append({"check": name, "ok": bool(ok), "hard": bool(hard), "detail": str(detail)[:220]})
        if hard and not ok:
            errs.append(name)

    try:
        ir = json.load(open(ir_path, encoding="utf-8"))
    except Exception as exc:                                      # noqa: BLE001
        return {"ok": False, "errors": ["ir.read"], "warnings": [],
                "items": [{"check": "ir.read", "ok": False, "hard": True, "detail": str(exc)[:200]}],
                "stats": {}}
    if not isinstance(ir, dict):
        return {"ok": False, "errors": ["ir.object"], "warnings": [],
                "items": [{"check": "ir.object", "ok": False, "hard": True,
                           "detail": "IR root must be a JSON object"}], "stats": {}}

    ck("ir.schema", ir.get("schema") == SCHEMA, "schema=%r" % ir.get("schema"))
    ck("ir.figure_type", ir.get("figure_type") in FIGURE_TYPES, "figure_type=%r" % ir.get("figure_type"))
    if not ir.get("title"):
        warns.append("title missing")
    cm = ir.get("canvas_mm") or []
    ck("ir.canvas_mm", len(cm) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in cm),
       "canvas_mm=%s" % cm)

    els = ir.get("elements") or []
    rels = ir.get("relations") or []
    ck("ir.elements_present", bool(els), "%d elements" % len(els))
    ids, seen = set(), set()
    for el in els:
        eid = el.get("id")
        if not eid:
            ck("ir.element.id", False, "element without id: %r" % el.get("label"))
            continue
        ck("ir.element.id_unique", eid not in seen, "duplicate id")
        seen.add(eid)
        ids.add(eid)
        ck("ir.element.kind", el.get("kind") in KINDS, "kind=%r" % el.get("kind"))
        ck("ir.element.certainty", el.get("certainty") in CERTAINTY,
           "certainty=%r" % el.get("certainty"))
        src = el.get("source") or {}
        ck("ir.element.source", bool(src.get("locator")), "locator=%r" % src.get("locator"))
        ck("ir.element.quote", bool((src.get("quote") or "").strip()),
           "quote=%r" % (src.get("quote") or "")[:60])
    for rl in rels:
        rid = rl.get("id")
        ck("ir.relation.endpoints", rl.get("from") in ids and rl.get("to") in ids,
           "%s -> %s" % (rl.get("from"), rl.get("to")))
        ck("ir.relation.kind", rl.get("kind") in REL_KINDS, "kind=%r" % rl.get("kind"))
        ck("ir.relation.quote", bool(((rl.get("source") or {}).get("quote") or "").strip()),
           "quote=%r" % ((rl.get("source") or {}).get("quote") or "")[:60])

    idx = ir.get("extraction_index") or []
    ck("ir.index.present", bool(idx), "%d index items" % len(idx))
    mapped = 0
    for it in idx:
        m = it.get("mention")
        ck("ir.index.quote", bool((it.get("quote") or "").strip()), "mention=%r" % m)
        if it.get("status") == "omitted":
            ck("ir.index.omit_reason", bool(it.get("reason")),
               "omitted without reason: %r" % m)
        else:
            ck("ir.index.mapped", it.get("mapped_id") in ids,
               "mapped_id=%r not in elements" % it.get("mapped_id"))
            mapped += 1
    for n in ir.get("numbers") or []:
        ck("ir.number.source", bool((n.get("source") or {}).get("locator")),
           "label=%r" % n.get("label")[:40])

    # 契约与实现同源：symbol_library.md 必须列出 IR 用到的每个 kind
    lib = library or os.path.join(HERE, os.pardir, "references", "symbol_library.md")
    used = sorted({el.get("kind") for el in els if el.get("kind")} |
                  {r.get("kind") for r in rels if r.get("kind")})
    try:
        doc = open(lib, encoding="utf-8").read()
        missing = [k for k in used if k not in doc]
        ck("library.kind_documented", not missing,
           "undocumented kinds=%s (doc=%s)" % (missing, os.path.basename(lib)))
    except Exception as exc:                                      # noqa: BLE001
        ck("library.kind_documented", False, "library doc unreadable: %s" % exc)

    return {"ok": not errs, "errors": errs, "warnings": warns, "items": items,
            "stats": {"elements": len(els), "relations": len(rels), "index": len(idx),
                      "index_mapped": mapped, "index_omitted": len(idx) - mapped}}


def main(a=None):
    ap = argparse.ArgumentParser(description="validate the intermediate representation only")
    ap.add_argument("--ir", required=True)
    ap.add_argument("--library", default="")
    ap.add_argument("--report", default="")
    x = ap.parse_args(a)
    rep = run(x.ir, x.library or None)
    for i in rep["items"]:
        if not i["ok"]:
            print("[%s] %-34s %s" % ("FAIL" if i["hard"] else "warn", i["check"], i["detail"]))
    print("[validate_ir] ok=%s errors=%d warnings=%d stats=%s"
          % (rep["ok"], len(rep["errors"]), len(rep["warnings"]), rep["stats"]))
    if x.report:
        json.dump(rep, open(x.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
