# -*- coding: utf-8 -*-
"""selftest.py — expected vs actual from real runs, including negative controls.

    python3 tests/selftest.py --report tests/selftest-report.json

T1..T6 run the main command on the shipped example and check the artifacts.
T7 is a NEGATIVE CONTROL: the deck is tampered with after the fact (a fabricated
bullet declared as a verbatim quote; a number transplanted onto the wrong page; an
anchor pointing at a page that does not exist) and the shipped verifier must FAIL
each of them.  Without T7 a green report only proves that the checker agrees with
itself.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
PY = sys.executable
EX = os.path.join(PKG, "examples")


def run(args, cwd):
    p = subprocess.run([PY] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(HERE, "selftest-report.json"))
    a = ap.parse_args(argv)
    root = tempfile.mkdtemp(prefix="deck-selftest-")
    rep = {"note": "expected vs actual, produced by real runs of the main command; "
                   "T7 are negative controls that must fail",
           "python": sys.version.split()[0], "tests": [], "passed": True}

    def rec(name, expected, actual, ok=None, extra=None):
        ok = (expected == actual) if ok is None else ok
        row = {"test": name, "expected": expected, "actual": actual, "ok": bool(ok)}
        if extra:
            row.update(extra)
        rep["tests"].append(row)
        rep["passed"] = rep["passed"] and bool(ok)

    def case_dir(name, extra_case=None, deck=None):
        d = os.path.join(root, "in", name)
        os.makedirs(d, exist_ok=True)
        for n in os.listdir(EX):
            shutil.copy2(os.path.join(EX, n), os.path.join(d, n))
        cj = json.load(open(os.path.join(d, "case.example.json"), encoding="utf-8"))
        os.remove(os.path.join(d, "case.example.json"))
        cj = {**cj, "case_id": "T1-EXAMPLE", **(extra_case or {})}
        if deck:
            shutil.copy2(deck, os.path.join(d, "starting-deck.pptx"))
        json.dump(cj, open(os.path.join(d, "case.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        return d

    def checks_of(out):
        p = os.path.join(out, "_work", "checks.json")
        return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}

    # ------------------------------------------------------------------ T1 generate
    d1, o1 = case_dir("case-01"), os.path.join(root, "out-01")
    rc, log = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                   os.path.join(d1, "case.json"), "--out", o1], root)
    r1 = json.load(open(os.path.join(o1, "result.json"), encoding="utf-8"))
    c1 = checks_of(o1)
    rec("T1 generate: exit code", 0, rc, extra={"tail": log[-200:]})
    rec("T1 generate: result.status", "success", r1.get("status"))
    rec("T1 generate: case_id echoes the input case (QA-round-20261124 P0-1)", "T1-EXAMPLE",
        r1.get("case_id"))
    rec("T1 generate: notes contract is read back from the deck", "read back from "
        "deck.pptx", r1.get("notes_origin"))
    rec("T1 generate: every page's notes contract is non-empty", 0,
        len([x for x in (r1.get("notes") or []) if not str(x.get("notes") or "").strip()]))
    rec("T1 generate: no page is an undeclared blank", [], (r1.get("deliverable") or {}
                                                           ).get("declared_backup_pages")
        or [])
    rec("T1 generate: slides == case slide_count", 8,
        (r1.get("deliverable") or {}).get("slides"))
    rec("T1 generate: contract keys echoed", True,
        all(k in r1 for k in ("deliverable", "slide_plan", "evidence_map", "notes",
                              "claim_support", "render_and_versions")))
    rec("T1 generate: outputs[] carries sha256", True,
        all(o.get("sha256") for o in (r1.get("outputs") or [])))
    rec("T1 generate: no check failed", 0, (c1.get("summary") or {}).get("failed"))
    rec("T1 generate: n/a checks are listed, not silent", True,
        isinstance((c1.get("summary") or {}).get("not_applicable"), list))
    rec("T1 generate: body text is not empty (placeholder kept)", True,
        bool([e for e in (r1.get("evidence_map") or []) if e.get("slide", 0) > 2]) and
        bool([s for s in (r1.get("deliverable", {}).get("png_previews") or [])]))

    # ---------------------------------------------------------------------- T2 edit
    d2 = case_dir("case-03", deck=os.path.join(o1, "deck.pptx"),
                  extra_case={"slide_count": 6, "ops": [
                      {"op": "set_title", "slide": 1, "text": "Fixture deck (edited)"},
                      {"op": "compress_bullets", "slide": 4, "max": 1,
                       "why": "selftest"},
                      {"op": "delete_slide", "slide": 8, "why": "8 -> 7"},
                      {"op": "delete_slide", "slide": 7, "why": "7 -> 6"},
                      {"op": "set_notes", "slide": 1, "text": "[讲稿] selftest"}]})
    o2 = os.path.join(root, "out-03")
    rc2, log2 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d2, "case.json"), "--out", o2], root)
    r2 = json.load(open(os.path.join(o2, "result.json"), encoding="utf-8"))
    er = json.load(open(os.path.join(o2, "_work", "edit_report.json"), encoding="utf-8"))
    c2 = checks_of(o2)
    c10 = next((c for c in c2.get("checks", []) if c.get("id") == "C10"), {})
    rec("T2 edit: exit code", 0, rc2, extra={"tail": log2[-200:]})
    rec("T2 edit: result.status", "success", r2.get("status"),
        extra={"uncertainty": r2.get("uncertainty"),
               "checks": (c2.get("summary") or {})})
    rec("T2 edit: slide count trimmed to the case instruction", 6,
        er.get("slides_after"))
    rec("T2 edit: template_preserved (edit report)", True, er.get("template_preserved"))
    rec("T2 edit: C10 compares against the starting deck it edited", "pass",
        c10.get("status"),
        extra={"baseline": (c10.get("detail") or {}).get("baseline"),
               "role": (c10.get("detail") or {}).get("baseline_role"), "why": c10})
    rec("T2 edit: version snapshots written", 2, len(er.get("versions") or []))

    # ----------------------------------------------------------------- T3 recompute
    for tag, o, expect in (("generated", o1, 0), ("edited", o2, 0)):
        rc3, log3 = run([os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                         os.path.join(o, "deck.pptx"), "--result",
                         os.path.join(o, "result.json")], root)
        rec("T3 recompute (%s deck) exits 0" % tag, expect, rc3,
            extra={"tail": log3[-240:]})

    # ---------------------------------------------------------- T4 cwd independence
    ext = tempfile.mkdtemp(prefix="deck-cwd-")
    rc4, log4 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d1, "case.json"), "--out", os.path.join(ext, "out")],
                    ext)
    r4 = json.load(open(os.path.join(ext, "out", "result.json"), encoding="utf-8"))
    rep["cwd_independence"] = {
        "command": "cd <external-cwd> && python3 <pkg>/scripts/deck.py --case "
                   "<in>/case.json --out <external-cwd>/out",
        "cwd": "<external temp dir, not the package dir and not /input>",
        "exit_code": rc4, "status": r4.get("status"),
        "slides": (r4.get("deliverable") or {}).get("slides"),
        "resolved_from": r4.get("resolved_from"), "tail": log4[-160:]}
    rec("T4 cwd independence: status success", "success", r4.get("status"))
    rec("T4 cwd independence: material resolved from case_dir", "case_dir",
        (r4.get("resolved_from") or {}).get("material"))

    # ------------------------------------------------------------------ T5 copy probe
    deep = os.path.join(tempfile.mkdtemp(prefix="copy-probe-"), "runs", "q09-fire",
                        "stage", "outputs", "pkg-copy")
    shutil.copytree(PKG, deep, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    ext2 = tempfile.mkdtemp(prefix="copy-probe-out-")
    rc5, log5 = run([os.path.join(deep, "scripts", "deck.py"), "--case",
                     os.path.join(deep, "examples", "case.example.json"), "--out",
                     os.path.join(ext2, "out")], ext2)
    r5 = json.load(open(os.path.join(ext2, "out", "result.json"), encoding="utf-8"))
    rep["copy_probe"] = {
        "why": "input discovery keys on file names only, never on absolute path "
               "segments: a package placed under a path containing 'outputs' still "
               "sees its inputs",
        "copy_path_shape": "<tmp>/runs/q09-fire/stage/outputs/pkg-copy",
        "command": "cd <external-cwd> && python3 <copy>/scripts/deck.py --case "
                   "<copy>/examples/case.example.json --out <external-cwd>/out",
        "exit_code": rc5, "status": r5.get("status"),
        "slides": (r5.get("deliverable") or {}).get("slides"),
        "discover": next((s.get("status") for s in r5.get("stages", [])
                          if s.get("stage") == "discover"), None),
        "uncertainty": r5.get("uncertainty")}
    rec("T5 copy probe: exit code", 0, rc5)
    rec("T5 copy probe: status success", "success", r5.get("status"))
    rec("T5 copy probe: slides == 8", 8, (r5.get("deliverable") or {}).get("slides"))

    # ------------------------------------------------------- T6 empty-artifact guard
    d6 = os.path.join(root, "in", "empty")
    os.makedirs(d6, exist_ok=True)
    json.dump({"case_id": "EMPTY", "slide_count": 5,
               "output_contract": {"deliverable": "pptx"}},
              open(os.path.join(d6, "case.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    o6 = os.path.join(root, "out-empty")
    rc6, log6 = run([os.path.join(PKG, "scripts", "deck.py"), "--case",
                     os.path.join(d6, "case.json"), "--out", o6], root)
    r6 = (json.load(open(os.path.join(o6, "result.json"), encoding="utf-8"))
          if os.path.isfile(os.path.join(o6, "result.json")) else {})
    rep["empty_artifact_guard"] = {"exit_code": rc6, "status": r6.get("status"),
                                   "slides": (r6.get("deliverable") or {}).get("slides"),
                                   "uncertainty": r6.get("uncertainty")}
    rec("T6 empty input: status is not success", True,
        r6.get("status") in ("partial", "failed"))
    rec("T6 empty input: a reason is recorded", True, bool(r6.get("uncertainty")))

    # -------------------------------------------- T7 negative controls (must FAIL)
    import re
    from pptx import Presentation
    from pptx.util import Inches
    ctrl = []
    for tag, mutate, want in (
            ("fabricated-bullet", "text", "C12"),
            ("number-moved-to-another-page", "number", "C13"),
            ("anchor-points-at-a-wrong-page", "anchor", "C11")):
        outs = os.path.join(root, "tamper-" + tag)
        shutil.copytree(o1, outs)
        prs = Presentation(os.path.join(outs, "deck.pptx"))
        sl = list(prs.slides)[3]
        notes = sl.notes_slide.notes_text_frame
        body = next(sh for sh in sl.shapes
                    if sh.has_text_frame and sh.name.startswith("Content"))
        lines, done = notes.text.splitlines(), False
        for idx, ln in enumerate(lines):
            m = re.match(r"^-\s+(?P<body>.+?)\s+(?P<anchor>\[来源[^\]]*\])\s*$", ln)
            if not m or done:
                continue
            if mutate == "text":
                claim = "本方法把残差学习与恒等映射结合，作者声称该结论对所有数据集一律成立。"
                lines[idx] = "- %s  %s" % (claim, m.group("anchor"))
                body.text_frame.paragraphs[0].text = claim
            elif mutate == "number":
                claim = "Decoys aside, this sentence claims 88.88% for every dataset."
                lines[idx] = "- %s  %s" % (claim, m.group("anchor"))
                body.text_frame.paragraphs[0].text = claim
            else:
                lines[idx] = "- %s  %s" % (m.group("body"),
                                           m.group("anchor").replace(" p.1 ", " p.99 "))
            done = True
        notes.text = "\n".join(lines)
        prs.save(os.path.join(outs, "deck.pptx"))
        rc7, log7 = run([os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                         os.path.join(outs, "deck.pptx"), "--case",
                         os.path.join(d1, "case.json"), "--source",
                         os.path.join(o1, "_work", "source.json"), "--spec",
                         os.path.join(o1, "_work", "deck_plan.json"), "--template",
                         os.path.join(o1, "_work", "neutral-master.pptx"), "--out",
                         os.path.join(outs, "tampered-checks.json")], root)
        c7 = json.load(open(os.path.join(outs, "tampered-checks.json"), encoding="utf-8"))
        failed = [c["id"] for c in c7.get("checks", []) if c["status"] == "fail"]
        ctrl.append({"control": tag, "must_fail": want, "failed_ids": failed,
                     "exit_code": rc7})
        rec("T7 negative control (%s): %s fails" % (tag, want), True, want in failed,
            extra={"exit_code": rc7, "failed_ids": failed,
                   "why": "a tampered deck must not be reported as verified"})

    # T8 negative controls on the rendered preview (byte-level, not on trust)
    outs = os.path.join(root, "tamper-preview")
    shutil.copytree(o1, outs)
    rr = json.load(open(os.path.join(outs, "_work", "render_report.json"),
                        encoding="utf-8"))
    rr["pdf"] = os.path.join(outs, "preview", "deck.pdf")
    rr["png"] = [os.path.join(outs, "preview", os.path.basename(p))
                 for p in (rr.get("png") or [])]
    json.dump(rr, open(os.path.join(outs, "_work", "render_report.json"), "w",
                       encoding="utf-8"), ensure_ascii=False)
    try:
        import fitz
        d = fitz.open()
        d.new_page(width=960, height=540)
        d.save(os.path.join(outs, "preview", "deck.pdf"))
        d.close()
    except Exception as e:
        rep["preview_tamper_error"] = str(e)[:120]
    rc8, _ = run([os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                  os.path.join(outs, "deck.pptx"), "--case",
                  os.path.join(d1, "case.json"), "--source",
                  os.path.join(o1, "_work", "source.json"), "--spec",
                  os.path.join(o1, "_work", "deck_plan.json"), "--render",
                  os.path.join(outs, "_work", "render_report.json"), "--out",
                  os.path.join(outs, "tampered-checks.json")], root)
    c8 = json.load(open(os.path.join(outs, "tampered-checks.json"), encoding="utf-8"))
    failed8 = [c["id"] for c in c8.get("checks", []) if c["status"] == "fail"]
    rec("T8 negative control (preview truncated to one page): C14 fails", True,
        "C14" in failed8, extra={"exit_code": rc8, "failed_ids": failed8})

    outs = os.path.join(root, "tamper-stub-image")
    shutil.copytree(o1, outs)
    from PIL import Image
    stub = os.path.join(root, "stub.png")
    Image.new("RGB", (1, 1), (255, 255, 255)).save(stub)
    prs = Presentation(os.path.join(outs, "deck.pptx"))
    prs.slides[2].shapes.add_picture(stub, Inches(1), Inches(1), Inches(3), Inches(2))
    prs.save(os.path.join(outs, "deck.pptx"))
    rc9, _ = run([os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                  os.path.join(outs, "deck.pptx"), "--case",
                  os.path.join(d1, "case.json"), "--source",
                  os.path.join(o1, "_work", "source.json"), "--spec",
                  os.path.join(o1, "_work", "deck_plan.json"), "--render",
                  os.path.join(outs, "_work", "render_report.json"), "--out",
                  os.path.join(outs, "tampered-checks.json")], root)
    c9 = json.load(open(os.path.join(outs, "tampered-checks.json"), encoding="utf-8"))
    failed9 = [c["id"] for c in c9.get("checks", []) if c["status"] == "fail"]
    rec("T9 negative control (1x1 stub pasted as a figure): C15 fails", True,
        "C15" in failed9, extra={"exit_code": rc9, "failed_ids": failed9})

    # T10-T12 negative controls for the QA-round-20261124 fixes
    def verify_with(outdir, contract=None, extra=()):
        args = [os.path.join(PKG, "scripts", "verify.py"), "--pptx",
                os.path.join(outdir, "deck.pptx"), "--case",
                os.path.join(d1, "case.json"), "--source",
                os.path.join(o1, "_work", "source.json"), "--spec",
                os.path.join(o1, "_work", "deck_plan.json"), "--render",
                os.path.join(outdir, "_work", "render_report.json"), "--out",
                os.path.join(outdir, "checks-tampered.json")] + list(extra)
        if contract:
            args += ["--contract", contract]
        rc, log = run(args, root)
        c = json.load(open(os.path.join(outdir, "checks-tampered.json"), encoding="utf-8"))
        return rc, [x["id"] for x in c.get("checks", []) if x["status"] == "fail"]

    outs = os.path.join(root, "tamper-empty-body")
    shutil.copytree(o1, outs)
    prs = Presentation(os.path.join(outs, "deck.pptx"))
    sl = list(prs.slides)[2]
    for sh in list(sl.shapes):
        if sh.has_text_frame and sh.name.startswith("Content"):
            sh._element.getparent().remove(sh._element)
    prs.save(os.path.join(outs, "deck.pptx"))
    rc10, f10 = verify_with(outs)
    rec("T10 negative control (content page emptied, no [备份]): C08 fails", True,
        "C08" in f10, extra={"exit_code": rc10, "failed_ids": f10})

    outs = os.path.join(root, "tamper-contract-id")
    shutil.copytree(o1, outs)
    rr = json.load(open(os.path.join(outs, "result.json"), encoding="utf-8"))
    rr["case_id"] = "C07"                      # the exact P0-1 symptom
    json.dump(rr, open(os.path.join(out1 := os.path.join(outs, "contract.json"), ), "w",
                       encoding="utf-8"), ensure_ascii=False)
    rc11, f11 = verify_with(outs, contract=out1)
    rec("T11 negative control (contract case_id polluted): C16 fails", True,
        "C16" in f11, extra={"exit_code": rc11, "failed_ids": f11})

    outs = os.path.join(root, "tamper-contract-notes")
    shutil.copytree(o1, outs)
    rr = json.load(open(os.path.join(outs, "result.json"), encoding="utf-8"))
    for row in rr.get("notes") or []:
        row["notes"] = row["notes_full"] = ""
    cpath = os.path.join(outs, "contract.json")
    json.dump(rr, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    rc12, f12 = verify_with(outs, contract=cpath)
    rec("T12 negative control (contract notes emptied): C16 fails", True,
        "C16" in f12, extra={"exit_code": rc12, "failed_ids": f12})

    outs = os.path.join(root, "tamper-contract-source")
    shutil.copytree(o1, outs)
    rr = json.load(open(os.path.join(outs, "result.json"), encoding="utf-8"))
    rr["sources"] = [{"kind": "material", "path": "task.md"}]
    cpath = os.path.join(outs, "contract.json")
    json.dump(rr, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    rc13, f13 = verify_with(outs, contract=cpath)
    rec("T13 negative control (work order promoted into sources[]): C16 fails", True,
        "C16" in f13, extra={"exit_code": rc13, "failed_ids": f13})
    rep["negative_controls"] = ctrl

    # ---- T14/T15: the name rule must not over-block (focus re-check finding ③)
    def name_case(tag, fname, body):
        d = os.path.join(root, "name", tag)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, fname), "w", encoding="utf-8").write(body)
        json.dump({"case_id": "NAME-" + tag.upper(), "audience": "group_meeting",
                   "language": "zh", "duration_min": 8, "slide_count": 6,
                   "output_contract": {"deliverable": "pptx", "evidence_map": "jsonl"}},
                  open(os.path.join(d, "case.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        o = os.path.join(d, "out")
        run([os.path.join(PKG, "scripts", "deck.py"), "--case",
             os.path.join(d, "case.json"), "--out", o], root)
        p = os.path.join(o, "result.json")
        r = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}
        disc = next((s.get("detail") or {} for s in r.get("stages", [])
                     if s.get("stage") == "discover"), {})
        return (r.get("status"), (r.get("deliverable") or {}).get("slides"),
                disc.get("material"), [x.get("file") for x in
                                       (disc.get("refused_as_evidence") or [])])

    paper = "".join("## Results %d\n\nThe router cuts p95 latency by 4%d.2%% while "
                    "accuracy drops by only 0.8 points with a budget of 32 "
                    "passages.\n\n" % (i, i) for i in range(1, 41))
    st14, sl14, mat14, ref14 = name_case("t14", "case-study-routing.md", paper)
    rec("T14 a real paper named case-study-routing.md is read as material", True,
        st14 == "success" and mat14 == "case-study-routing.md",
        extra={"status": st14, "slides": sl14, "material": mat14, "refused": ref14})
    sheet = ("# Work order\n\nDeliver a deck.\n\n## 评分维度\n\noutput_contract must be "
             "echoed. Runtime contract: 64 requests, 900 seconds. Do not submit "
             "prepared answers.\n")
    st15, sl15, mat15, ref15 = name_case("t15", "case-study-notes.md", sheet)
    rec("T15 a task sheet renamed to a paper-like name is still refused", True,
        mat15 is None and "case-study-notes.md" in (ref15 or []),
        extra={"status": st15, "slides": sl15, "material": mat15, "refused": ref15})

    # ---- T16/T17: evaluation vocabulary must NOT get a real paper refused
    # (focus re-check finding: an LLM-as-a-judge paper uses grader/rubric everywhere)
    eval_paper = ("# Calibrating Automatic Graders\n\nWe study whether an automatic "
                  "grader can match a human rubric. Each answer is scored by a human "
                  "grader and by our judge model on a shared rubric with five "
                  "criteria.\n\n")
    eval_paper += "".join("## Analysis %d\n\nThe automatic grader agrees with the "
                          "human rubric on 4%d.2%% of items while the disagreement "
                          "rate stays below 0.8 points on the shared rubric, with a "
                          "budget of 32 passages.\n\n" % (i, i % 10)
                          for i in range(1, 41))
    st16, sl16, mat16, ref16 = name_case("t16", "llm-eval-paper.md", eval_paper)
    rec("T16 a real paper using grader/rubric is read as material", True,
        st16 == "success" and mat16 == "llm-eval-paper.md",
        extra={"status": st16, "slides": sl16, "material": mat16, "refused": ref16})
    assess = ("# 面向开放题的自动评分维度研究\n\n本文研究自动评分维度是否稳定：我们请两名"
              "评分者按同一份 rubric 打分，并用 grader 模型复现评分维度。\n\n")
    assess += "".join("## 实验 %d\n\n在第 %d 组实验里，自动评分维度与人工评分者的一致率为 "
                      "9%d.3%%，平均偏差 0.4 分。\n\n" % (i, i, i % 10)
                      for i in range(1, 41))
    st17, sl17, mat17, ref17 = name_case("t17", "assessment-paper.md", assess)
    rec("T17 a Chinese assessment paper mentioning 评分维度 is read as material", True,
        st17 == "success" and mat17 == "assessment-paper.md",
        extra={"status": st17, "slides": sl17, "material": mat17, "refused": ref17})
    for tag, fname in (("t18", "task-notes.md"), ("t19", "case_report.md")):
        stx, slx, matx, refx = name_case(tag, fname, eval_paper)
        rec("T%s a real paper named %s is read as material" % (tag[1:], fname), True,
            stx == "success" and matx == fname,
            extra={"status": stx, "slides": slx, "material": matx, "refused": refx})
    st20, sl20, mat20, ref20 = name_case("t20", "brief.md", sheet)
    rec("T20 a work order named brief.md is still refused", True,
        mat20 is None and "brief.md" in (ref20 or []),
        extra={"status": st20, "slides": sl20, "material": mat20, "refused": ref20})

    # ---- T21/T22: grading vocabulary alone must never refuse a paper
    # (focus re-check: a Chinese annotation paper and an NLP "prepared answer" paper)
    zh_annot = ("# 面向长文本问答的标注方案与一致性研究\n\n本文给出一套人工标注方案：评分维度"
                "包括事实性、覆盖度、连贯性与校准度；每个评分点 1–5 分；评分细则见附录 A。\n\n"
                "三名标注者独立打分，我们用 Krippendorff α 报告评分维度之间的一致性。\n\n")
    zh_annot += "".join("## 分析 %d\n\n在第 %d 组样本上，评分维度之间的一致性为 8%d.3%%，"
                        "平均分歧 0.4 分，说明该评分细则在长文本上可以稳定复现。\n\n"
                        % (i, i, i % 10) for i in range(1, 41))
    st21, sl21, mat21, ref21 = name_case("t21", "zh-annotation-paper.md", zh_annot)
    rec("T21 a Chinese annotation paper (评分维度/评分点/评分细则) is read as material",
        True, st21 == "success" and mat21 == "zh-annotation-paper.md",
        extra={"status": st21, "slides": sl21, "material": mat21, "refused": ref21})
    prep = ("# Prepared Answers versus Retrieved Passages for Open-Domain QA\n\nWe "
            "compare answering from a fixed set of prepared answers with answering from "
            "retrieved passages; the prepared answer set is re-ranked by a reader.\n\n")
    prep += "".join("## Results %d\n\nWith prepared answers the reader reaches 7%d.4 "
                    "exact match against 72.5 for retrieved passages.\n\n" % (i, i % 10)
                    for i in range(1, 41))
    st22, sl22, mat22, ref22 = name_case("t22", "prepared-answers-paper.md", prep)
    rec("T22 a paper about prepared answers is read as material", True,
        st22 == "success" and mat22 == "prepared-answers-paper.md",
        extra={"status": st22, "slides": sl22, "material": mat22, "refused": ref22})

    rep["runtime_workdir"] = "temporary (not shipped)"
    json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"report": a.report, "passed": rep["passed"],
                      "failed": [t["test"] for t in rep["tests"] if not t["ok"]]},
                     ensure_ascii=False, indent=1))
    shutil.rmtree(root, ignore_errors=True)
    return 0 if rep["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
