#!/usr/bin/env python3
"""Minimal scientific schematic skill: case + material -> editable SVG + result.json.

    python scripts/schematic.py --case /input/case.json --out /app/output

Stdlib only, no network, no LLM. The figure model is the source of truth; every
entity, relation and data mark carries the locator and the verbatim quote it came
from. Polarity is re-derived from the quote (an inhibition drawn as an activation
is a blocking error) and a data column the model names but the table lacks is a
blocking error, never a silent substitution. Failures degrade to status=partial +
gaps/uncertainty and still write what they produced. The SVG is both the editable
source and the vector export (PDF/PNG are out of scope in this minimal build).
"""
import argparse, copy, csv, json, os, re, sys, time, hashlib

sys.dont_write_bytecode = True
P = 72.0 / 25.4  # mm -> pt: SVG user units are pt, the page size is mm
REL = {"activation": ("Activates", "arrow"), "inhibition": ("Inhibits", "tee"),
       "binding": ("Binds (no direction)", "line"), "transport": ("Transports", "dash"),
       "modification": ("Modifies", "open"), "sequence": ("Then (order)", "step"),
       "inclusion": ("Contains", "nested"), "unknown": ("Unclear", "q")}
VB = {"activation": "activate activates induced induce induces promote promotes drive drives trigger stimulates upregulate increases enhances stabilizes transcribes",
      "inhibition": "inhibit inhibits inhibited suppress suppresses repress blocks block prevents reduce reduces decrease decreases downregulate degrades sequesters impairs",
      "binding": "bind binds bound interact interacts associate associates complex",
      "transport": "translocate translocates transport transports imports export exports secretes releases",
      "modification": "phosphorylate phosphorylates ubiquitinate methylate acetylate cleaves", "sequence": "then subsequently finally"}
V2R = {v: r for r, vs in VB.items() for v in vs.split()}
PAL = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
TXT = (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".rst", ".html", ".xml")
BIN = (".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".tif", ".zip")
FONT = "Helvetica, Arial, 'DejaVu Sans', sans-serif"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def nm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def r3(v):
    return f"{round(float(v), 3):g}"


def tw(s, fp):
    return sum(.55 if ord(c) < 0x2E80 else 1. for c in str(s)) * fp * .3528


def A(**kw):
    return "".join(f' {k.rstrip("_").replace("_", "-")}="{esc(v)}"' for k, v in kw.items() if v not in (None, ""))


def E(F, c, m, s="error"):
    F.append({"check": c, "severity": s, "message": m})


def jload(p):
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def material(md, notes):
    """Read every text file. A binary/office file is reported, never guessed."""
    files, txt = [], []
    if not md or not os.path.isdir(md):
        notes.append({"item": "material", "why": f"material directory not found: {md or '(none)'}",
                      "handling": "built from the model only; quotes cannot be verified"})
        return {"files": [], "text": "", "by_name": {}}
    for n in sorted(os.listdir(md)):
        p, e = os.path.join(md, n), os.path.splitext(n)[1].lower()
        if not os.path.isfile(p):
            continue
        r = {"rel": n, "bytes": os.path.getsize(p), "readable": e in TXT}
        if e in BIN:
            r["note"] = "binary/office format: this minimal skill reads text only and does not guess content"
            notes.append({"item": f"material {n}", "why": r["note"], "handling": "not read; see not_reported"})
        elif e not in TXT:
            r["note"] = "unsupported extension"
        else:
            with open(p, encoding="utf-8-sig", errors="replace") as fh:
                txt.append((n, fh.read()))
        files.append(r)
    return {"files": files, "text": nm(" \n ".join(t for _n, t in txt)), "by_name": {n: nm(t) for n, t in txt}}


def find_spec(case, cp, md, case_dir=""):
    """Resolve a declared model against case.json's directory first, never the cwd first."""
    def pick(value):
        for base in (case_dir, md, os.getcwd(), "/input"):
            if base and isinstance(value, str):
                c = os.path.join(base, value)
                if os.path.exists(c):
                    return c
        return value if isinstance(value, str) and os.path.exists(value) else ""
    for k in ("figure_spec", "spec", "figure_spec_path", "spec_path"):
        v = case.get(k)
        if isinstance(v, str):
            c = pick(v)
            if c:
                return c, f"case.{k}"
    for root in (case_dir, md, os.getcwd()):
        if root and os.path.isdir(root):
            n = next((x for x in sorted(os.listdir(root))
                      if re.search(r"(figure|chart|spec).*\.json$", x, re.I)
                      and not re.search(r"checks|result|used|edited|report|provenance|"
                                        r"geometry|prims|draft", x, re.I)), None)
            if n:
                return os.path.join(root, n), f"discovered:{n}"
    return "", ""


def find_table(md, case_dir):
    """Find a CSV/TSV in the material and infer its role columns - no spec needed.

    Purely heuristic: numeric-looking columns become value/error candidates, the rest
    become category/series candidates, guided by common names when they match.
    """
    cands = []
    for root in (md, os.path.join(md or "", "materials"), case_dir):
        if root and os.path.isdir(root):
            cands += [os.path.join(root, n) for n in sorted(os.listdir(root))
                      if os.path.splitext(n)[1].lower() in (".csv", ".tsv")]
    if not cands:
        return "", {}
    path = cands[0]
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        txt = fh.read(8192)
        fh.seek(0)
        try:
            dl = csv.Sniffer().sniff(txt, delimiters=",;\t") if txt.strip() else csv.excel
        except Exception:
            dl = csv.excel
        rows = [r for r in csv.reader(fh, dl) if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        return "", {}
    head, body = [str(c).strip() for c in rows[0]], rows[1:]

    def isnum(v):
        try:
            float(str(v).replace(",", ".").strip())
            return True
        except Exception:
            return False

    num = [h for i, h in enumerate(head)
           if sum(1 for r in body if i < len(r) and isnum(r[i])) >= max(1, len(body) // 2)]
    txt_cols = [h for h in head if h not in num]
    val = next((h for h in num if re.search(r"value|mean|expr|level|activity|rate|fold|值|表达|水平", h, re.I)),
               num[0] if num else "")
    if not val:
        return "", {}
    cat = next((h for h in txt_cols
                if re.search(r"time|condition|category|group|treat|阶段|时间|条件|分组", h, re.I)),
               txt_cols[0] if txt_cols else "")
    ser = next((h for h in txt_cols if h != cat
                and re.search(r"gene|series|probe|sample|strain|基因|系列|样本", h, re.I)),
               next((h for h in txt_cols if h != cat), ""))
    err = next((h for h in num if h != val
                and re.search(r"^(sd|sem|se|std|stdev|error|ci)$|误差|标准差", h, re.I)), "")
    return path, {"category_column": cat or None, "series_column": ser or None,
                  "value_column": val, "error_column": err or None}


def draft(corpus, title):
    """Last-resort model mined from the material; every element is marked uncertain."""
    ns, es, seen = [], [], {}
    read = [(f.get("rel") or "", f.get("text") or "") for f in (corpus.get("files") or [])
            if f.get("readable")]

    def src_of(raw):
        """Which material file this sentence came from, so the SVG keeps a locator."""
        for cand in (nm(raw)[:200], nm(raw)[:60], raw.strip()):
            for rel, txt in read:
                if cand and txt and cand in txt:
                    return rel
        return read[0][0] if len(read) == 1 else ""
    for cl in re.split(r"(?<=[.;!?])\s+", corpus.get("text") or ""):
        f = [x for x in re.findall(r"\b[A-Z][A-Z0-9]{1,6}\b", cl) if x not in ("DNA", "RNA", "EXAMPLE")]
        v = next((w for w in re.split(r"[^a-z]+", cl.lower()) if w in V2R), None)
        if len(f) < 2 or not v or f[0] == f[1]:
            continue
        for tok in (f[0], f[1]):
            if tok not in seen:
                seen[tok] = {"id": f"n{len(seen)+1}", "label": tok, "kind": "entity", "uncertain": True,
                             "evidence": [{"source": src_of(cl), "quote": nm(cl)[:200]}]}
                ns.append(seen[tok])
        es.append({"id": f"e{len(es)+1}", "source": seen[f[0]]["id"], "target": seen[f[1]]["id"], "relation": V2R[v],
                   "uncertain": True, "evidence": [{"source": src_of(cl), "quote": nm(cl)[:200]}]})
    return None if not es else {"_status": "DRAFT mined from the material; every element is uncertain and must be reviewed",
                                "figure_type": "mechanism", "title": title or "Draft entity-relation view (needs review)",
                                "canvas": {"width_mm": 180, "margin_mm": 7, "font_pt": 7.5, "line_pt": .9},
                                "nodes": ns, "edges": es, "uncertain": True}


def data_of(spec, md, cp, notes, F):
    """Table -> categories/series/values. A named-but-missing column is a blocking error."""
    d = spec.get("data") or {}
    rel = d.get("table") or d.get("path")
    if not rel:
        return None
    b = os.path.basename(rel)
    path = next((c for c in (rel, os.path.join(md or "", rel), os.path.join(md or "", "materials", b),
                             os.path.join(md or "", b), os.path.join(os.path.dirname(cp or "."), rel)) if os.path.isfile(c)), "")
    if not path:
        E(F, "data_table_missing", f"data table '{rel}' was not found next to the case or the material")
        return None
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        s = fh.read(8192); fh.seek(0)
        try:
            dl = csv.Sniffer().sniff(s, delimiters=",;\t") if s.strip() else csv.excel
        except Exception:
            dl = csv.excel
        rows = [r for r in csv.reader(fh, dl) if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        E(F, "data_table_unreadable", f"no rows could be read from {b}")
        return None
    head, role = [str(c).strip() for c in rows[0]], {}
    for r, ks in (("category", ("category_column", "x_column")), ("series", ("series_column",)),
                  ("value", ("value_column", "y_column")), ("error", ("error_column", "sd_column"))):
        role[r] = next((d[k] for k in ks if d.get(k)), None)
        if role[r] and role[r] not in head:
            E(F, "data_column_missing", f"data.{r}_column='{role[r]}' is not in the table header {head}; "
                                        "this skill refuses to substitute another column")
            return None
    if not role["value"]:
        role["value"] = next((h for h in head if re.search(r"value|mean|expr|level|activity|rate|fold|均值|数值|表达|水平", h, re.I)), head[-1])
        notes.append({"item": "data.value_column", "why": "the model did not name a value column",
                      "handling": f"'{role['value']}' was chosen by heuristic; confirm it"})
    role["category"] = role["category"] or head[0]
    ix, rec = {h: i for i, h in enumerate(head)}, []
    for r in rows[1:]:
        def num(k):
            try:
                return float(str(r[ix[role[k]]]).replace(",", ".").strip()) if role[k] and role[k] in ix else None
            except Exception:
                return None
        v = num("value")
        if v is None:
            continue
        er = num("error")
        rec.append({"category": str(r[ix[role["category"]]]).strip() if role["category"] in ix else "",
                    "series": str(r[ix[role["series"]]]).strip() if role["series"] and role["series"] in ix else "value",
                    "value": v, "error": abs(er) if er is not None else None})
    if not rec:
        E(F, "data_no_numeric_rows", f"no numeric value rows in {b}")
        return None
    cats, sers = [], []
    for r in rec:
        cats += [r["category"]] if r["category"] not in cats else []
        sers += [r["series"]] if r["series"] not in sers else []
    return {"rel": b, "rows": len(rec), "category_column": role["category"], "series_column": role["series"],
            "value_column": role["value"], "error_column": role["error"], "unit": d.get("value_unit") or "",
            "categories": cats, "series": sers, "records": rec, "colors": {s: PAL[i % len(PAL)] for i, s in enumerate(sers)},
            "vmax": max(r["value"] + (r["error"] or 0) for r in rec) or 1.}


def check_model(spec, corpus, F):
    """Structure, relation vocabulary, polarity (blocking) and entity spelling (warning)."""
    ns, es = spec.get("nodes") or [], spec.get("edges") or []
    if not ns and not (spec.get("data") or {}).get("table"):
        return E(F, "no_entities", "the model has no entities: nothing can be drawn without inventing content")
    ids, t = [n.get("id") for n in ns], (corpus.get("text") or "").lower()
    known, lab = set(ids), {n["id"]: nm(n.get("label")) for n in ns}
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        E(F, "duplicate_ids", f"duplicate entity id {d!r}")
    for e in es:
        if e.get("source") not in known or e.get("target") not in known:
            E(F, "edge_dangling", f"edge {e.get('id')!r} points at an entity not in the model")
        if e.get("relation") not in REL:
            E(F, "relation_not_in_vocabulary", f"edge {e.get('id')!r} uses {e.get('relation')!r}, not in {sorted(REL)}")
        qs = [nm(q.get("quote")) for q in (e.get("evidence") or []) if q.get("quote")]
        if not qs:
            E(F, "edge_without_evidence", f"edge {e.get('id')!r} has no evidence sentence; its direction cannot be re-derived", "warn")
            continue
        verb = next((w for w in re.split(r"[^a-z]+", qs[0].lower()) if w in V2R), None)
        dec, found = e.get("relation"), V2R.get(verb)
        if dec in ("activation", "inhibition") and found in ("activation", "inhibition") and found != dec:
            E(F, "polarity_inverted", f"edge {e.get('id')!r} is drawn as {dec} but the quoted sentence says '{verb}' "
                                      f"({found}): {qs[0][:110]}")
    for n in ns:
        la = nm(n.get("label"))
        if not t or la.lower() in t or any(nm(a).lower() in t for a in (n.get("aliases") or [])):
            continue
        miss = [w for w in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", la) if len(w) >= 3 and w.lower() not in t]
        if miss:
            E(F, "entity_unverified", f"entity {n.get('id')!r} label {la!r} contains {miss}, which does not occur verbatim "
                                      "in the material; spell it as the source does or add an alias", "warn")


def verify(spec, corpus):
    """Verbatim lookup of every quoted sentence, so each element can be traced back."""
    rows, by, joined = [], corpus.get("by_name") or {}, corpus.get("text") or ""
    for kind, items in (("node", spec.get("nodes") or []), ("edge", spec.get("edges") or []),
                        ("figure", [spec] if spec.get("evidence") else [])):
        for it in items:
            for ev in (it.get("evidence") or []):
                q = nm(ev.get("quote"))
                if not q:
                    continue
                hay = by.get(ev.get("source")) or joined
                pos = hay.find(q)
                rows.append({"element_id": it.get("id"), "element_type": kind, "label": it.get("label") or "",
                             "relation": it.get("relation") or "", "declared_source": ev.get("source") or "", "quote": q,
                             "verified": pos >= 0, "locator": f"{ev.get('source') or 'material'}#char{pos}" if pos >= 0 else "not-found",
                             "occurrences": hay.count(q) if pos >= 0 else 0})
    ok = sum(1 for r in rows if r["verified"])
    return rows, {"quotes": len(rows), "verified": ok, "rate": round(ok / len(rows), 3) if rows else None}


def layout(spec, d, notes):
    """Deterministic grid layout in mm; data is encoded as a bar strip below it."""
    cv = spec.get("canvas") or {}
    W, m = float(cv.get("width_mm") or 180), float(cv.get("margin_mm") or 7)
    fp, lp = float(cv.get("font_pt") or 7.5), float(cv.get("line_pt") or .9)
    ns, es = list(spec.get("nodes") or []), list(spec.get("edges") or [])
    title = nm(spec.get("title"))
    # order entities by compartment so the vertical flow reads top-down
    order, grp = [], {}
    for n in ns:
        b = n.get("band") or n.get("compartment") or "main"
        grp.setdefault(b, [])
        if b not in order:
            order.append(b)
        grp[b].append(n)
    seq = [n for b in order for n in grp[b]]
    y = m + (fp * 1.6 * .3528 + 3. if title else 0.)
    cols, nh, gx, gy, pad, iw = 4, 12., 6., 8., 3., W - 2 * m
    bw = (iw - 2 * pad - (cols - 1) * gx) / cols
    for i, n in enumerate(seq):
        rr, cc = divmod(i, cols)
        n.update(_x=m + pad + cc * (bw + gx), _y=y + pad + rr * (nh + gy), _w=bw, _h=nh)
    if seq:  # a chart-only model has no entity grid to advance past
        rowsn = (len(seq) + cols - 1) // cols
        y += 2 * pad + rowsn * nh + (rowsn - 1) * gy
    strip = None
    if d:  # data encoding: one bar per (category, series) with value labels
        h = 26.
        strip = {"x": m, "y": y + 5., "base": y + 5. + h - 6., "h": h, "gw": iw / max(1, len(d["categories"])), "bars": []}
        slot = strip["gw"] * .7 / max(1, len(d["series"]))
        for r in d["records"]:
            ci, si = d["categories"].index(r["category"]), d["series"].index(r["series"])
            bh = r["value"] / d["vmax"] * (h - 12.)
            strip["bars"].append({"x": strip["x"] + strip["gw"] * ci + (strip["gw"] - slot * len(d["series"])) / 2 + slot * si,
                                  "y": strip["base"] - bh, "w": slot * .82, "h": bh, "value": r["value"], "error": r["error"],
                                  "series": r["series"], "category": r["category"], "color": d["colors"][r["series"]]})
        y = strip["y"] + h
    legend, x = [], m
    keys = [(r, REL[r][1], None) for r in dict.fromkeys(e.get("relation") for e in es) if r in REL]
    keys += [(s, "swatch", d["colors"][s]) for s in (d or {}).get("series", [])]
    for k, gly, col in keys:
        lab = k if gly == "swatch" else REL[k][0]
        legend.append({"key": k, "label": lab, "glyph": gly, "color": col, "x": x, "y": y + 7.})
        x += (8. if gly == "swatch" else 13.5) + tw(lab, fp * .95) + 7.
    H = (y + 7. + fp * .95 * .3528 + 3. if legend else y) + m
    by = {n.get("id"): n for n in ns}
    routes = []
    for e in es:
        s, t = by.get(e.get("source")), by.get(e.get("target"))
        if not s or not t:
            continue
        sc, tc = (s["_x"] + s["_w"] / 2, s["_y"] + s["_h"] / 2), (t["_x"] + t["_w"] / 2, t["_y"] + t["_h"] / 2)
        dx, dy = tc[0] - sc[0], tc[1] - sc[1]
        k = min((s["_w"] / 2) / abs(dx) if dx else 9e9, (s["_h"] / 2) / abs(dy) if dy else 9e9)
        k2 = min((t["_w"] / 2) / abs(dx) if dx else 9e9, (t["_h"] / 2) / abs(dy) if dy else 9e9)
        rel, ev = (e.get("relation") if e.get("relation") in REL else "unknown"), (e.get("evidence") or [])
        routes.append({"id": e.get("id"), "source": e.get("source"), "target": e.get("target"), "relation": rel,
                       "glyph": REL[rel][1], "x1": sc[0] + dx * k, "y1": sc[1] + dy * k, "x2": tc[0] - dx * k2,
                       "y2": tc[1] - dy * k2, "src": (ev[0].get("source") if ev else "") or "",
                       "quote": (ev[0].get("quote") if ev else "") or ""})
    cvs = {"width_mm": round(W, 2), "height_mm": round(H, 2), "margin_mm": m, "font_pt": fp, "line_pt": lp}
    if cv.get("height_mm") and abs(float(cv["height_mm"]) - H) > 1:
        notes.append({"item": "canvas height", "why": f"requested height_mm {cv['height_mm']} did not fit the content",
                      "handling": f"the canvas grew to {round(H,1)} mm so nothing overlaps"})
    return {"canvas": cvs, "nodes": seq, "edges": routes, "legend": legend, "strip": strip, "title": title,
            "title_y": m + fp * 1.1 * .3528}


def head(rel, x, y, dx, dy, lp):
    """Glyph at the target end: filled arrow / T-bar / open arrow / '?' when unresolved."""
    L = (dx * dx + dy * dy) ** .5 or 1.
    ux, uy, px, py, g = dx / L, dy / L, -dy / L, dx / L, REL[rel][1]
    s, w = max(2., lp * 3.), max(2., lp * 3.) * .55
    if g in ("arrow", "open", "dash"):
        return [f'<polygon points="{r3(x*P)},{r3(y*P)} {r3((x-ux*s+px*w)*P)},{r3((y-uy*s+py*w)*P)} '
                f'{r3((x-ux*s-px*w)*P)},{r3((y-uy*s-py*w)*P)}" fill="{"#111" if g=="arrow" else "#fff"}" '
                f'stroke="#111" stroke-width="{r3(lp*.7)}"/>']
    if g == "tee":
        return [f'<line x1="{r3((x+px*w)*P)}" y1="{r3((y+py*w)*P)}" x2="{r3((x-px*w)*P)}" y2="{r3((y-py*w)*P)}" '
                f'stroke="#111" stroke-width="{r3(lp*1.4)}"{A(data_glyph="tee-bar")}/>']
    if g == "q":
        return [f'<text x="{r3((x-ux*s*2.5)*P)}" y="{r3((y-uy*s*2.5)*P)}" font-family="{FONT}" '
                f'font-size="{r3(max(4.,lp*3.4))}" text-anchor="middle" font-weight="bold" fill="#111">?</text>']
    return []


def render(g, d):
    cv, fp, lp = g["canvas"], g["canvas"]["font_pt"], g["canvas"]["line_pt"]
    W, H = cv["width_mm"] * P, cv["height_mm"] * P
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{r3(cv["width_mm"])}mm" '
         f'height="{r3(cv["height_mm"])}mm" viewBox="0 0 {r3(W)} {r3(H)}" data-units="pt">',
         f'<title>{esc(g["title"] or "scientific schematic")}</title>',
         "<desc>Layered editable SVG: entities, edges and data marks carry id + data-source; all text is real "
         "&lt;text&gt; and stays selectable/editable.</desc>"]

    def tx(x, y, s, f, anchor="middle", weight="normal", fill="#111", **a):
        o.append(f'<text x="{r3(x*P)}" y="{r3(y*P)}" font-family="{FONT}" font-size="{r3(f)}" text-anchor="{anchor}" '
                 f'font-weight="{weight}" fill="{fill}" data-font-pt="{r3(f)}"{A(**a)}>{esc(s)}</text>')

    def fit(s, mx, f):  # single-line label, truncated if it cannot fit the box
        s = str(s)
        while s and tw(s, f) > mx:
            s = s[:-2]
        return s
    o.append('<g id="layer-nodes" data-layer="nodes">')
    for n in g["nodes"]:
        ev = n.get("evidence") or []
        o.append(f'<g id="node-{esc(n["id"])}"{A(data_entity=n.get("label"), data_kind=n.get("kind") or "",
                                                 data_band=n.get("band") or n.get("compartment") or "main",
                                                 data_source=(ev[0].get("source") if ev else "") or "",
                                                 data_quote=(ev[0].get("quote") if ev else "") or "")}>'
                 f'<rect x="{r3(n["_x"]*P)}" y="{r3(n["_y"]*P)}" width="{r3(n["_w"]*P)}" height="{r3(n["_h"]*P)}" '
                 f'rx="1.6" fill="#F5F7FA" stroke="#33475B" stroke-width="{r3(lp)}"/></g>')
        tx(n["_x"] + n["_w"] / 2, n["_y"] + n["_h"] / 2 + fp * .35, fit(n.get("label"), n["_w"] - 2., fp), fp)
    o.append('</g><g id="layer-edges" data-layer="edges">')
    for e in g["edges"]:
        o.append(f'<g id="edge-{esc(e["id"])}"{A(data_relation=e["relation"], data_glyph=e["glyph"],
                                                 data_source=e["src"], data_quote=e["quote"])}>')
        if e["glyph"] == "nested":
            t = next((n for n in g["nodes"] if n.get("id") == e["target"]), None)
            if t:
                o.append(f'<rect x="{r3((t["_x"]-1.2)*P)}" y="{r3((t["_y"]-1.2)*P)}" width="{r3((t["_w"]+2.4)*P)}" '
                         f'height="{r3((t["_h"]+2.4)*P)}" fill="none" stroke="#666" stroke-width="{r3(lp)}" '
                         f'stroke-dasharray="2.5 1.8" rx="1.6"/>')
        else:
            o.append(f'<line x1="{r3(e["x1"]*P)}" y1="{r3(e["y1"]*P)}" x2="{r3(e["x2"]*P)}" y2="{r3(e["y2"]*P)}" '
                     f'stroke="#111" stroke-width="{r3(lp)}" fill="none"'
                     + (' stroke-dasharray="2.5 1.8"' if e["glyph"] in ("dash", "q") else "") + "/>")
            o += head(e["relation"], e["x2"], e["y2"], e["x2"] - e["x1"], e["y2"] - e["y1"], lp)
        o.append("</g>")
    o.append("</g>")
    if g["strip"]:
        s, u = g["strip"], (g["strip"]["h"] - 12.) / d["vmax"]
        o.append(f'<g id="layer-data" data-layer="data"><line x1="{r3(s["x"]*P)}" y1="{r3(s["base"]*P)}" '
                 f'x2="{r3((s["x"]+s["gw"]*len(d["categories"]))*P)}" y2="{r3(s["base"]*P)}" stroke="#111" '
                 f'stroke-width="{r3(lp)}"/>')
        for b in s["bars"]:
            o.append(f'<g id="mark-{esc(b["category"])}-{esc(b["series"])}"'
                     f'{A(data_category=b["category"], data_series=b["series"], data_value=f"{b["value"]:g}",
                          data_error="" if b["error"] is None else f"{b["error"]:g}", data_source=d["rel"])}>'
                     f'<rect x="{r3(b["x"]*P)}" y="{r3(b["y"]*P)}" width="{r3(b["w"]*P)}" height="{r3(max(0.,b["h"])*P)}" '
                     f'fill="{b["color"]}" stroke="{b["color"]}" stroke-width="{r3(lp*.8)}"/>'
                     + (f'<line x1="{r3((b["x"]+b["w"]/2)*P)}" y1="{r3((s["base"]-(b["value"]-b["error"])*u)*P)}" '
                        f'x2="{r3((b["x"]+b["w"]/2)*P)}" y2="{r3((s["base"]-(b["value"]+b["error"])*u)*P)}" stroke="#111" '
                        f'stroke-width="{r3(lp*.8)}"{A(data_role="error-bar")}/>' if b["error"] else "") + "</g>")
            tx(b["x"] + b["w"] / 2, b["y"] - 1., f'{b["value"]:g}', fp * .85)
        for i, c in enumerate(d["categories"]):
            tx(s["x"] + s["gw"] * (i + .5), s["base"] + 4., c, fp * .9, data_category=c)
        o.append("</g>")
    o.append('<g id="layer-legend" data-layer="legend">')
    for it in g["legend"]:
        if it["glyph"] == "swatch":
            o.append(f'<g{A(data_legend_item=it["key"])}><rect x="{r3(it["x"]*P)}" y="{r3((it["y"]-fp*.8)*P)}" '
                     f'width="{r3(3.6*P)}" height="{r3(3.*P)}" fill="{it["color"]}" stroke="{it["color"]}" '
                     f'stroke-width="{r3(lp*.8)}"/>')
            tx(it["x"] + 4.6, it["y"], it["label"], fp * .95, "start")
        else:
            o.append(f'<g{A(data_legend_item=it["key"])}><line x1="{r3(it["x"]*P)}" y1="{r3((it["y"]-fp*.32)*P)}" '
                     f'x2="{r3((it["x"]+9.)*P)}" y2="{r3((it["y"]-fp*.32)*P)}" stroke="#111" stroke-width="{r3(lp)}"/>'
                     + "".join(head(it["key"], it["x"] + 9., it["y"] - fp * .32, 1., 0., lp)))
            tx(it["x"] + 10.5, it["y"], it["label"], fp * .95, "start")
        o.append("</g>")
    o.append('</g><g id="layer-titles" data-layer="titles">')
    if g["title"]:
        tx(cv["width_mm"] / 2, g["title_y"], g["title"], fp * 1.35, weight="bold")
    o.append("</g></svg>")
    return "\n".join(o) + "\n"


def apply_order(spec, order):
    """Model-level edit: rename_node / set_relation / set_title / set_caption."""
    new, ch, err, touched = copy.deepcopy(spec), [], [], set()
    ns = {n.get("id"): n for n in (new.get("nodes") or [])}
    es = {e.get("id"): e for e in (new.get("edges") or [])}
    for i, op in enumerate((order.get("operations") if isinstance(order, dict) else order) or []):
        k, oid, ok = op.get("op"), op.get("id"), False
        if k == "rename_node" and oid in ns:
            b = ns[oid].get("label"); ns[oid]["label"] = op.get("label", b)
            if op.get("evidence"):
                ns[oid]["evidence"] = op["evidence"]
            if op.get("aliases"):
                ns[oid]["aliases"] = list(dict.fromkeys(list(ns[oid].get("aliases") or []) + list(op["aliases"])))
            ch.append({"op": k, "id": oid, "before": b, "after": ns[oid]["label"], "reason": op.get("reason", "")}); ok = True
        elif k == "set_relation" and oid in es and op.get("relation") in REL:
            b = es[oid].get("relation"); es[oid]["relation"] = op["relation"]
            if op.get("evidence"):
                es[oid]["evidence"] = op["evidence"]
            ch.append({"op": k, "id": oid, "before": b, "after": op["relation"], "reason": op.get("reason", "")}); ok = True
        elif k in ("set_title", "set_caption"):
            key = "title" if k == "set_title" else "caption"
            b = new.get(key); new[key] = op.get("text") or op.get("value") or ""
            ch.append({"op": k, "before": b, "after": new[key], "reason": op.get("reason", "")}); ok = True
        if not ok:
            err.append({"index": i, "error": f"{k}: refused (unknown id/relation, or an operation this minimal skill does "
                                             "not apply; supported: rename_node, set_relation, set_title, set_caption)"})
        elif oid:
            touched.add(str(oid))  # only an applied operation counts as touched
    return new, ch, err, touched


ALI = {"svg": "editable_source", "figure": "deliverable", "export": "exports", "preview": "exports", "files": "outputs",
       "artifacts": "outputs", "evidence": "element_sources", "provenance": "element_sources", "notes": "change_log"}


def contract(case):
    """Field names declared by the case's output_contract, in any of its four shapes."""
    raw = next((v for k, v in (case or {}).items() if re.search(r"contract|output|schema|expect", str(k), re.I) and v), None)
    out = {}
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, str):
                out[it] = {"required": True, "type": "string"}
            elif isinstance(it, dict) and (it.get("name") or it.get("field")):
                out[it.get("name") or it.get("field")] = {"required": bool(it.get("required", True)),
                                                          "type": str(it.get("type") or "string")}
    elif isinstance(raw, dict):
        if raw.get("type") == "object" and "properties" in raw:
            req = set(raw.get("required") or [])
            out = {n: {"required": n in req, "type": str((s or {}).get("type") or "string")} for n, s in raw["properties"].items()}
        else:
            for n, v in raw.items():
                out[n] = ({"required": bool(v.get("required", True)), "type": str(v.get("type") or "string")} if isinstance(v, dict)
                          else {"required": True, "type": "array" if str(n).endswith("s") and n not in ("status", "summary") else "string"})
    return out


def run(case_path, out_dir, md=None, spec_path=None, quiet=False):
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    notes, F = [], []
    case, cerr = jload(case_path) if case_path else (None, "no case.json was found")
    case = case or {}
    cid = str(case.get("case_id") or case.get("id") or case.get("task_id") or
              (os.path.splitext(os.path.basename(case_path))[0] if case_path else "case"))
    if cerr:
        notes.append({"item": "case.json", "why": cerr, "handling": "continued with material discovery and a mined draft"})
    base = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    base = os.path.dirname(os.path.abspath(case_path)) if case_path else os.getcwd()
    md_from = "cli" if md else ""
    if not md:
        # case.json's directory first, then the cwd, then the platform default (D14 R1b)
        cand = case.get("material_dir") or case.get("materials")
        opts = []
        if cand:
            opts += [(os.path.join(base, cand), f"case_dir/{cand}"),
                     (os.path.join(os.getcwd(), cand), f"cwd/{cand}")]
        opts += [(os.path.join(base, "materials"), "case_dir/materials"), (base, "case_dir"),
                 (os.path.join(os.getcwd(), "input"), "cwd/input"), (os.getcwd(), "cwd"),
                 ("/input", "/input")]
        for c, lab in opts:
            if c and os.path.isdir(c):
                md, md_from = c, lab
                break
    corpus = material(md, notes)
    sfile, ssrc = (spec_path, "cli") if spec_path and os.path.isfile(spec_path) else find_spec(case, case_path, md, base)
    spec, serr = jload(sfile) if sfile else (None, None)
    if spec is not None and not (spec.get("nodes") or spec.get("edges")
                                 or (spec.get("data") or {}).get("table")):
        # a JSON that is not a usable figure model (a stray report, a truncated file) must
        # never shadow the heuristic derivation from the material.
        notes.append({"item": "figure model", "why": f"{os.path.basename(sfile or '?')} is not a "
                      "usable figure model (no nodes, no edges, no data table)",
                      "handling": "ignored it and derived the model from the material instead"})
        spec, sfile = None, ""
    if spec is None:
        if sfile:
            E(F, "spec_unreadable", f"spec {os.path.basename(sfile)} could not be read: {serr}")
        spec = draft(corpus, case.get("title") or "")
        ssrc = "mined draft" if spec else ssrc
        if spec:
            notes.append({"item": "figure model", "why": "no model was provided, so a draft was mined from the material",
                          "handling": "every drafted element is marked uncertain; review before submitting"})
    # ---- fully heuristic derivation -------------------------------------------------
    # With no usable model, derive one from the material alone: entities/relations from the
    # text, and a data table discovered in the material directory with its role columns
    # inferred. An external spec is never required.
    tbl, tinfo = find_table(md, base)
    DM0 = (spec or {}).get("data") or {}
    if tbl and not (DM0.get("table") or DM0.get("path")):
        if spec is None:
            spec = {"figure_type": "chart",
                    "canvas": {"width_mm": 120, "margin_mm": 6, "font_pt": 7.5, "line_pt": .9},
                    "title": f"Heuristic chart from {os.path.basename(tbl)}"}
            ssrc = "heuristic table"
            notes.append({"item": "figure model", "why": "no model was provided; the table in the "
                          "material was used directly", "handling": "columns were inferred "
                          "heuristically and every mark keeps a data-source locator"})
        spec = dict(spec)
        spec["data"] = dict(tinfo, table=tbl)
        ssrc = ssrc or "heuristic table"
    res = {"case_id": cid,
           "task": case.get("task") or case.get("title") or "科研示意图生成与编辑 (scientific schematic generation and editing)",
           "status": "success", "status_reason": "", "summary": "", "deliverable": "", "editable_source": "",
           "exports": [], "outputs": [], "element_sources": [], "data_mapping": {}, "checks": {"ok": True, "items": []},
           "uncertainty": list(notes) + [
               {"item": "export scope", "why": "this minimal build emits an SVG only (no PDF/PNG) and embeds no font",
                "handling": "vector text stays selectable and editable; the viewer substitutes a system font"},
               {"item": "layout", "why": "positions come from a deterministic grid, not from a typesetting engine",
                "handling": "long labels are truncated to fit their box; re-check the SVG if you go beyond ~20 entities"}],
           "gaps": [], "changes": [], "source_preservation": None, "not_reported": [],
           "change_log": [f"read {len(corpus['files'])} material file(s); {sum(1 for f in corpus['files'] if f['readable'])} readable",
                          f"model source: {ssrc or '(none)'}"],
           "sources": [{"rel": f["rel"], "bytes": f["bytes"], "readable": f["readable"], "note": f.get("note", "")} for f in corpus["files"]],
           "metrics": {}, "run_log": {}, "self_scored": False,
           "note": "this skill does not score itself; quality is judged by an independent run"}
    DM = (spec or {}).get("data") or {}
    if not spec or not (spec.get("nodes") or DM.get("table") or DM.get("path")):
        res.update({"status": "partial", "summary": "no deliverable: neither a figure model nor readable material was found",
                    "status_reason": "no figure model and no readable material: nothing could be drawn without inventing content",
                    "gaps": [{"item": "everything", "why": "inputs missing", "alternative_evidence": "run again with --case/--material"}]})
        res["checks"] = {"ok": False, "items": [], "blocking": {"model_errors": 1, "data_errors": 0}}
        res["run_log"] = {"seconds": round(time.time() - t0, 2), "spec_source": ssrc or "(none)"}
        res["resolved_from"] = _resolved(case_path, base, md, md_from, sfile, ssrc)
        return finish(out_dir, res, case, quiet)
    check_model(spec, corpus, F)
    d = data_of(spec, md, case_path, notes, F)
    order, osrc = None, ""
    for k in ("edit_order", "edit_request", "changes_request"):
        v = case.get(k)
        order, osrc = (v, f"case.{k}") if isinstance(v, dict) else ((jload(v)[0], f"case.{k}") if isinstance(v, str) and os.path.isfile(v) else (order, osrc))
    if not order and sfile:
        n = next((x for x in sorted(os.listdir(os.path.dirname(sfile))) if re.search(r"(edit|change)[-_]?order.*\.json$", x, re.I)), None)
        if n:
            order, osrc = jload(os.path.join(os.path.dirname(sfile), n))[0], f"discovered:{n}"
    old, changes, eerr, pres = spec, [], [], None
    if order:
        spec, changes, eerr, touched = apply_order(spec, order)
        if eerr:
            E(F, "edit_order_refused", "; ".join(e["error"] for e in eerr))
        ids = lambda s: {n.get("id") for n in s.get("nodes") or []} | {e.get("id") for e in s.get("edges") or []}
        o, n2 = ids(old), ids(spec)
        pres = {"available": True, "level": "model elements (id + label), not byte-level SVG", "elements_before": len(o),
                "elements_after": len(n2), "unchanged": len(o & n2 - touched), "changed": sorted(o & touched),
                "removed": sorted(o - n2), "added": sorted(n2 - o), "source_preserved": not (o - n2),
                "note": "every element the edit order did not name survives unchanged"}
        notes.append({"item": "edit order", "why": f"{len(changes)} operation(s) applied from {osrc}",
                      "handling": "the figure was re-derived from the edited model; untouched elements keep their id and label"})
    g = layout(spec, d, notes)
    _drawn = len(g["nodes"]) + len(g["edges"]) + len((g.get("strip") or {}).get("bars") or [])
    if _drawn == 0:  # empty-figure guard: a silently swallowed input must never look fine
        E(F, "empty_figure", "the run produced 0 entities, 0 relations and 0 data marks: the "
                             "case was probably not read, so nothing was drawn")
        res["gaps"].append({"item": "empty figure",
                            "why": "0 entities, 0 relations and 0 data marks were drawn",
                            "alternative_evidence": "check sources[] readability and "
                                                    "run_log.resolved_from for the paths used"})
    svg = render(g, d)
    rows, prov = verify(spec, corpus)
    if d:
        for b in (g["strip"] or {}).get("bars", []):
            rows.append({"element_id": f'mark-{b["category"]}-{b["series"]}', "element_type": "data-mark",
                         "label": f'{b["series"]} @ {b["category"]}', "relation": "", "declared_source": d["rel"],
                         "quote": f'{b["value"]:g}', "verified": True, "locator": f'{d["rel"]}#{d["value_column"]}', "occurrences": 1})
        q = [r for r in rows if r["element_type"] != "data-mark"]
        prov = {"quotes": len(q), "verified": sum(1 for r in q if r["verified"]),
                "rate": round(sum(1 for r in q if r["verified"]) / len(q), 3) if q else None}
    if prov.get("quotes") and not prov.get("verified"):
        # nothing can be traced back: this is the off-topic / wholesale-fabrication shape and
        # must not be reported as a success.
        E(F, "evidence_unverified", "none of the quoted sentences occur in the material, so no "
                                    "element can be traced back to its source")
        res["gaps"].append({"item": "unverified evidence",
                            "why": "0 of the quoted sentences were found in the material",
                            "alternative_evidence": "check sources[] and each element_sources[].quote"})
    if not corpus["text"]:
        E(F, "quotes_unverifiable", "no readable material text was available, so quoted sentences could not be verified", "warn")
    keys, drawn = {it["key"] for it in g["legend"]}, {e["relation"] for e in g["edges"]} | set((d or {}).get("series", []))
    if drawn - keys:
        E(F, "legend_incomplete", f"{sorted(drawn - keys)} are drawn but missing from the legend")
    sp = os.path.join(out_dir, "figure.svg")
    with open(sp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg)
    pub = lambda o: ({k: pub(v) for k, v in o.items() if not k.startswith("_")} if isinstance(o, dict)
                     else [pub(v) for v in o] if isinstance(o, list) else o)
    tx, errs = svg.count("<text "), [f for f in F if f["severity"] == "error"]
    warns, secs = [f for f in F if f["severity"] == "warn"], round(time.time() - t0, 2)
    m = {"figure_type": spec.get("figure_type") or ("chart" if d else "mechanism"), "entities": len(g["nodes"]),
         "relations": len(g["edges"]), "legend_items": len(g["legend"]), "data_marks": len((g["strip"] or {}).get("bars") or []),
         "categories": len((d or {}).get("categories") or []), "series": len((d or {}).get("series") or []),
         "canvas_mm": [g["canvas"]["width_mm"], g["canvas"]["height_mm"]], "font_pt": g["canvas"]["font_pt"],
         "svg_text_elements": tx, "evidence_quotes": prov.get("quotes"), "evidence_verified": prov.get("verified"),
         "evidence_verify_rate": prov.get("rate"), "seconds": secs,
         "spec_sha256": hashlib.sha256(json.dumps(pub(spec), sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    res.update({
        "editable_source": "figure.svg",
        "editable_source_detail": f"layered SVG: {tx} real <text> elements (selectable and editable); every entity/edge/mark "
                                  f"carries id + data-source; layers {list(dict.fromkeys(re.findall(r'data-layer=.([a-z]+).', svg)))}",
        "exports": [{"format": "svg", "path": sp, "rel": "figure.svg", "bytes": os.path.getsize(sp), "vector": True,
                     "text_as_text": True, "text_elements": tx, "raster_elements": 0, "font_pt": g["canvas"]["font_pt"],
                     "canvas_mm": [g["canvas"]["width_mm"], g["canvas"]["height_mm"]]}],
        "outputs": [{"kind": "editable_svg", "path": sp, "rel": "figure.svg", "bytes": os.path.getsize(sp)}],
        "element_sources": [{"element_id": r["element_id"], "element_type": r["element_type"], "label": r["label"],
                             "relation": r["relation"], "source": r["declared_source"], "locator": r["locator"],
                             "quote": r["quote"], "verified_in_material": r["verified"]} for r in rows],
        "data_mapping": ({"table": d["rel"], "category_column": d["category_column"], "series_column": d["series_column"],
                          "value_column": d["value_column"], "error_column": d["error_column"], "unit": d["unit"],
                          "categories": d["categories"], "series": d["series"], "rows": d["rows"], "colors": d["colors"]}
                         if d else {"note": "no data table in this case"}),
        "changes": changes, "source_preservation": pres, "metrics": m,
        "checks": {"ok": not errs, "items": F, "counts": {"errors": len(errs), "warnings": len(warns)},
                   "blocking": {"model_errors": len([f for f in errs if not str(f["check"]).startswith("data")]),
                                "data_errors": len([f for f in errs if str(f["check"]).startswith("data")])},
                   "legend": {"keys": sorted(keys), "derived_from": "the relations and series actually drawn"},
                   "export": {"ok": True, "svg_text_elements": tx, "text_selectable": True, "raster_elements": 0,
                              "note": "the SVG is both the editable source and the vector export; PDF/PNG are out of scope here"}},
        "run_log": {"seconds": secs, "spec_source": ssrc or "(none)", "spec_path": os.path.basename(sfile or ""),
                    "case_path": os.path.basename(case_path or ""), "material_dir": os.path.basename(md or "")}})
    res["deliverable"] = res["editable_source_detail"]
    res["uncertainty"] += [{"item": f"check:{w['check']}", "why": w["message"], "handling": "flagged for human review"} for w in warns]
    res["not_reported"] = [{"field": f"material {f['rel']}", "why": f.get("note") or "could not be read"}
                           for f in corpus["files"] if not f["readable"]]
    if not prov.get("quotes"):
        res["not_reported"].append({"field": "evidence quotes", "why": "the model carried no quoted sentences"})
    if errs:
        res["status"] = "partial"
        res["status_reason"] = "blocking check(s) failed: " + ", ".join(sorted({f["check"] for f in errs}))
        res["gaps"].append({"item": "blocking checks", "why": res["status_reason"],
                            "alternative_evidence": "the artifacts and the per-check list are still written"})
    elif spec.get("uncertain") or str(ssrc).startswith(("mined", "heuristic")):
        # a derived model is a provenance fact, not a failure: status is decided by the
        # blocking checks above. It is recorded so a reviewer knows what to confirm.
        res["uncertainty"].append({"item": "model provenance",
                                   "why": "the figure model was derived heuristically from the "
                                          "material instead of being read from a reviewed model",
                                   "handling": "every derived element carries its source sentence "
                                               "in element_sources; review them before submitting"})
        res["change_log"].append("model derived heuristically (no reviewed model was supplied); "
                                 "status still reflects the blocking checks only")
    res["summary"] = (f"{m['entities']} entities / {m['relations']} relations"
                      + (f", {m['data_marks']} data marks over {m['categories']} categories x {m['series']} series" if d else "")
                      + f" on a {m['canvas_mm'][0]}x{m['canvas_mm'][1]} mm canvas; blocking errors {len(errs)}; evidence quotes "
                        f"verified {m['evidence_verified']}/{m['evidence_quotes']}; editable SVG in {secs}s")
    res["resolved_from"] = _resolved(case_path, base, md, md_from, sfile, ssrc)
    res["change_log"].append(f"checks: {len(errs)} error(s), {len(warns)} warning(s)")
    return finish(out_dir, res, case, quiet, F)


def finish(out_dir, res, case, quiet, F=()):
    fields, miss, echo = contract(case), [], {}
    for n, meta in fields.items():
        v = res.get(n, res.get(ALI.get(n, n)))
        if v is None:
            v = [] if meta.get("type") in ("array", "list") else ""
            miss += [n] if meta.get("required") else []
        echo[n] = v
    res["contract_echo"], res["contract_fields_declared"], res["contract_missing_required"] = echo, len(fields), miss
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2, default=str)
    if not quiet:
        print(res["summary"])
        print(f"status: {res['status']} ({res['status_reason'] or 'ok'})")
        for f in F:
            print(f"  [{f['severity']}] {f['check']}: {f['message']}")
        print("RESULT_OK" if res["status"] == "success" else "RESULT_PARTIAL")
    return 0 if res["status"] == "success" else 2


def _resolved(case_path, base, md, md_from, sfile, ssrc):
    """How every relative path was resolved, so a reviewer never has to guess the cwd."""
    return {"case": case_path or "(none)", "case_dir": base or "(none)",
            "material_dir": md or "(none)", "material": md_from or "(none)",
            "spec": sfile or "(none)", "spec_source": ssrc or "(none)",
            "order": "case.json dir -> material dir -> cwd -> /input; nothing is resolved "
                     "against the cwd first"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="minimal editable scientific schematic skill")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--material", default=None)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    return run(a.case if os.path.isfile(a.case) else None, a.out, a.material, a.spec, a.quiet)


if __name__ == "__main__":
    sys.exit(main())
