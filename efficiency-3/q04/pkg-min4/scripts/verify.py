#!/usr/bin/env python3
"""verify.py — independent self-check of a finished run.
    python3 scripts/verify.py --out /app/output
Re-validates the entities, arrow grammar, direction (geometry), traceability, legend coverage
and "no invented data" rules on spec.json/result.json and writes verify-report.json.
Exit 0 = PASS, 2 = FAIL."""
import argparse, io, json, os
from pathway import CMP, R, TYP, WID, geometry_checks, layout


def checks(spec, lay):
    C = []
    def c(cid, okk, det, lvl="error"):
        C.append({"id": cid, "ok": bool(okk), "level": lvl, "detail": det})
    ents, edges = spec["entities"], spec["edges"]
    c("entities.unique", len({e["id"] for e in ents}) == len(ents), "entity ids unique")
    c("entities.typed", all(e["type"] in TYP and e["label"] for e in ents), "every entity typed/labelled")
    c("trace.entities", all(e["evidence"] for e in ents), "every entity has a source locator")
    c("trace.edges", all(e["evidence"] for e in edges), "every edge has a source locator")
    sig = {}
    for t, r in R.items():
        sig.setdefault((r["arrow"], r["line"]), []).append(t)
    c("semantics.distinct", all(len(x) == 1 or all(R[t]["arrow"] == "none" for t in x)
                                for x in sig.values()),
      "one drawn signature per interaction type (the undirected types share the no-head dashed one "
      "by design; the legend says so)")
    c("semantics.matches", all(e["arrow"] == R[e["type"]]["arrow"] and e["line"] == R[e["type"]]["line"]
                               for e in edges), "arrow geometry equals the grammar")
    box = lay["box"]
    back = [(e["source"], e["target"]) for e in edges if not e.get("feedback") and e["source"] in box
            and e["target"] in box and box[e["target"]][0] <= box[e["source"]][0] + 1]
    c("direction.forward", not back, "non-feedback edges point rightwards", "warning")
    drawn = {(e["source"], e["target"], e["type"]) for e in edges}
    c("honesty.negated", not [x for x in spec["excluded"]
                              if (x.get("source"), x.get("target"), x.get("type")) in drawn],
      "%d negated claim(s) recorded and not drawn" % len(spec["excluded"]))
    c("honesty.reasons", all(x.get("removed_because") for x in spec["excluded"]), "excluded edges state why")
    c("localisation.receptor", all(e["compartment"] == "plasma_membrane" for e in ents if e.get("role") == "receptor"),
      "transmembrane receptors on the membrane band")
    c("legend.coverage", {e["type"] for e in ents} <= set(TYP) and {e["type"] for e in edges} <= set(R),
      "legend covers every token drawn")
    c("data.sourced", all(not e.get("data") or e.get("data_source") for e in ents), "painted values have a source")
    err = [x["id"] for x in C if not x["ok"] and x["level"] == "error"]
    warn = [x["id"] for x in C if not x["ok"] and x["level"] == "warning"]
    return {"ok": not err, "n_checks": len(C), "n_errors": len(err), "n_warnings": len(warn),
            "errors": err, "warnings": warn, "checks": C}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args(argv)
    spec = json.load(open(os.path.join(a.out, "spec.json"), encoding="utf-8"))
    res = json.load(open(os.path.join(a.out, "result.json"), encoding="utf-8")) if \
        os.path.exists(os.path.join(a.out, "result.json")) else {}
    box = {}
    lay = {"box": box}
    for e in spec["entities"]:
        x = (e.get("layout") or {}).get("x")
        if x is not None:
            box[e["id"]] = (x, 0, x + 1, 0)
    if not box:                      # fall back: geometry from the SVG node groups
        svg = open(os.path.join(a.out, "figure.svg"), encoding="utf-8").read() if \
            os.path.exists(os.path.join(a.out, "figure.svg")) else ""
        for m in re.finditer(r'<g id="(E\d+)"[^>]*>.*?<rect x="([-\d.]+)"', svg, re.S):
            box[m.group(1)] = (float(m.group(2)), 0, float(m.group(2)) + 1, 0)
    rep = checks(spec, lay)
    # independent geometry re-derivation: read figure.svg from disk, recompute the audit, and
    # compare it with the producer's fig.checks.json (a mismatch is itself a finding)
    svg_p = os.path.join(a.out, "figure.svg")
    geo_ind = None
    if os.path.exists(svg_p):
        svg_text = io.open(svg_p, encoding="utf-8").read()
        geo_ind = geometry_checks(spec, layout(spec), svg_text, a.out)
        shipped_p = os.path.join(a.out, "fig.checks.json")
        if os.path.exists(shipped_p):
            shipped = json.load(io.open(shipped_p, encoding="utf-8"))
            a_ = {c["check"]: c["passed"] for c in shipped.get("checks") or []}
            b_ = {c["check"]: c["passed"] for c in geo_ind["checks"]}
            diff = sorted(k for k in set(a_) | set(b_) if a_.get(k) != b_.get(k))
            geo_ind["matches_producer_report"] = not diff
            geo_ind["differing_checks"] = diff
        rep["geometry_recheck"] = geo_ind
        rep["checks"] = list(rep.get("checks") or []) + [
            {"id": "geometry.producer_report_matches", "ok": geo_ind.get("matches_producer_report", True),
             "level": "error",
             "detail": "independent recomputation agrees with fig.checks.json"
                       if geo_ind.get("matches_producer_report", True)
                       else "differs on %s" % geo_ind.get("differing_checks")}]
        if not geo_ind.get("matches_producer_report", True):
            rep["errors"] = list(rep.get("errors") or []) + ["geometry.producer_report_matches"]
            rep["n_errors"] = len(rep["errors"])
            rep["ok"] = False
        rep["n_checks"] = len(rep["checks"])
    files = {f: os.path.getsize(os.path.join(a.out, f)) for f in
             ("figure.svg", "figure.png", "result.json", "check-report.json") if os.path.exists(os.path.join(a.out, f))}
    rep["files"] = files
    rep["result_status"] = res.get("status")
    json.dump(rep, open(os.path.join(a.out, "verify-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("verify: %d checks, %d errors, %d warnings -> %s" %
          (rep["n_checks"], rep["n_errors"], rep["n_warnings"], "PASS" if rep["ok"] else "FAIL"))
    for c in rep["checks"]:
        if not c["ok"]:
            print("  [%s] %s - %s" % (c["level"], c["id"], c["detail"]))
    print("files : %s" % ", ".join("%s=%dB" % kv for kv in files.items()))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    import sys, re
    sys.exit(main())
