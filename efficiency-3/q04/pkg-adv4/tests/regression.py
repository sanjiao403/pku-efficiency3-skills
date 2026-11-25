#!/usr/bin/env python3
"""regression.py — the QA round-2026-11-24 defect suite, shipped so anyone can re-run it.

    python3 tests/regression.py            # exits 0 only if every check passes

Each fixture is a one-line material; each assertion is about the *direction* or the *provenance* of
what was drawn, not about how it looks:

  A  `MAP2K1 is phosphorylated by EGFR.`            -> EGFR -> MAP2K1   (passive voice flips)
  B  `MAP2K1 被 EGFR 磷酸化。`                        -> EGFR -> MAP2K1   (Chinese passive flips)
  C  `EGFR phosphorylates MAP2K1, which then...`     -> no EGFR -> MAPK1 (no layer skip)
  D  `... translocates into the nucleus and drives transcription of FOS.`
                                                    -> transport targets the compartment, one edge
                                                       per ordered pair (no doubled arrow)
  E  `# EGF-stimulated MAPK signalling` heading      -> no `MAPK` pseudo-entity
  F  six tamper variants of a finished run           -> verify.py must go red, each for its own
                                                       reason (unread source, missing file, line past
                                                       EOF, forged quote, evidence emptied,
                                                       materials_resolution emptied)
  G  `MTOR forms a complex with RPTOR and
      phosphorylates S6K1.` (EN + comma + 中文)       -> MTOR -> S6K1, never RPTOR -> S6K1
                                                       (predicate subject = matrix subject)
  H  the G run, tampered twice                       -> verify.py must go red on
                                                       `citation.predicate_subject_not_in_object_slot`
                                                       for the wrong `RPTOR -> S6K1` edge and stay
                                                       green for the correct `MTOR -> S6K1` one
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ENTRY = os.path.join(PKG, "scripts", "pathway.py")
VERIFY = os.path.join(PKG, "scripts", "verify.py")
TMP = tempfile.mkdtemp(prefix="q04-regression-")
ROWS = []


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run(name, material, dpi="72", case_extra=None):
    d = os.path.join(TMP, name)
    w(os.path.join(d, "m.md"), material)
    case = {"case_id": name, "materials": ["m.md"],
            "output_contract": {"entities": "e", "interactions": "i", "status": "s"}}
    case.update(case_extra or {})
    w(os.path.join(d, "case.json"), json.dumps(case, ensure_ascii=False, indent=1))
    out = os.path.join(d, "out")
    p = subprocess.run([sys.executable, ENTRY, "--case", os.path.join(d, "case.json"),
                        "--out", out, "--dpi", dpi, "--quiet"], capture_output=True, text=True)
    rp = os.path.join(out, "result.json")
    r = json.load(open(rp, encoding="utf-8")) if os.path.isfile(rp) else {}
    labels = {e["id"]: e["label"] for e in r.get("entities", [])}
    return {"dir": d, "out": out, "rc": p.returncode, "status": r.get("status"),
            "entities": [e["label"] for e in r.get("entities", [])],
            "edges": [(labels.get(e["source"], e["source"]), e["type"],
                       labels.get(e["target"], e["target"])) for e in r.get("edges", [])],
            "quotes": [(e.get("evidence") or [{}])[0].get("quote", "") for e in r.get("edges", [])],
            "unresolved": [(u.get("locator"), u.get("why")) for u in r.get("unresolved_statements", [])]}


def check(name, ok, detail):
    ROWS.append((name, bool(ok)))
    print("%-4s %-36s %s" % ("PASS" if ok else "FAIL", name, detail))


a = run("A_en_passive", "MAP2K1 is phosphorylated by EGFR.\n")
check("A_en_passive_direction", a["edges"] == [("EGFR", "modifies", "MAP2K1")], "edges=%s" % (a["edges"],))

b = run("B_zh_passive", "MAP2K1 被 EGFR 磷酸化。\n")
check("B_zh_passive_direction", b["edges"] == [("EGFR", "modifies", "MAP2K1")], "edges=%s" % (b["edges"],))

c = run("C_which_clause", "EGFR phosphorylates MAP2K1, which then activates MAPK1.\n")
check("C_no_layer_skip", ("MAP2K1", "activates", "MAPK1") in c["edges"]
      and ("EGFR", "activates", "MAPK1") not in c["edges"], "edges=%s" % (c["edges"],))

d = run("D_transport_target",
        "Activated MAPK1 translocates into the nucleus and drives transcription of FOS.\n")
pairs = [(s, t) for s, _ty, t in d["edges"]]
check("D_transport_not_duplicated",
      len(pairs) == len(set(pairs)) and any(ty == "transports" for _s, ty, _t in d["edges"]),
      "edges=%s" % (d["edges"],))

e = run("E_heading_entity",
        "# EGF-stimulated MAPK signalling\n\nEGFR phosphorylates MAP2K1 in the cytosol.\n")
check("E_no_heading_pseudo_entity", "MAPK" not in e["entities"], "entities=%s" % (e["entities"],))


def verify(outdir, input_dir):
    p = subprocess.run([sys.executable, VERIFY, "--out", outdir, "--input", input_dir],
                       capture_output=True, text=True)
    rep = {}
    rp = os.path.join(outdir, "verify-report.json")
    if os.path.isfile(rp):
        rep = json.load(open(rp, encoding="utf-8"))
    return p.returncode, [l.strip() for l in p.stdout.splitlines() if l.strip().startswith("[")], rep


base = run("F_base", "MAP2K1 is phosphorylated by EGFR.\n")
rc, _f, _r = verify(base["out"], base["dir"])
check("F0_untampered_passes", rc == 0, "verify rc=%s" % rc)


def tamper_from(baserun, tag, mutate):
    dst = os.path.join(TMP, tag)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(baserun["out"], dst)
    rp = os.path.join(dst, "result.json")
    r = json.load(open(rp, encoding="utf-8"))
    mutate(r)
    json.dump(r, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
    return verify(dst, baserun["dir"])


def tamper(tag, mutate):
    return tamper_from(base, tag, mutate)


def expect(name, rc, fails, want):
    hit = [i for i in want if any(i in f for f in fails)]
    check(name, rc != 0 and bool(hit), "rc=%s hit=%s" % (rc, hit))


def unread_source(r):
    r["sources"].append({"id": "mat77", "path": "protocol.md", "kind": "md"})
    r["entities"][0]["evidence"][0] = {"source": "mat77", "locator": "mat77#L1", "quote": "x"}


rc, f, _rep = tamper("F1_unread_source", unread_source)
expect("F1_unread_source_red", rc, f, ["citation.sources_have_read_evidence"])


def missing_file(r):
    real = dict(r["sources"][0])
    r["sources"].append(dict(real, id="mat78", path="nowhere.md"))
    r["entities"][0]["evidence"][0] = {"source": "mat78", "locator": "mat78#L1", "quote": "x"}


rc, f, _rep = tamper("F2_missing_file", missing_file)
expect("F2_missing_file_red", rc, f, ["citation.materials_reachable"])


def past_eof(r):
    r["entities"][0]["evidence"][0]["locator"] = "mat01#L99"


rc, f, _rep = tamper("F3_line_past_eof", past_eof)
expect("F3_line_past_eof_red", rc, f, ["citation.citation_lines_in_range"])


def forged_quote(r):
    r["entities"][0]["evidence"][0]["quote"] = "MAPK1 drives proliferation of the tumour cells."


rc, f, _rep = tamper("F4_forged_quote", forged_quote)
expect("F4_forged_quote_red", rc, f, ["citation.citations_quote_present"])


def no_evidence(r):
    r["entities"][0]["evidence"] = []


rc, f, _rep = tamper("F5_evidence_emptied", no_evidence)
expect("F5_evidence_emptied_red", rc, f, ["citation.claims_have_evidence"])


def no_resolution(r):
    r["materials_resolution"] = []


rc, f, _rep = tamper("F6_resolution_emptied", no_resolution)
expect("F6_resolution_emptied_red", rc, f, ["citation.sources_in_resolution"])

# --------------------------------------------------------------------------------------------
# G/H — the compound-predicate subject (QA 2026-11-24, P0-3) and its verification control pair.
#
# The predicate in `A forms a complex with B and phosphorylates C` belongs to the *matrix* subject A.
# Attaching it to the entity nearest the cue (B, the object of `forms a complex with`) drew
# `B -> C`; the shipped `examples/result.example.json` contained exactly that wrong edge while
# `verify.py` stayed green, so the error was asserted silently.
g = run("G_compound_subject", "MTOR forms a complex with RPTOR and phosphorylates S6K1.\n")
check("G1_compound_subject_is_matrix_subject",
      g["edges"] == [("MTOR", "modifies", "S6K1")], "edges=%s" % (g["edges"],))
check("G2_compound_subject_not_the_object",
      ("RPTOR", "modifies", "S6K1") not in g["edges"], "edges=%s" % (g["edges"],))

g2 = run("G_compound_subject_comma", "MTOR forms a complex with RPTOR, and phosphorylates S6K1.\n")
check("G3_compound_subject_comma",
      [e for e in g2["edges"] if e[1] == "modifies"] == [("MTOR", "modifies", "S6K1")]
      and ("RPTOR", "modifies", "S6K1") not in g2["edges"], "edges=%s" % (g2["edges"],))

gz = run("G_compound_subject_zh",
         "MTOR 与 RPTOR 形成复合物，并磷酸化 S6K1。\n")
check("G4_compound_subject_zh",
      ("MTOR", "modifies", "S6K1") in gz["edges"] and ("RPTOR", "modifies", "S6K1") not in gz["edges"],
      "edges=%s" % (gz["edges"],))

# ---- control pair for the new independent check in verify.py ---------------------------------
rc, _f, rep = verify(g["out"], g["dir"])
mine = [x for x in (rep.get("citation") or {}).get("checks") or []
        if x["id"] == "citation.predicate_subject_not_in_object_slot"]
check("H0_true_negative_correct_edge_is_green",
      rc == 0 and bool(mine) and mine[0]["ok"],
      "verify rc=%s, %s -> ok=%s" % (rc, mine[0]["id"] if mine else "(missing)",
                                     mine[0]["ok"] if mine else None))


def wrong_edge(r):
    """Feed the wrong graph back: the same arrow, but declared to start at RPTOR."""
    lab = {e["label"]: e["id"] for e in r["entities"]}
    for e in r["edges"]:
        if e["type"] == "modifies":
            e["source"] = lab["RPTOR"]


rc, f, rep = tamper_from(g, "H1_wrong_edge_source", wrong_edge)
expect("H1_true_positive_wrong_edge_is_red", rc, f,
       ["citation.predicate_subject_not_in_object_slot"])
check("H1b_red_for_the_object_slot_reason",
      any("object slot" in f for f in f), "fails=%s" % (f,))


def wrong_label(r):
    """Same graph geometry, wrong claim: the node at the arrow's tail is *called* RPTOR. Only the
    predicate-subject layer can see this — ids, arrow endpoints and export records stay valid."""
    for e in r["entities"]:
        if e["label"] == "MTOR":
            e["label"] = "RPTOR"


rc, f, rep = tamper_from(g, "H2_wrong_edge_label", wrong_label)
expect("H2_true_positive_label_swap_is_red", rc, f,
       ["citation.predicate_subject_not_in_object_slot"])

# --------------------------------------------------------------------------------------------
# I/J — a Markdown heading line is topic metadata, never a subject (QA 2026-11-24, P0-4).
#
# A heading does not end with sentence punctuation, so the line-join used to glue it to the sentence
# below: `# MAPK1 pathway overview` + `Extracellular EGF binds EGFR.` became one "sentence" whose
# first mention was the heading's word, and the figure asserted `MAPK1 -> EGFR` while `verify.py`
# stayed green (44/44). Four shapes, plus the case where the heading word is the sentence's *object*
# (there the whole edge used to disappear).
i1 = run("I1_heading_subject",
         "# MAPK1 pathway overview\nExtracellular EGF binds EGFR.\nMAP2K1 activates MAPK1.\n")
check("I1_heading_word_is_not_the_subject",
      ("EGF", "binds", "EGFR") in i1["edges"] and ("MAPK1", "binds", "EGFR") not in i1["edges"],
      "edges=%s" % (i1["edges"],))
check("I1b_heading_word_keeps_its_own_body_edge",
      ("MAP2K1", "activates", "MAPK1") in i1["edges"], "edges=%s" % (i1["edges"],))
check("I1c_citation_quotes_the_body_sentence",
      all("overview" not in q for q in i1["quotes"])
      and any(q.startswith("Extracellular EGF binds EGFR") for q in i1["quotes"]),
      "quotes=%s" % (i1["quotes"],))

i2 = run("I2_heading_other_entity",
         "# S6K1 signalling overview\nExtracellular EGF binds EGFR.\nS6K1 inhibits IRS1.\n")
check("I2_heading_entity_in_body_too",
      ("EGF", "binds", "EGFR") in i2["edges"] and ("S6K1", "inhibits", "IRS1") in i2["edges"]
      and ("S6K1", "binds", "EGFR") not in i2["edges"], "edges=%s" % (i2["edges"],))

i3 = run("I3_heading_no_space", "#MAPK1 overview\nExtracellular EGF binds EGFR.\n")
check("I3_heading_without_space_after_hash",
      i3["edges"] == [("EGF", "binds", "EGFR")], "edges=%s" % (i3["edges"],))

i4 = run("I4_heading_then_compound_sentence",
         "# MTOR signalling overview\nMTOR forms a complex with RPTOR and phosphorylates S6K1.\n"
         "S6K1 inhibits IRS1.\n")
check("I4_heading_plus_compound_predicate",
      ("MTOR", "modifies", "S6K1") in i4["edges"] and ("RPTOR", "modifies", "S6K1") not in i4["edges"],
      "edges=%s" % (i4["edges"],))

i5 = run("I5_heading_word_is_the_object", "# MAPK1 pathway overview\nEGFR binds MAPK1.\n")
check("I5_heading_word_as_object_edge_is_not_swallowed",
      i5["edges"] == [("EGFR", "binds", "MAPK1")], "edges=%s" % (i5["edges"],))

i6 = run("I6_heading_one_word_only", "# MAPK1\nMAP2K1 activates MAPK1.\n")
check("I6_one_word_heading", i6["edges"] == [("MAP2K1", "activates", "MAPK1")],
      "edges=%s" % (i6["edges"],))

# ---- control pair for the heading check -----------------------------------------------------
rc, _f, rep = verify(i1["out"], i1["dir"])
mine = [x for x in (rep.get("citation") or {}).get("checks") or []
        if x["id"] == "citation.quote_is_its_own_sentence"]
check("J0_true_negative_body_quote_is_green",
      rc == 0 and bool(mine) and mine[0]["ok"],
      "verify rc=%s, %s -> ok=%s" % (rc, mine[0]["id"] if mine else "(missing)",
                                     mine[0]["ok"] if mine else None))


def glued_quote(r):
    """Re-create exactly what the parent arm delivered: the subject is the heading's word and the
    citation starts inside the heading line."""
    lab = {e["label"]: e["id"] for e in r["entities"]}
    for e in r["edges"]:
        if e["type"] == "binds":
            e["source"] = lab["MAPK1"]
            e["evidence"][0]["locator"] = "mat01#L1"
            e["evidence"][0]["quote"] = "MAPK1 pathway overview Extracellular EGF binds EGFR."


rc, f, rep = tamper_from(i1, "J1_glued_quote", glued_quote)
expect("J1_true_positive_glued_quote_is_red", rc, f, ["citation.quote_is_its_own_sentence"])
check("J1b_red_for_the_heading_reason", any("heading" in l for l in f), "fails=%s" % (f,))

print("\n%d/%d checks passed" % (sum(1 for _n, ok in ROWS if ok), len(ROWS)))
sys.exit(0 if all(ok for _n, ok in ROWS) else 1)
