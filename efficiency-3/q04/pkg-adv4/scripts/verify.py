#!/usr/bin/env python3
"""verify.py — independent self-check of a finished run.

    python3 scripts/verify.py --out /app/output

Two groups of checks, kept apart on purpose:

* `checks[]`   — spec-level invariants (ids, typing, arrow grammar, direction, legend, no invented
  data). They read `spec.json` on disk, never memory, but they do share the grammar table with the
  writer, so on their own they cannot prove that the *figure* obeys the grammar.
* `artefact[]` — re-derived from the delivered artefacts only (`figure.svg` + `result.json`): which
  entity/edge ids are really in the SVG, whether each interaction type really has its own arrow
  geometry in the markup, whether each arrow really starts inside its declared source and ends
  inside its declared target, whether the drawing is raster-free, and whether the reported citations
  and the reported export format are honoured by what is on disk.

Exit 0 = PASS, 2 = FAIL."""
import argparse, json, os, re, sys

sys.dont_write_bytecode = True          # never leave __pycache__/*.pyc inside the Skill tree
from pathway import R, TYP, WID


def _box(rects):
    """Union bounding box of the rect primitives of one node group (a receptor straddles the
    membrane and is drawn as three rects, so the first rect is not the node box)."""
    xs, ys, xe, ye = [], [], [], []
    for x, y, w, h in rects:
        xs.append(x); ys.append(y); xe.append(x + w); ye.append(y + h)
    if not xs:
        return None
    return (min(xs), min(ys), max(xe), max(ye))


def _prims(inner):
    """Primitive sequence of one edge group, read from the markup (no spec involved)."""
    sig, dash = [], ""
    for m in re.finditer(r"<(line|polyline|polygon|circle|text)\b([^>]*)>", inner):
        tag, at = m.group(1), m.group(2)
        d = re.search(r'stroke-dasharray="([^"]*)"', at)
        if d:
            dash = d.group(1)
        if tag == "line":
            sig.append("L")
        elif tag == "circle":
            sig.append("C")
        elif tag == "text":
            sig.append("X")                      # a modification tag / label on the edge
        elif tag == "polyline":
            sig.append("O")
        else:
            sig.append("H" if re.search(r'fill="#FFFFFF"', at) else "T")
    return "-".join(sig) + "|" + dash


def _norm_text(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# An entity that directly follows one of these is in an *object* slot, so a predicate cannot have
# that entity as its subject: `forms a complex with RPTOR`, `与 RPTOR 形成复合物`. The list is
# deliberately small and literal — this layer re-reads the material, it does not share the writer's
# clause parser.
_OBJE = re.compile(r"(?:(?<![A-Za-z])(?:with|of|by|for|from|via|through|using|including|plus|against|"
                   r"into|in|on|at|to|as|than)|[和与及])"
                   r"(?:\s+(?:the|a|an|its|their|his|her))?\s*$", re.I)
_OBJZ = re.compile(r"(?:与|和|及|同|跟|对|向|给|由|被|为|从|在|使|让)\s*$")
_BY = re.compile(r"\bby\b")
_ZBY = re.compile("[由被受]")
# A Markdown heading/label line — 1-6 `#` at the start of a line, with or without a space after them
# (`#MAPK1`), and also inside a blockquote. This mirrors the writer's pattern on purpose: the point of
# the check is that both sides agree on what a heading *is*.
_HEADING = re.compile(r"\s{0,3}(?:>\s*)?#{1,6}\s*\S")


def _heading_leaks(raw):
    """(heading text, text of the line below it) for every heading, whitespace-normalised.

    A heading does not end with sentence punctuation, so the writer's line-join used to glue it to
    the sentence underneath. Re-deriving that pair from the raw file is what lets this layer say
    "this quote begins inside a heading" without sharing the writer's clause code."""
    lines = (raw or "").split("\n")
    out = []
    for i, ln in enumerate(lines):
        if _HEADING.match(ln):
            h = _norm_text(re.sub(r"^\s{0,3}(?:>\s*)?#{1,6}\s*", "", ln))
            body = _norm_text(lines[i + 1]) if i + 1 < len(lines) else ""
            if h and body:
                out.append((h, body))
    return out


def _pos_of(q, cands):
    """Every position of the predicate cue in the quoted sentence, inflection-tolerant.

    The recorded cue is the 3rd-person singular form from the vocabulary (`phosphorylates`) while the
    sentence may carry any inflection (`phosphorylated`), and a Chinese passive cue is a pattern
    (`由.*?激活`), so the literal is tried first and the pattern second. All occurrences are returned:
    a cue may appear twice in one clause and the claim may hang off either of them."""
    out = set()
    for c in cands:
        c = (c or "").strip().lower()
        if not c:
            continue
        for st in {c, c[:-1] if c.endswith(("s", "e")) else c}:
            try:
                for m in re.finditer(re.escape(st), q):
                    out.add(m.start())
                for m in re.finditer(st, q, re.I):
                    out.add(m.start())
            except re.error:
                pass
    return sorted(out)


def predicate_subject_checks(res, lines_of):
    """Independent re-derivation: does every drawn edge really name, as its subject, an entity that
    sits in *subject* position in the sentence the edge cites?

    The writer's own subject resolution lives in `pathway.py`; this layer must not trust it. It takes
    the quoted sentence out of `result.json`, finds the predicate cue in that text, locates the
    declared source entity in front of it (or behind `by` / 由 / 被 for a passive), and refuses an
    edge whose only occurrence there is the object of a preposition or conjunction.

    That is exactly the shape of the defect this arm repairs: in
    `MTOR forms a complex with RPTOR and phosphorylates S6K1` the parent arm attached the predicate
    to `RPTOR` — the object of `forms a complex with` — and delivered `RPTOR -> S6K1` while its own
    42 checks stayed green (QA 2026-11-24, P0-3)."""
    C = []

    def c(cid, okk, det, lvl="error"):
        C.append({"id": "citation." + cid, "ok": bool(okk), "level": lvl, "detail": det})

    ents = {e.get("id"): e for e in res.get("entities") or []}
    prose = "prose" in str(res.get("graph_source") or "").lower()
    absent, objslot, na = [], [], []
    for e in res.get("edges") or []:
        ev = (e.get("evidence") or [{}])[0]
        q = _norm_text(ev.get("quote") or "")
        sid = str(ev.get("locator") or "").partition("#L")[0]
        if not q or sid not in lines_of or (e.get("type") or "") not in R:
            na.append(e.get("id"))
            continue
        m0 = re.match(r"cue '([^']*)'", str(e.get("origin") or ""))
        cands = [m0.group(1)] if m0 else []
        cands += (R[e["type"]]["en"] + " " + R[e["type"]]["zh"]).split()
        poss = _pos_of(q, cands)                    # every cue occurrence, not just the first one
        if not poss:
            na.append("%s (no cue in the quoted text)" % e.get("id"))
            continue
        src = ents.get(e.get("source")) or {}
        lab = _norm_text(src.get("label"))
        if lab and re.search(re.escape(lab), q):
            # the label the figure draws is in the sentence: that is the form the claim uses, so it
            # is the form that must sit in subject position (a label edited after the run is caught
            # here even when the geometry is untouched)
            forms = [lab]
        else:
            forms = sorted({_norm_text(f) for f in
                            [src.get("label")] + list(src.get("surfaces") or []) if _norm_text(f)},
                           key=len, reverse=True)
        occ = [(m.start(), m.end()) for f in forms for m in re.finditer(re.escape(f), q)]
        if not occ:
            absent.append((e.get("id"), src.get("label") or e.get("source"),
                           "the sentence it cites never mentions it"))
            continue
        # Subject position, derived from the text alone (the writer's `voice` field is not trusted):
        # in front of the cue, unless the sentence carries passive morphology at that cue
        # (`by` after it, 由/被/受 in front of it) — the pair form `A 与 B 结合` is *not* passive and
        # keeps its subject in front, which is what makes it differ from `B 被 A 结合`.
        clean_before = clean_after = False
        for p in poss:
            passive_here = bool(_BY.search(q[p:p + 60])) or bool(_ZBY.search(q[max(0, p - 40):p + 3]))
            for a, b in occ:
                if b <= p:
                    head = q[max(0, a - 26):a]
                    if not (_OBJE.search(head) or _OBJZ.search(head)):
                        clean_before = True
                elif passive_here and a >= p:
                    clean_after = True
        if not (clean_before or clean_after):
            heads = [q[max(0, a - 26):a] for a, _b in occ]
            objslot.append((e.get("id"), src.get("label") or e.get("source"),
                            "no subject position: it follows '%s'"
                            % (heads[0].strip()[-18:] or "the cue")))
    c("predicate_subject_located", not absent and not (prose and na),
      "edge source(s) that cannot be found in subject position in the sentence they cite: %s%s" % (
          absent[:4], (" | not derivable for: %s" % na[:3]) if na else ""))
    c("predicate_subject_not_in_object_slot", not objslot,
      "%d edge(s) name an entity that sits in an object slot as the subject of the predicate: %s" % (
          len(objslot), objslot[:3]))
    return C


def _locate_material(name, out, input_dir):
    """Find a material file the way the writer would have: input dir, output dir, cwd, parent."""
    cands = []
    for base in (input_dir, os.path.dirname(os.path.abspath(out)), os.getcwd(),
                 os.path.dirname(os.path.dirname(os.path.abspath(out)))):
        if base:
            cands.append(os.path.join(base, name))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def citation_checks(out, res, input_dir):
    """Citations must point at text that was really read: the source must be registered with read
    evidence (bytes/lines/sha256), the file must be locatable, the line must exist, the recorded
    checksum must still match, and the quoted sentence must be in that file.

    The previous version compared ids only, so registering a never-read file (`protocol.md`) and
    citing it passed silently (QA 2026-11-24, P1-3)."""
    import hashlib
    C = []

    def c(cid, okk, det, lvl="error"):
        C.append({"id": "citation." + cid, "ok": bool(okk), "level": lvl, "detail": det})

    sources = {s.get("id"): s for s in res.get("sources") or []}
    res_map = {r.get("path"): r for r in res.get("materials_resolution") or []}
    evs = [(ev, "evidence") for ev in (res.get("evidence") or [])]
    for e in (res.get("entities") or []) + (res.get("edges") or []):
        for ev in (e.get("evidence") or []):
            evs.append((ev, "entity/edge"))
    # 1. every source record must carry read evidence
    no_read = [s.get("id") for s in sources.values()
               if not s.get("bytes") or not s.get("lines") or not s.get("sha256")]
    c("sources_have_read_evidence", not no_read,
      "source(s) registered without bytes/lines/sha256 (i.e. never actually read): %s" % no_read)
    # 2. every source must appear in materials_resolution
    unres = [sid for sid, s in sources.items() if s.get("path") not in res_map]
    c("sources_in_resolution", not unres,
      "source(s) missing from materials_resolution[]: %s" % unres)
    # 3. evidence must exist and name a registered source with a parseable locator
    noev = [e.get("id") for e in (res.get("entities") or []) + (res.get("edges") or [])
            if not (e.get("evidence") or [])]
    c("claims_have_evidence", not noev,
      "%d claim(s) in result.json carry no evidence at all: %s" % (len(noev), noev[:4]))
    missing = sorted({ev.get("source") for ev, _k in evs if ev and ev.get("source") not in sources})
    c("citations_registered", not missing, "citation(s) naming an unregistered source: %s" % missing)
    bad_loc = [(ev.get("source"), ev.get("locator")) for ev, _k in evs
               if not re.search(r"#L\d+$", str(ev.get("locator") or ""))]
    c("citations_have_line_locator", not bad_loc,
      "citation(s) without a `#Lnn` locator: %s" % bad_loc[:4])
    # 4. line numbers must exist in the material, and the file must still hash to what was recorded
    lines_of, mism, past, unreachable, binary = {}, [], [], [], []
    for sid, s in sources.items():
        rel = s.get("path") or ""
        found = _locate_material(rel, out, input_dir)
        if not found:
            unreachable.append(rel)
            continue
        try:
            raw = open(found, "rb").read()
            sha = "sha256:" + hashlib.sha256(raw).hexdigest()
            if s.get("sha256") and sha != s.get("sha256"):
                mism.append(rel)
            if s.get("bytes") and len(raw) != s.get("bytes"):
                mism.append(rel + " (size)")
            text = raw.decode("utf-8", "replace")
            if (s.get("kind") or "").lower() in ("pdf", "docx") or "\x00" in text[:4096]:
                # the writer's line numbers come from an extractor (PyMuPDF / docx XML); this
                # verifier cannot re-extract them without the same library, so line/quote checks are
                # reported as *not applicable* instead of silently passing
                binary.append(rel)
                continue
            lines_of[sid] = (_norm_text(text), max(1, text.count("\n") + 1), text)
        except OSError:
            unreachable.append(rel)
    c("materials_reachable", not unreachable,
      "material(s) not locatable from this run (pass --input <case dir>): %s" % unreachable)
    c("materials_hash_unchanged", not mism,
      "recorded bytes/sha256 differ from the file on disk (material changed after the run): %s" % mism)
    if binary:
        c("binary_material_text_rechecked", False,
          "line/quote of a binary material (PDF/DOCX) cannot be re-derived here without the same "
          "extractor; reachability and checksum were checked: %s" % binary, lvl="warning")
    for ev, _k in evs:
        sid, _, ln = str(ev.get("locator") or "").partition("#L")
        if not sid or not ln.isdigit():
            continue
        if sid in lines_of and int(ln) > lines_of[sid][1]:
            past.append((ev.get("locator"), lines_of[sid][1]))
    c("citation_lines_in_range", not past,
      "locator(s) past the end of the material: %s" % past[:4])
    # 5. the quoted sentence must really be in the material
    forged = []
    for ev, _k in evs:
        sid = str(ev.get("locator") or "").partition("#L")[0]
        q = _norm_text(ev.get("quote") or "")
        if not q or sid not in lines_of:
            continue
        head = q[:40]
        if head and head not in lines_of[sid][0]:
            forged.append((ev.get("locator"), (ev.get("quote") or "")[:60]))
    c("citations_quote_present", not forged,
      "quote(s) not found in the material they cite: %s" % forged[:3])
    # 5b. every quote must be taken from its own sentence: it may not be glued to a Markdown heading
    # line, and the line it names may not be a heading. A heading names the topic; a sentence that
    # starts inside one hands the heading's word to the figure as a subject — that is how
    # `# MAPK1 pathway overview` + `Extracellular EGF binds EGFR.` produced `MAPK1 -> EGFR`
    # (QA 2026-11-24, P0-4). Both halves of the leak are required, so a body sentence that merely
    # begins with the same word as a heading is not accused.
    glued = []
    for ev, _k in evs:
        sid, _, ln = str(ev.get("locator") or "").partition("#L")
        if sid not in lines_of:
            continue
        raw = lines_of[sid][2]
        rawlines = raw.split("\n")
        first = int(ln) - 1 if ln.isdigit() else -1
        if 0 <= first < len(rawlines) and _HEADING.match(rawlines[first]):
            glued.append((ev.get("locator"), "the cited line is a Markdown heading",
                          (ev.get("quote") or "")[:60]))
            continue
        q = _norm_text(ev.get("quote") or "")
        if not q:
            continue
        for h, body in _heading_leaks(raw):
            if q.startswith(h + " ") and q[len(h) + 1:].startswith(body[:30]):
                glued.append((ev.get("locator"), "the quote starts inside heading %r" % h,
                              (ev.get("quote") or "")[:60]))
                break
    c("quote_is_its_own_sentence", not glued,
      "%d quote(s) glued to a Markdown heading line instead of the sentence they claim: %s"
      % (len(glued), glued[:3]))
    # 6. the subject of every predicate must be locatable in the material, in subject position
    C += predicate_subject_checks(res, lines_of)
    err = [x["id"] for x in C if not x["ok"] and x["level"] == "error"]
    warn = [x["id"] for x in C if not x["ok"] and x["level"] == "warning"]
    return {"ok": not err, "n_checks": len(C), "n_errors": len(err), "n_warnings": len(warn),
            "errors": err, "warnings": warn, "checks": C}


def artefact_checks(out, res, svg):
    """Everything here is recomputed from the delivered files; nothing is taken from the writer."""
    C = []

    def c(cid, okk, det, lvl="error"):
        C.append({"id": "artefact." + cid, "ok": bool(okk), "level": lvl, "detail": det})

    groups = [(m.group(1), m.group(2), m.group(3), m.group(4)) for m in re.finditer(
        r'<g class="edge edge-([^"]+)" data-edge-id="([^"]*)" data-edge-type="([^"]+)">(.*?)</g>',
        svg, re.S)]
    nodes = [(m.group(1), m.group(2), m.group(3), m.group(4)) for m in re.finditer(
        r'<g id="([^"]+)" class="node ([^"]+)" data-entity-id="([^"]+)">(.*?)</g>', svg, re.S)]
    node_box = {}
    for nid, ncls, nunused, inner in nodes:
        rects = [(float(a), float(b), float(w), float(h)) for a, b, w, h in re.findall(
            r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"', inner)]
        node_box[nid] = _box(rects)
    c("svg_layers", all('id="layer-%s"' % k in svg for k in
                        ("compartments", "membrane", "edges", "nodes", "legend")),
      "the five named layers are present in the SVG")
    c("no_raster", ("<image" not in svg) and ("data:image" not in svg),
      "the SVG embeds no raster image data (vector-only preview)")
    spec_ents = [e["id"] for e in res.get("entities") or []]
    svg_ents = [n[2] for n in nodes]
    c("node_ids_match", sorted(spec_ents) == sorted(svg_ents),
      "entities in result.json == data-entity-id in the SVG (%d)" % len(svg_ents))
    spec_edges = {e.get("id"): e for e in res.get("edges") or []}
    svg_edges = [g[1] for g in groups]
    c("edge_ids_match", sorted(spec_edges) == sorted(svg_edges),
      "edges in result.json == data-edge-id in the SVG (%d)" % len(svg_edges))
    # one arrow geometry per interaction type, derived from the markup
    by_type = {}
    for etype, eid, etype2, inner in groups:
        by_type.setdefault(etype, set()).add(_prims(inner))
    stable = {t: len(v) == 1 for t, v in by_type.items()}
    c("arrow_geometry_stable", all(stable.values()),
      "every edge type keeps one geometry in the SVG: %s" % (
          "ok" if all(stable.values()) else {t: sorted(v) for t, v in by_type.items() if len(v) > 1}))
    uniq = {t: next(iter(v)) for t, v in by_type.items()}
    c("arrow_geometry_distinct", len(set(uniq.values())) == len(uniq),
      "%d interaction type(s) -> %d distinct geometries: %s" % (
          len(uniq), len(set(uniq.values())), uniq))
    # geometry: the drawn edge must really touch the box of its declared source and its declared
    # target (a mis-wired `<g data-edge-id>` would touch different boxes)
    def dist_to_box(x, y, b):
        dx = max(b[0] - x, 0.0, x - b[2])
        dy = max(b[1] - y, 0.0, y - b[3])
        return (dx * dx + dy * dy) ** 0.5

    off = []
    for etype, eid, etype2, inner in groups:
        e = spec_edges.get(eid) or {}
        pts = [(float(a), float(b)) for a, b in re.findall(r'<line x1="([-\d.]+)" y1="([-\d.]+)"', inner)]
        pts += [(float(a), float(b)) for a, b in re.findall(r'<line[^>]*x2="([-\d.]+)"[^>]*y2="([-\d.]+)"', inner)]
        for pm in re.finditer(r'<(?:polygon|polyline) points="([^"]+)"', inner):
            pts += [(float(a), float(b)) for a, b in re.findall(r"([-\d.]+),([-\d.]+)", pm.group(1))]
        pts += [(float(a), float(b)) for a, b in re.findall(r'<circle cx="([-\d.]+)" cy="([-\d.]+)"', inner)]
        sb, tb = node_box.get(e.get("source")), node_box.get(e.get("target"))
        if not (pts and sb and tb):
            off.append((eid, "no geometry or missing node box"))
            continue
        ds = min(dist_to_box(x, y, sb) for x, y in pts)
        dt = min(dist_to_box(x, y, tb) for x, y in pts)
        if ds > 3.5 or dt > 3.5:
            off.append((eid, "source gap %.1fpx / target gap %.1fpx (declared %s -> %s)"
                        % (ds, dt, e.get("source"), e.get("target"))))
    c("arrow_touches_declared_ends", not off,
      "%d/%d edges touch the boxes of the source and target they declare (%s)" % (
          len(groups) - len(off), len(groups), off[:3]))
    # citations must name a source that was actually read, and never an instruction file
    src_ids = {s.get("id") for s in res.get("sources") or []}
    evs = list(res.get("evidence") or []) + [
        ev for e in (res.get("entities") or []) + (res.get("edges") or []) for ev in (e.get("evidence") or [])]
    bad_src = sorted({ev.get("source") for ev in evs if ev.get("source") not in src_ids})
    c("citations_name_read_sources", not bad_src,
      "%d citation(s) reference a material that is not in sources[]: %s" % (len(bad_src), bad_src))
    instr = {"task.md", "task.txt", "instruction.md", "instructions.md", "prompt.md", "rubric.md"}
    read_instr = sorted({s.get("path") for s in res.get("sources") or []
                         if (s.get("path") or "").lower() in instr})
    c("instructions_not_material", not read_instr,
      "no work-order/instruction file was read as biological material: %s" % read_instr)
    # a case descriptor may be a *declared work order* (structured input) and is then named as a
    # source on purpose; it must never be cited when the graph came from prose extraction
    structured = "structured" in (res.get("graph_source") or "").lower()
    desc = [s.get("path") for s in res.get("sources") or []
            if (s.get("path") or "").lower() in ("case.json", "case.yaml", "case.yml")]
    c("descriptor_only_when_structured", structured or not desc,
      "graph_source=%r, descriptor used as a source: %s" % (res.get("graph_source"), desc))
    # the reported export format must match what is on disk
    claimed = {d.get("format") for d in res.get("deliverables") or []}
    files_on_disk = {f for f in os.listdir(out) if os.path.isfile(os.path.join(out, f))}
    exts = {f.split(".")[-1] for f in files_on_disk}
    c("export_claim_honest", claimed <= (exts | {"svg"}),
      "declared formats %s vs artefacts on disk %s" % (sorted(claimed), sorted(files_on_disk)))
    c("raster_claim_honest", bool((res.get("exports") or {}).get("raster", {}).get("produced", False))
      == any(f in files_on_disk for f in ("figure.png", "figure.pdf")),
      "exports.raster.produced matches the presence of a raster/PDF file (%s)"
      % sorted(f for f in files_on_disk if f.startswith("figure.")))
    con = res.get("output_contract") or {}
    missing = [k for k in con if k not in res]
    c("contract_echoed", not missing, "%d contract key(s) echoed, missing: %s" % (len(con), missing))
    # ---- exports: measured from the bytes on disk, not from what result.json says about them ----
    import hashlib

    def sha(p):
        return "sha256:" + hashlib.sha256(open(p, "rb").read()).hexdigest()

    m = re.search(r'<svg[^>]*\bwidth="([\d.]+)"[^>]*\bheight="([\d.]+)"', svg)
    canvas = [float(m.group(1)), float(m.group(2))] if m else []
    ex = res.get("exports") or {}
    pdf_path, png_path = os.path.join(out, "figure.pdf"), os.path.join(out, "figure.png")
    # PDF: page box, vector-only, real text operators
    pdf_ok, pdf_det = os.path.isfile(pdf_path), "figure.pdf missing"
    if pdf_ok:
        raw = open(pdf_path, "rb").read()
        mb = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", raw)
        box = [float(mb.group(1)), float(mb.group(2))] if mb else []
        content = b""
        for mm in re.finditer(rb"stream\r?\n", raw):
            end = raw.find(b"endstream", mm.end())
            if end > 0:
                content += raw[mm.end():end]
        text_ops = len(re.findall(rb"\bT[jJ]\b", content))
        images = len(re.findall(rb"/Subtype\s*/Image", raw))
        pages = len(re.findall(rb"/Type\s*/Page\b", raw))
        pdf_det = "page=%s canvas=%s vector=%s text_ops=%d pages=%d" % (
            box, canvas, images == 0, text_ops, pages)
        c("pdf_page_is_the_figure_box", bool(box) and bool(canvas) and
          abs(box[0] - canvas[0]) < 0.6 and abs(box[1] - canvas[1]) < 0.6, pdf_det)
        c("pdf_is_vector", images == 0, "%d image xobject(s) in the PDF" % images)
        c("pdf_text_is_selectable", text_ops > 0, "%d text-showing operator(s)" % text_ops)
        c("pdf_export_record_matches_bytes",
          (ex.get("pdf") or {}).get("bytes") == len(raw) and
          (ex.get("pdf") or {}).get("sha256") == sha(pdf_path),
          "recorded %s B / %s" % ((ex.get("pdf") or {}).get("bytes"), len(raw)))
    else:
        c("pdf_page_is_the_figure_box", False, pdf_det)
    # PNG: pixel size must be the page box at the dpi stored in pHYs
    if os.path.isfile(png_path):
        raw = open(png_path, "rb").read()
        w = h = dpi = None
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            i = 8
            while i + 8 <= len(raw):
                ln = int.from_bytes(raw[i:i + 4], "big")
                typ = raw[i + 4:i + 8]
                data = raw[i + 8:i + 8 + ln]
                if typ == b"IHDR":
                    w, h = int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big")
                elif typ == b"pHYs":
                    dpi = round(int.from_bytes(data[0:4], "big") * 0.0254, 1)
                i += 12 + ln
        want = [int(round(canvas[0] * dpi / 72.0)), int(round(canvas[1] * dpi / 72.0))] if canvas and dpi else []
        c("png_pixels_match_page_and_dpi",
          bool(want) and abs(w - want[0]) <= 1 and abs(h - want[1]) <= 1,
          "IHDR %sx%s, pHYs %s dpi, expected %s px (±1 px: renderers round differently)" % (w, h, dpi, want))
        c("png_export_record_matches_bytes",
          (ex.get("png") or {}).get("bytes") == len(raw) and
          (ex.get("png") or {}).get("sha256") == sha(png_path),
          "recorded %s B / %s" % ((ex.get("png") or {}).get("bytes"), len(raw)))
        c("png_dpi_is_declared", (ex.get("png") or {}).get("dpi_requested") == dpi,
          "requested %s, pHYs says %s" % ((ex.get("png") or {}).get("dpi_requested"), dpi))
    else:
        c("png_pixels_match_page_and_dpi", False, "figure.png missing")
    c("deliverable_formats_on_disk",
      {"svg", "pdf", "png"} <= {d.get("format") for d in res.get("deliverables") or []} and
      all(os.path.isfile(os.path.join(out, f)) for f in ("figure.svg", "figure.pdf", "figure.png")),
      "declared formats %s" % sorted({d.get("format") for d in res.get("deliverables") or []}))
    err = [x["id"] for x in C if not x["ok"] and x["level"] == "error"]
    warn = [x["id"] for x in C if not x["ok"] and x["level"] == "warning"]
    return {"ok": not err, "n_checks": len(C), "n_errors": len(err), "n_warnings": len(warn),
            "errors": err, "warnings": warn, "checks": C}


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
    c("semantics.distinct", all(len(v) == 1 for v in sig.values()), "one arrow shape per interaction type")
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
    ap.add_argument("--input", default="/input",
                    help="where the case materials live, so citations can be re-checked against the "
                         "text that was actually read (default /input, as in the runtime contract)")
    ap.add_argument("--case", default="", help="case.json; its directory is searched for materials")
    a = ap.parse_args(argv)
    input_dir = a.input
    if a.case and os.path.isfile(a.case):
        input_dir = os.path.dirname(os.path.abspath(a.case))
    specp = os.path.join(a.out, "spec.json")
    if not os.path.isfile(specp):
        print("verify: nothing to check in %s: spec.json is missing.\n"
              "        run `python3 scripts/pathway.py --case <case.json> --out %s` first."
              % (a.out, a.out))
        return 2
    spec = json.load(open(specp, encoding="utf-8"))
    res = json.load(open(os.path.join(a.out, "result.json"), encoding="utf-8")) if \
        os.path.exists(os.path.join(a.out, "result.json")) else {}
    svg = open(os.path.join(a.out, "figure.svg"), encoding="utf-8").read() if \
        os.path.exists(os.path.join(a.out, "figure.svg")) else ""
    box = {}
    lay = {"box": box}
    for e in spec["entities"]:
        x = (e.get("layout") or {}).get("x")
        if x is not None:
            box[e["id"]] = (x, 0, x + 1, 0)
    if not box:                      # fall back: geometry from the SVG node groups
        for m in re.finditer(r'<g id="(E\d+)"[^>]*>.*?<rect x="([-\d.]+)"', svg, re.S):
            box[m.group(1)] = (float(m.group(2)), 0, float(m.group(2)) + 1, 0)
    rep = checks(spec, lay)
    art = artefact_checks(a.out, res, svg) if svg else {
        "ok": False, "n_checks": 0, "n_errors": 1, "n_warnings": 0,
        "errors": ["artefact.svg_missing"], "checks": [
            {"id": "artefact.svg_missing", "ok": False, "level": "error",
             "detail": "figure.svg was not written: nothing can be re-derived"}]}
    rep["independence"] = {"spec_level": "reads spec.json/result.json on disk; shares the grammar table "
                                         "with the writer, so it is necessary but not sufficient",
                           "artefact_level": "reads figure.svg + figure.pdf + figure.png + result.json "
                                             "only and re-derives ids, arrow geometry, arrow endpoints, "
                                             "export claims and the citation index",
                           "citation_level": "re-opens the material files (--input / --case) and checks "
                                             "that each cited line exists, the recorded bytes/sha256 "
                                             "still match, and the quoted sentence is really in the "
                                             "text",
                           "material_dir": input_dir,
                           "used_intermediate_spec": False}
    rep["artefact"] = art
    cit = citation_checks(a.out, res, input_dir) if res else {
        "ok": False, "n_checks": 0, "n_errors": 1,
        "errors": ["citation.result_missing"], "checks": [
            {"id": "citation.result_missing", "ok": False, "level": "error",
             "detail": "result.json was not written: the citation index cannot be checked"}]}
    rep["citation"] = cit
    rep["ok"] = bool(rep["ok"] and art["ok"] and cit["ok"])
    rep["n_checks"] = rep["n_checks"] + art["n_checks"] + cit["n_checks"]
    rep["n_errors"] = rep["n_errors"] + art["n_errors"] + cit["n_errors"]
    rep["n_warnings"] = rep["n_warnings"] + art["n_warnings"]
    files = {f: os.path.getsize(os.path.join(a.out, f)) for f in
             ("figure.svg", "figure.pdf", "figure.png", "result.json", "check-report.json")
             if os.path.exists(os.path.join(a.out, f))}
    rep["files"] = files
    rep["result_status"] = res.get("status")
    json.dump(rep, open(os.path.join(a.out, "verify-report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("verify: %d checks (%d spec + %d artefact + %d citation), %d errors, %d warnings -> %s" %
          (rep["n_checks"], rep["n_checks"] - art["n_checks"] - cit["n_checks"], art["n_checks"],
           cit["n_checks"], rep["n_errors"], rep["n_warnings"], "PASS" if rep["ok"] else "FAIL"))
    for c in rep["checks"] + art["checks"] + cit["checks"]:
        if not c["ok"]:
            print("  [%s] %s - %s" % (c["level"], c["id"], c["detail"]))
    print("files : %s" % ", ".join("%s=%dB" % kv for kv in files.items()))
    print("materials checked against: %s" % input_dir)
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
