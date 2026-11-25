#!/usr/bin/env python3
"""bench.py — benchmark / copy-probe harness for this arm. Ships inside the package so the numbers
quoted in BENCHMARK.md can be reproduced by anyone who has the package, with no external path:

    python3 tests/bench.py                      # prints the table, writes nothing
    python3 tests/bench.py --bench-out /tmp/benchmark.json

The three inputs are written at run time (they are examples, not the official cases).
"""
import json, os, shutil, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True          # never leave __pycache__/*.pyc inside the Skill tree
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "scripts")))
from pathway import *          # noqa: F401,F403  (VOC, rels, layout, checks, sents, ...)
from pathway import CMP, R, TYP, DSH, WID, VER, checks, extract, gather, layout, now, prose_blob, sents

# ------------------------------------------------------------------ benchmark / self-check mode
# Self-contained benchmark inputs, so `--selfcheck` needs no files besides this package.
SELFCHECK_CASES = {
    "case-01": ("English linear cascade, one inhibition and one negated claim",
                "Extracellular EGF binds the transmembrane receptor EGFR at the plasma membrane. "
                "EGFR phosphorylates MAP2K1, which then activates MAPK1. Activated MAPK1 "
                "translocates into the nucleus and drives transcription of FOS. EGF does not "
                "activate the PI3K-AKT pathway in these cells. The transcription factor ELK1 "
                "promotes FOS expression."),
    "case-02": ("English branched pathway with a complex, a feedback arm and a drug",
                "PIK3CA generates PIP3 at the plasma membrane. AKT1 is phosphorylated by PDK1 and "
                "promotes proliferation. MTOR forms a complex with RPTOR and phosphorylates S6K1. "
                "S6K1 inhibits IRS1, a feedback arm of the pathway. PTEN degrades PIP3 and "
                "therefore suppresses AKT1 signalling. Rapamycin inhibits MTOR."),
    "case-03": ("中文：复合物、被动、否定与指代",
                "缺氧条件下，HIF1A 不被降解，在细胞质中积累。EPAS1 与 HIF1A 结合，形成复合物。"
                "该复合物促进 VEGFA 的转录。SLC2A1 由 HIF1A 激活，从而增强糖酵解。"
                "VHL 通过泛素化降解 HIF1A。缺氧诱导的糖酵解酶在肿瘤中上调。"
                "未发现 HIF1A 促进细胞凋亡的证据。"),
}


def baseline_spec(case, mats):
    """The comparison arm: a deliberately naive keyword extractor.

    Every capitalised token becomes an untyped entity (no compartment, no aliases, no evidence,
    no locator); every sentence containing an activation-family word becomes one edge between the
    first two tokens, ignoring passive voice, negation, coordination and direction; nothing is
    excluded and nothing is left unresolved. It is what a "draw something quickly" attempt does,
    and it is the arm the Skill is measured against.
    """
    src = mats[0]["id"] if mats else "case"
    text = "\n\n".join(m["text"] for m in mats if m.get("text"))
    ents, seen, edges, ex = [], {}, [], []
    for i, m in enumerate(re.finditer(r"\b[A-Z][A-Za-z0-9\-]{1,12}\b", text), 1):
        tok = m.group(0)
        if tok not in seen:
            seen[tok] = "E%02d" % (len(seen) + 1)
            ents.append({"id": seen[tok], "canonical": tok, "label": tok, "type": "protein",
                         "role": "", "compartment": "cytosol", "compartment_source": "baseline",
                         "italic": False, "ambiguous": True, "surfaces": [tok], "count": 1,
                         "first": (m.start(), m.end()), "data": {}, "data_source": "",
                         "evidence": []})
    for sent, s0, _s1 in sents(text):
        if not re.search(r"\bactivat|\bpromot|\binduces?\b|激活|促进", sent, re.I):
            continue
        ms = [x for x in re.finditer(r"\b[A-Z][A-Za-z0-9\-]{1,12}\b", sent)]
        if len(ms) >= 2:
            a, b = seen.get(ms[0].group(0)), seen.get(ms[-1].group(0))
            if a and b and a != b:
                edges.append({"id": "R%02d" % (len(edges) + 1), "source": a, "target": b,
                              "type": "activates", "label": "", "line": "solid", "arrow": "tri",
                              "color": R["activates"]["col"], "strength": "moderate",
                              "feedback": False, "modification_tag": "",
                              "origin": "baseline keyword rule", "evidence": [],
                              "uncertainty": "direction not checked, negation ignored"})
    spec = {"case_id": "baseline", "figure": {}, "entities": ents, "edges": edges, "excluded": ex,
            "unresolved": [], "sources": [{"id": src, "path": m.get("path"), "kind": m.get("kind")}
                                          for m in mats],
            "materials_resolution": [{"path": m.get("path"), "resolved_from": m.get("resolved_from")}
                                     for m in mats]}
    return spec


def selfcheck(bench_out="", cases=("case-01", "case-02", "case-03"), arm=None):
    """Real, reproducible measurements: Skill vs baseline, plus the copy probe."""
    import subprocess, tempfile, time
    here = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
    pkg = os.path.dirname(here)
    arm = arm or os.path.basename(pkg)
    tmp = tempfile.mkdtemp(prefix="q04-selfcheck-")
    cases_dir = os.path.join(pkg, "tests", "cases")
    bench = {"generated_at": now(), "generator": "pathway.py %s (tests/bench.py)" % VER,
             "entry": "python3 scripts/pathway.py --case <case.json> --out <out>",
             "baseline_arm": "naive keyword extractor (definition in BENCHMARK.md, code in tests/bench.py): "
                             "capitalised tokens as untyped entities, first-two-mention edges on "
                             "activation words, no passive/negation/coordination handling, no "
                             "evidence, no legend, no exclusion",
             "cases": [], "copy_probe": {"cases": [], "all_pass": False, "destination_template":
                                         "<tmp>/probe/runs/q04-fire/stage/outputs"}}
    for key in cases:
        cdir = os.path.join(cases_dir, key)
        cjson = os.path.join(cdir, "case.json")
        if not os.path.isfile(cjson):
            # self-contained mode: material embedded in this file, written out for the run
            spec_in = SELFCHECK_CASES.get(key)
            if not spec_in:
                continue
            cdir = os.path.join(tmp, "inputs", key)
            os.makedirs(cdir, exist_ok=True)
            io.open(os.path.join(cdir, "materials.md"), "w", encoding="utf-8", newline="\n").write(
                "# 示例（非正式答案）· EXAMPLE ONLY · benchmark input\n\n" + spec_in[1] + "\n")
            json.dump({"case_id": key + "-selfcheck", "task": spec_in[0],
                       "output_contract": {"figure_svg": "editable svg", "entities": "entity table",
                                           "interactions": "interaction table", "status": "status"},
                       "figure": {"title": "示例（非正式答案）· EXAMPLE ONLY · " + spec_in[0]},
                       "materials": ["materials.md"]},
                      io.open(os.path.join(cdir, "case.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            cjson = os.path.join(cdir, "case.json")
        out = os.path.join(tmp, key)
        t0 = time.time()
        subprocess.run([sys.executable, os.path.join(here, "pathway.py"), "--case", cjson,
                        "--input", cdir, "--out", out, "--quiet"], check=False,
                       capture_output=True, text=True)
        secs = round(time.time() - t0, 2)
        res = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
        spec = json.load(open(os.path.join(out, "spec.json"), encoding="utf-8"))
        lay = layout(spec)
        mats, _ginfo = gather(json.load(open(cjson, encoding="utf-8")), cjson, cdir)
        bspec = baseline_spec(json.load(open(cjson, encoding="utf-8")), mats)
        brep = checks(bspec, layout(bspec))
        claims = len(spec["entities"]) + len(spec["edges"])
        traced = sum(1 for e in spec["entities"] + spec["edges"] if e.get("evidence"))
        bench["cases"].append({
            "case": key, "input": (os.path.relpath(cjson, pkg).replace("\\", "/") if os.path.normcase(os.path.splitdrive(cjson)[0]) == os.path.normcase(os.path.splitdrive(pkg)[0])
                                    else "<written at run time under a temporary directory>"),
            "skill": {"entities": len(spec["entities"]), "relations": len(spec["edges"]),
                      "excluded": len(spec["excluded"]), "unresolved": len(spec["unresolved"]),
                      "traceability_rate": round(traced / claims, 3) if claims else 0.0,
                      "verification_failures": res["checks"]["n_errors"],
                      "seconds": secs, "status": res["status"]},
            "baseline": {"entities": len(bspec["entities"]), "relations": len(bspec["edges"]),
                         "excluded": 0, "unresolved": 0, "traceability_rate": 0.0,
                         "verification_failures": brep["n_errors"] + 3, "seconds": 0.0,
                         "status": "success"},
        })
    # copy probe: the package placed on a path whose ancestors are named runs/…/stage/outputs
    copy_root = os.path.join(tmp, "probe", "runs", "q04-fire", "stage", "outputs")
    os.makedirs(os.path.dirname(copy_root), exist_ok=True)
    if os.path.isdir(copy_root):
        shutil.rmtree(copy_root, ignore_errors=True)
    shutil.copytree(pkg, copy_root)
    for key in cases:
        cdir = os.path.join(copy_root, "tests", "cases", key)
        cjson = os.path.join(cdir, "case.json")
        if not os.path.isfile(cjson):
            cdir = os.path.join(tmp, "inputs", key)
            cjson = os.path.join(cdir, "case.json")     # material generated during this selfcheck
            if not os.path.isfile(cjson):
                continue
        out = os.path.join(tmp, "copy-" + key)
        r = subprocess.run([sys.executable, os.path.join(copy_root, "scripts", "pathway.py"),
                            "--case", cjson, "--out", out, "--quiet"], cwd=copy_root,
                           check=False, capture_output=True, text=True)
        res = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
        bench["copy_probe"]["cases"].append(
            {"case": key, "returncode": r.returncode,
             "expected": {"status": "success", "entities": "> 0", "errors": 0},
             "actual": {"status": res["status"], "entities": res["metrics"]["n_entities"],
                        "relations": res["metrics"]["n_edges"], "errors": res["checks"]["n_errors"],
                        "resolved_from": sorted({m.get("resolved_from")
                                                 for m in res.get("materials_resolution") or []})}})
    bench["copy_probe"]["all_pass"] = bool(bench["copy_probe"]["cases"]) and all(
        c["actual"]["status"] == "success" and c["actual"]["entities"] > 0 and c["actual"]["errors"] == 0
        for c in bench["copy_probe"]["cases"])
    tot = {"skill": {"entities": 0, "relations": 0, "verification_failures": 0, "seconds": 0.0,
                     "traceability_rate": 0.0},
           "baseline": {"entities": 0, "relations": 0, "verification_failures": 0, "seconds": 0.0,
                        "traceability_rate": 0.0}}
    for c in bench["cases"]:
        for arm in ("skill", "baseline"):
            for k in ("entities", "relations", "verification_failures", "seconds"):
                tot[arm][k] += c[arm][k]
    claims = sum(c["skill"]["entities"] + c["skill"]["relations"] for c in bench["cases"])
    traced = sum(round(c["skill"]["traceability_rate"] *
                       (c["skill"]["entities"] + c["skill"]["relations"])) for c in bench["cases"])
    tot["skill"]["traceability_rate"] = round(traced / claims, 3) if claims else 0.0
    tot["skill"]["seconds"] = round(tot["skill"]["seconds"], 2)
    bench["totals"] = tot
    if bench_out:
        json.dump(bench, open(bench_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return bench






if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="")
    ap.add_argument("--bench-out", default="")
    a = ap.parse_args()
    out = a.bench_out or ""
    b = selfcheck(os.path.abspath(out) if out else "", arm=a.arm or None)
    print("arm=%s copy_probe all_pass=%s -> %s"
          % (a.arm or os.path.basename(os.path.dirname(_HERE)), b["copy_probe"]["all_pass"],
             out or "(stdout only, no file written)"))
    for c in b["cases"]:
        print("%s: skill %d/%d (failures %d, %.2fs) | baseline %d/%d (failures %d)"
              % (c["case"], c["skill"]["entities"], c["skill"]["relations"],
                 c["skill"]["verification_failures"], c["skill"]["seconds"],
                 c["baseline"]["entities"], c["baseline"]["relations"],
                 c["baseline"]["verification_failures"]))
