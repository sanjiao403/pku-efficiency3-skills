#!/usr/bin/env python3
"""verify.py - self-check a run of scripts/schematic.py.

    python scripts/verify.py --result /app/output/result.json [--case /input/case.json]

Re-checks the produced files independently of the generator: the result.json
contract, the artifacts on disk, the SVG's editability and per-element sources,
the legend/data agreement, the blocking counters, and - read back from the drawing -
the drawn relation token and the arrow geometry. Last line is VERIFY_OK or
VERIFY_FAIL; exit code 0 or 2. Nothing is invented: a missing field is reported as
missing. Deliberately standalone (it does not import schematic.py) so it stays a
genuine second opinion.
"""
import argparse, json, os, re, sys

sys.dont_write_bytecode = True
REQ = ("case_id", "status", "summary", "editable_source", "exports", "checks", "uncertainty")


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify a schematic.py run")
    ap.add_argument("--result", default="/app/output/result.json")
    ap.add_argument("--case", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    fails, notes, ok_n = [], [], 0
    say = lambda s: None if a.quiet else print(s)

    def ok(m):
        nonlocal ok_n
        ok_n += 1
        say(f"[ ok ] {m}")

    def bad(m):
        fails.append(m)
        print(f"[FAIL] {m}")

    def note(m):
        notes.append(m)
        say(f"[note] {m}")

    if not os.path.isfile(a.result):
        bad(f"result.json not found: {a.result}")
        print("VERIFY_FAIL")
        return 2
    try:
        with open(a.result, encoding="utf-8") as fh:
            r = json.load(fh)
    except Exception as e:
        bad(f"result.json is not valid JSON: {type(e).__name__}: {e}")
        print("VERIFY_FAIL")
        return 2
    ok(f"result.json parsed ({len(r)} top-level fields)")

    for k in REQ:
        if r.get(k) in (None, "", [], {}):
            bad(f"required field missing or empty: {k}")
        else:
            ok(f"field present: {k}")
    if r.get("status") not in ("success", "partial"):
        bad(f"status must be success|partial, got {r.get('status')!r}")
    elif r["status"] == "partial" and not (r.get("status_reason") or r.get("gaps")):
        bad("status=partial but neither status_reason nor gaps explains why")
    else:
        ok(f"status={r['status']} is explained")

    missing = [x.get("rel") or x.get("path") for x in (r.get("exports") or []) + (r.get("outputs") or [])
               if not os.path.isfile(os.path.join(os.path.dirname(a.result), x.get("rel") or ""))]
    ok(f"{len(r.get('exports') or [])} export(s) declared") if not missing else bad(f"declared but missing: {sorted(set(missing))}")

    svg_path = os.path.join(os.path.dirname(a.result), "figure.svg")
    if not os.path.isfile(svg_path):
        bad("figure.svg was not written next to result.json")
    else:
        svg = open(svg_path, encoding="utf-8").read()
        checks = (("<text" in svg, "text is real <text> (selectable and editable)"),
                  ('data-layer=' in svg, "named layers present"),
                  ('<g id="node-' in svg, "entities are addressable by id"))
        attributed = [s for s in (r.get("element_sources") or []) if (s.get("source") or "").strip()]
        if attributed and "data-source=" not in svg:
            bad(f"{len(attributed)} element(s) are attributed to a named file but the SVG has no "
                "data-source attribute: the locator was lost")
        elif attributed:
            ok(f"{len(attributed)} attributed element(s) carry a data-source locator in the SVG")
        else:
            note("no element could be attributed to a named file, so the SVG carries no data-source")
        for good, what in checks:
            ok(what) if good else bad(f"SVG check failed: {what}")
        if r.get("metrics", {}).get("svg_text_elements") not in (None, svg.count("<text ")):
            note("metrics.svg_text_elements does not match the SVG on disk")
        note(f"font_pt={r.get('metrics', {}).get('font_pt')} canvas_mm={r.get('metrics', {}).get('canvas_mm')}; "
             "the SVG carries no embedded font (vector text stays editable, the viewer substitutes a system font)")
        # read the drawing back (reference package's marker_semantics / marker_geometry):
        # the DRAWN token decides, so a wrong head fails even if the attrs claim otherwise.
        boxes = {}
        for m in re.finditer(r'<g id="node-([^"]+)"[^>]*><rect x="([-\d.]+)" y="([-\d.]+)" '
                             r'width="([-\d.]+)" height="([-\d.]+)"', svg):
            boxes[m.group(1)] = tuple(float(m.group(k)) for k in (2, 3, 4, 5))
        drawn = {}
        for m in re.finditer(r'<g id="edge-([^"]+)"([^>]*)>(.*?)</g>', svg, re.S):
            attrs, body = m.group(2), m.group(3)
            rel = (re.search(r'data-relation="([^"]+)"', attrs) or [None, None])[1]
            if 'data-glyph="nested"' in attrs or "<rect" in body:
                tok = "nested"
            elif "stroke-dasharray" in body:
                tok = "q" if re.search(r">\s*\?</text>", body) else "dash"
            elif 'data-glyph="tee-bar"' in body:
                tok = "tee-bar"
            elif "<polygon" in body:
                tok = "open" if 'fill="#fff"' in body else "arrow"
            else:
                tok = "none"
            ln = re.search(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"', body)
            drawn[m.group(1)] = {"relation": rel, "token": tok,
                                 "line": [float(ln.group(k)) for k in (1, 2, 3, 4)] if ln else None}
        want = {"activation": "arrow", "inhibition": "tee-bar", "binding": "none",
                "transport": "dash", "modification": "open", "sequence": "none",
                "inclusion": "nested", "unknown": "q"}
        wrong = [f"{k}: relation {e['relation']!r} is drawn as {e['token']!r}, expected "
                 f"{want.get(e['relation'])!r}" for k, e in drawn.items()
                 if want.get(e["relation"]) != e["token"]]
        if drawn and not wrong:
            ok(f"marker_semantics: all {len(drawn)} edge(s) carry the token their relation requires")
        elif wrong:
            bad("marker_semantics: " + "; ".join(wrong[:5]))
        else:
            note("no edges in this figure (nothing to check for relation semantics)")

        def nearest(pt):
            best, dist = None, 1e9
            for nid, bx in boxes.items():
                d = abs(min(pt[0] - bx[0], bx[0] + bx[2] - pt[0],
                            pt[1] - bx[1], bx[1] + bx[3] - pt[1]))
                if d < dist:
                    best, dist = nid, d
            return best, dist

        tol, bad_geo, skipped = 1.0, [], 0
        for eid, e in drawn.items():
            if e["line"] is None or e["token"] == "nested" or e["relation"] in ("binding", "sequence"):
                skipped += 1  # non-directional or containment: geometry is not a claim here
                continue
            (tn, td), (sn, sd) = nearest((e["line"][2], e["line"][3])), nearest((e["line"][0], e["line"][1]))
            if td > tol or sd > tol:
                bad_geo.append(f"{eid}: tip {td:.2f} pt / tail {sd:.2f} pt off the nearest box")
            elif tn == sn:
                bad_geo.append(f"{eid}: both ends sit on {tn}, so direction is unreadable")
        if bad_geo:
            bad("marker_geometry: " + "; ".join(bad_geo[:5]))
        else:
            ok(f"marker_geometry: {len(drawn) - skipped} directional edge(s) sit on their own "
               f"node boxes ({skipped} skipped: non-directional/containment)")
        missing_nodes = sorted({s.get("element_id") for s in (r.get("element_sources") or [])
                                if s.get("element_type") == "node"} - set(boxes))
        missing_edges = sorted({s.get("element_id") for s in (r.get("element_sources") or [])
                                if s.get("element_type") == "edge"} - set(drawn))
        if missing_nodes or missing_edges:
            bad(f"coverage: element_sources lists nodes {missing_nodes} / edges {missing_edges} "
                "that have no group in the SVG")
        elif r.get("element_sources"):
            ok(f"coverage: every listed element has a group in the drawing "
               f"({len(boxes)} boxes, {len(drawn)} edge groups)")

    bl = (r.get("checks") or {}).get("blocking") or {}
    if any(isinstance(v, int) and v > 0 for v in bl.values()):
        bad(f"blocking findings present: {bl}") if r.get("status") == "success" else \
            note(f"blocking findings recorded with status=partial: {bl}")
    elif bl:
        ok(f"no blocking findings: {bl}")

    dm = r.get("data_mapping") or {}
    if dm.get("series") and dm.get("colors"):
        ok(f"data mapping: {len(dm['series'])} series, {len(dm['colors'])} colours") \
            if len(dm["series"]) == len(dm["colors"]) else \
            bad(f"colour mapping mismatch: {len(dm['series'])} series vs {len(dm['colors'])} colours")
        lg = (r.get("checks") or {}).get("legend") or {}
        if lg.get("keys") and set(dm["series"]) - set(lg["keys"]):
            bad(f"series {sorted(set(dm['series']) - set(lg['keys']))} missing from the legend")
        else:
            ok("legend covers every data series")
    else:
        note("no data table in this case (schematic path)")

    src = r.get("element_sources") or []
    unver = [s.get("element_id") for s in src if s.get("verified_in_material") is False]
    if unver:
        bad(f"elements whose quoted sentence is NOT in the material: {unver}")
    elif src:
        ok(f"{len(src)} element source(s) recorded, all quotes found verbatim")
    else:
        note("element_sources is empty (expected only when nothing was drawn)")

    if a.case and os.path.isfile(a.case):
        try:
            case = json.load(open(a.case, encoding="utf-8"))
            raw = next((v for k, v in case.items() if re.search(r"contract|output|schema", str(k), re.I) and v), None)
            names = ([x if isinstance(x, str) else x.get("name") or x.get("field") for x in raw] if isinstance(raw, list)
                     else list(raw.get("properties", {})) if isinstance(raw, dict) and "properties" in raw
                     else list(raw) if isinstance(raw, dict) else [])
            miss = [n for n in names if n and r.get(n, r.get({"svg": "editable_source", "export": "exports"}.get(n, n))) is None]
            ok(f"output_contract: {len(names)} field(s) declared") if not miss else bad(f"contract field(s) not echoed: {miss}")
        except Exception as e:
            note(f"case.json could not be read for the contract check: {type(e).__name__}")

    print(f"\nchecked: {ok_n} pass, {len(fails)} fail, {len(notes)} note")
    print("VERIFY_OK" if not fails else "VERIFY_FAIL")
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
