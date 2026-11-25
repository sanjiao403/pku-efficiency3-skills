"""papertext.py - turn a real source into located text segments.

Input may be a single file or a directory (a case material folder).  Supported
readers, in order of preference:

* ``.pdf``   - text layer through :mod:`pdf_lite` (page numbers preserved)
* ``.tex``   - LaTeX reducer: sections, labels, ``\\ref``/``\\cite`` resolution
* ``.md``    - Markdown headings / lists / para
* ``.docx``  - paragraphs + tables (python-docx, optional)
* ``.txt`` / ``.csv`` / ``.json`` / ``.bib`` / ``.html``

Every segment carries a locator.  Nothing is invented: if the reader cannot
recover text (e.g. a scanned PDF without a text layer) the result says so in
``meta.notes`` and ``meta.text_layer = False`` so the caller can switch to OCR
instead of guessing.
"""
from __future__ import annotations

import os
import re

from util import Log, one_line, read_text, rel_posix, squish

SUPPORTED = {".pdf", ".tex", ".md", ".markdown", ".txt", ".docx", ".tex.txt",
             ".bib", ".json", ".csv", ".html", ".htm"}

_SKIP_DIRS = {"__pycache__", ".git", ".ipynb_checkpoints", "output", "outputs"}


class Source:
    """Collected material with page/section/line locators."""

    def __init__(self):
        self.segments: list[dict] = []
        self.files: list[dict] = []
        self.notes: list[str] = []
        self.text_layer = True
        self.bib: dict[str, dict] = {}

    # ---------------------------------------------------------------- adding
    def add(self, text: str, *, kind: str, source: str, page=None, section=None,
            line=None, para=None, label=None, order=None):
        text = squish(text)
        if not text:
            return None
        seg = {
            "id": f"seg-{len(self.segments) + 1:04d}",
            "kind": kind,
            "text": text,
            "source": rel_posix(source),
            "page": page,
            "section": section,
            "line": line,
            "para": para,
            "label": label,
            "order": len(self.segments) if order is None else order,
        }
        self.segments.append(seg)
        return seg

    # ---------------------------------------------------------------- views
    def texts(self, kinds=None) -> list[str]:
        return [s["text"] for s in self.segments if kinds is None or s["kind"] in kinds]

    @property
    def full_text(self) -> str:
        return "\n".join(self.texts())

    def locator(self, seg: dict) -> str:
        bits = [seg["source"]]
        if seg.get("section"):
            bits.append(f"\u00a7{seg['section']}")
        if seg.get("page"):
            bits.append(f"p{seg['page']}")
        if seg.get("line"):
            bits.append(f"L{seg['line']}")
        if seg.get("para") is not None:
            bits.append(f"para{seg['para'] + 1}")
        return " \u00b7 ".join(bits)

    def quote_locator(self, quote: str):
        """Find where *quote* occurs.

        Returns ``(segment, locator, match_kind)`` where match_kind is
        ``"verbatim"`` (whitespace-insensitive), ``"normalised"`` (survives PDF
        column bars / hyphenation) or ``None`` when it is not there at all.
        """
        from util import norm_key, quote_key
        if len(norm_key(quote)) < 6:
            return None, None, None
        q = norm_key(quote)
        for seg in self.segments:
            if q in norm_key(seg["text"]):
                return seg, self.locator(seg), "verbatim"
        for seg in self.segments:
            if q in quote_key(seg["text"]):
                return seg, self.locator(seg), "normalised"
        # allow the quote to span consecutive segments of the same section
        for key_fn, kind in ((quote_key, "span"),):
            joined, spans = "", []
            for seg in self.segments:
                spans.append((len(joined), seg))
                joined += key_fn(seg["text"])
            idx = joined.find(key_fn(quote))
            if idx >= 0:
                start = max(s for s, _ in spans if s <= idx)
                seg = next(seg for s, seg in spans if s == start)
                return seg, self.locator(seg) + " (span)", kind
        return None, None, None

    def to_dict(self) -> dict:
        return {
            "engine_segments": len(self.segments),
            "files": self.files,
            "text_layer": self.text_layer,
            "notes": self.notes,
            "bib_keys": sorted(self.bib.keys()),
        }


# ---------------------------------------------------------------- dispatch

def discover(path: str, exclude=()) -> list[str]:
    """Every readable material file under *path* (a file or a directory).

    *exclude* holds paths that are inputs to the run but not scientific material -
    in practice the case file itself, which must never end up quoted as evidence
    for a page.  Keeping it out of the material set means the title page is
    grounded in the paper, not in the case metadata.
    """
    skip = {os.path.abspath(x) for x in exclude if x}
    if os.path.isfile(path):
        return [] if os.path.abspath(path) in skip else [path]
    out = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext in SUPPORTED and os.path.abspath(os.path.join(dirpath, fn)) not in skip:
                out.append(os.path.join(dirpath, fn))
    out.sort(key=lambda p: (os.path.splitext(p)[1].lower() == ".bib", p))
    return out


def ingest(path: str, log: Log | None = None, exclude=()) -> Source:
    src = Source()
    files = discover(path, exclude)
    if not files:
        src.notes.append(f"no supported material under {rel_posix(path)}")
        return src
    # .bib first so \cite keys can be resolved while reducing .tex
    for f in files:
        if f.lower().endswith(".bib"):
            _read_bib(f, src)
    for f in files:
        if f.lower().endswith(".bib"):
            continue
        ext = os.path.splitext(f)[1].lower()
        try:
            if ext == ".pdf":
                _read_pdf(f, src)
            elif ext == ".tex":
                _read_tex(f, src)
            elif ext in (".md", ".markdown"):
                _read_md(f, src)
            elif ext == ".docx":
                _read_docx(f, src)
            elif ext in (".html", ".htm"):
                _read_html(f, src)
            else:
                _read_plain(f, src)
            src.files.append({"path": rel_posix(f), "reader": ext.lstrip(".") or "txt"})
        except Exception as exc:  # keep going: partial material beats nothing
            msg = f"reader failed for {rel_posix(f)}: {type(exc).__name__}: {exc}"
            src.notes.append(msg)
            if log:
                log.warn(msg)
    return src


# ---------------------------------------------------------------- readers

def _read_pdf(path: str, src: Source):
    import pdf_lite
    res = pdf_lite.extract_pages(path)
    src.notes.extend(f"{rel_posix(path)}: {n}" for n in res["notes"])
    if not res["text_layer"]:
        src.text_layer = False
    name = os.path.basename(path)
    if not res["pages"]:
        src.notes.append(f"{name}: 0 pages with text recovered")
        return
    for pg in res["pages"]:
        section = None
        for para_i, (hint, block) in enumerate(blocks_from_page_text(pg["text"])):
            kind, clean = _classify_block(block)
            if hint in ("heading", "caption", "table-row", "reference") and kind == "para":
                kind = hint
            if kind == "heading":
                section = one_line(clean)[:60]
            src.add(clean, kind=kind, source=name, page=pg["page"], section=section,
                    para=para_i)


_BLOCK_SPLIT = re.compile(r"\n\s*\n")


def _split_blocks(text: str) -> list[str]:
    return [b for b in _BLOCK_SPLIT.split(text or "") if b.strip()]


_SOFT_HEAD = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?)\s+\S"
    r"|^\s*(?:Abstract|Introduction|Related Work|Background|Methods?|Methodology|"
    r"Materials and Methods|Results?|Experiments?|Evaluation|Discussion|Conclusions?|"
    r"Limitations|Future Work|References|Acknowledg\w*|Appendix\w*)\b",
    re.I,
)


def _is_meta_title(seg) -> bool:
    return seg.get("kind") == "meta-title"
_SOFT_CAP = re.compile(
    r"^\s*(?:[Ff]igure|[Ff]ig\.?|[Tt]able|[Tt]ab\.?|[Aa]lgorithm|[Ll]isting|[Ii]mage|"
    r"\u56fe|\u8868)\s*(?:\d+|[IVX]+)\s*[.:\u2014\u3001]\s*(?=[A-Z0-9\u4e00-\u9fff\u00b0])")


def blocks_from_page_text(text: str) -> list[tuple[str, str]]:
    """Split a recovered PDF page into (kind_hint, block) pairs.

    A PDF page is a run of visual lines; without font metrics we use line shape:
    lines that look like a heading, a caption, a reference entry or a table row
    become their own block, everything else accumulates into a paragraph.
    """
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        if buf:
            out.append(("para", " ".join(buf).strip()))
            buf.clear()

    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if _SOFT_CAP.match(line):
            flush()
            out.append(("caption", line))
            continue
        if _SOFT_HEAD.match(line) and len(line) < 90:
            flush()
            out.append(("heading", line))
            continue
        if re.match(r"^\[\d+\]|^\d+\.\s+[A-Z][a-z]+,\s", line):
            flush()
            out.append(("reference", line))
            continue
        if line.count("|") >= 2 or (line.count("  ") >= 2 and len(line) < 120):
            flush()
            out.append(("table-row", line))
            continue
        buf.append(line)
    flush()
    return out


_HEAD_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+[A-Z\u4e00-\u9fff]"      # "3.2 Results"
    r"|^\s*(?:Abstract|Introduction|Related Work|Methods?|Methodology|Results?|"
    r"Discussion|Conclusion|Conclusions|Limitations|References|Acknowledge?ments?|"
    r"摘要|引言|相关工作|方法|结果|讨论|结论|局限性?|参考文献)\s*$",
    re.I,
)


def _classify_block(block: str) -> tuple[str, str]:
    b = block.strip()
    low = one_line(b).lower()
    if _HEAD_RE.match(b) or (len(low) < 70 and re.match(r"^\d+(\.\d+)*\.?\s", low)):
        return "heading", b
    if re.match(r"^(figure|fig\.?|table|tab\.?|\u56fe|\u8868)\s*\d+\s*[.:|\u2014-]", low):
        return "caption", b
    if low.startswith(("abstract", "keywords", "\u6458\u8981", "\u5173\u952e\u8bcd")):
        return "abstract", b
    if re.match(r"^(\[|\d+\.\s+[A-Z])", b) and len(b) < 400 and low.count("et al") + low.count("doi") > 0:
        return "reference", b
    if b.startswith(("-", "*", "\u2022")) or re.match(r"^\d+[\).]\s", b):
        return "bullet", b
    return "para", b


_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_CAPTION_RE = re.compile(r"\\caption\s*\{", re.I)
_REF_RE = re.compile(r"\\(?:ref|autoref|Cref|cref|eqref)\s*\{([^}]+)\}")
_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\])*\s*\{([^}]+)\}")
_ENV_RE = re.compile(r"\\begin\s*\{([^}]+)\}(.*?)\\end\s*\{\1\}", re.S)
_SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*\{", re.I)
_HEADING_WORDS = re.compile(r"\\(?:title|author|affiliation|keywords|abstract)\b", re.I)


def _strip_comments(tex: str) -> str:
    out = []
    for line in tex.split("\n"):
        if line.lstrip().startswith("%"):
            continue
        out.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(out)


def _read_tex(path: str, src: Source):
    raw = read_text(path)
    name = os.path.basename(path)
    tex = _strip_comments(raw)
    body = _preamble_strip(tex)
    body = _include_inputs(body, os.path.dirname(path))

    # 1) record figure/table environments (labels + captions) in document order
    fig_n = tab_n = eq_n = 0
    label_map: dict[str, str] = {}
    env_blocks = []
    _pending_rows: list[tuple[int, list[list[str]]]] = []
    for m in _ENV_RE.finditer(body):
        env = m.group(1).lower()
        if env in ("figure", "figure*"):
            fig_n += 1
            lab = _LABEL_RE.search(m.group(2))
            cap = _grab_braced(m.group(2), "caption")
            if lab:
                label_map[lab.group(1)] = f"Figure {fig_n}"
            env_blocks.append((m.start(), m.end(), "figure", fig_n,
                               one_line(cap or ""), lab.group(1) if lab else None))
        elif env in ("table", "table*"):
            tab_n += 1
            lab = _LABEL_RE.search(m.group(2))
            cap = _grab_braced(m.group(2), "caption")
            if lab:
                label_map[lab.group(1)] = f"Table {tab_n}"
            env_blocks.append((m.start(), m.end(), "table", tab_n,
                               one_line(cap or ""), lab.group(1) if lab else None))
            _pending_rows.append((tab_n, _tabular_rows(m.group(2))))
        elif env in ("equation", "equation*", "align", "align*", "eqnarray"):
            eq_n += 1
            lab = _LABEL_RE.search(m.group(2))
            if lab:
                label_map[lab.group(1)] = f"Equation ({eq_n})"

    # title/author from the preamble-ish head: real papers put them in \maketitle
    tm = _grab_braced(tex, "title")
    if tm:
        src.add(one_line(tm), kind="meta-title", source=name, section="title")
    am = _grab_braced(tex, "author")
    if am:
        src.add(one_line(_detex(am)), kind="meta-authors", source=name, section="title")
    ab = _grab_braced(tex, "begin{abstract}")
    if not ab:
        amb = re.search(r"\\begin\s*\{abstract\}(.*?)\\end\s*\{abstract\}", tex, re.S)
        if amb:
            ab = amb.group(1)
    if ab:
        src.add(_detex(ab), kind="abstract", source=name, section="Abstract")

    # 2) resolve refs to human labels before flattening
    def sub_ref(m):
        key = m.group(1)
        return label_map.get(key, f"[unresolved:{key}]")

    flat = _REF_RE.sub(sub_ref, body)

    def sub_cite(m):
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        return "[" + ", ".join(keys) + "]"

    flat = _CITE_RE.sub(sub_cite, flat)

    # 3) emit segments, tracking section numbering and heading positions
    section_no = [0, 0, 0]
    cur_section = None
    pending_caption: list[tuple[int, str, str]] = []

    # remove env bodies from the prose stream but remember positions
    for _, _, kind, n, cap, lab in env_blocks:
        if cap:
            pending_caption.append((n, cap, f"{'Figure' if kind == 'figure' else 'Table'} {n}"))

    pos = 0
    tokens: list[tuple[int, int, str, str]] = []
    for m in re.finditer(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*\{", flat, re.I):
        tokens.append((m.start(), _brace_end(flat, m.end() - 1), "heading", m.group(1).lower()))
    for m in _ENV_RE.finditer(flat):
        if m.group(1).lower() in ("figure", "figure*", "table", "table*",
                                  "equation", "equation*", "align", "align*"):
            tokens.append((m.start(), m.end(), "env", m.group(1).lower()))
    tokens.sort()

    for start, tok_end, kind, sub in tokens:
        if start > pos:
            _emit_tex_prose(flat[pos:start], src, name, cur_section)
        if kind == "heading":
            title = _grab_braced(flat[start:tok_end], sub) or ""
            depth = {"part": 0, "chapter": 0, "section": 1, "subsection": 2,
                     "subsubsection": 3, "paragraph": 3}.get(sub, 1)
            if depth <= 1:
                section_no[0] += 1
                section_no[1] = section_no[2] = 0
            elif depth == 2:
                section_no[1] += 1
                section_no[2] = 0
            else:
                section_no[2] += 1
            num = ".".join(str(x) for x in section_no[:max(1, depth)])
            cur_section = f"{num} {one_line(title)}".strip()
            src.add(cur_section, kind="heading", source=name, section=cur_section,
                    line=flat[:start].count("\n") + 1)
        else:
            if sub.startswith(("figure", "table")):
                nth = fig_n if sub.startswith("figure") else tab_n
                for n, cap, label in pending_caption:
                    if label.split()[-1] != str(nth):
                        continue
                    if label.split()[0].lower()[:4] != sub[:4]:
                        continue
                    src.add(f"{label}. {cap}", kind="caption", source=name,
                            section=cur_section, label=label,
                            line=flat[:start].count("\n") + 1)
                    break
                if sub.startswith("table"):
                    for tn, rows in _pending_rows:
                        if tn != nth:
                            continue
                        for r_i, row in enumerate(rows):
                            src.add(" | ".join(row), kind="table-row", source=name,
                                    section=cur_section, label=f"Table {tn}", para=r_i)
            else:  # equation: keep the numbered formula as a located segment
                eq_body = _ENV_RE.match(flat[start:tok_end])
                if eq_body:
                    text = _detex(eq_body.group(2))
                    if text:
                        src.add(f"Equation ({eq_n}). {text}", kind="equation",
                                source=name, section=cur_section,
                                line=flat[:start].count("\n") + 1)
        pos = tok_end
    if pos < len(flat):
        _emit_tex_prose(flat[pos:], src, name, cur_section)

    src.notes.append(f"{name}: {fig_n} figure env, {tab_n} table env, {eq_n} equation env")


def _preamble_strip(tex: str) -> str:
    m = re.search(r"\\begin\s*\{document\}", tex)
    if m:
        tex = tex[m.end():]
    tex = re.split(r"\\end\s*\{document\}", tex)[0]
    return tex


def _include_inputs(tex: str, base: str) -> str:
    def sub(m):
        rel = m.group(1).strip()
        for cand in (rel, rel + ".tex", os.path.join(base, rel), os.path.join(base, rel) + ".tex"):
            if os.path.isfile(cand):
                try:
                    return read_text(cand)
                except Exception:
                    return ""
        return ""
    return re.sub(r"\\(?:input|include)\s*\{([^}]+)\}", sub, tex)


def _tabular_rows(env_body: str) -> list[list[str]]:
    """Pull rows out of a tabular/tabularx/longtable environment body."""
    m = re.search(r"\\begin\s*\{(tabular\*?|tabularx|longtable|array)\}\s*(\{[^}]*\})?\s*(\{[^}]*\})?",
                  env_body)
    body = env_body[m.end():] if m else env_body
    body = re.split(r"\\end\s*\{(?:tabular\*?|tabularx|longtable|array)\}", body)[0]
    body = re.sub(r"\\(?:toprule|midrule|bottomrule|hline|cline\{[^}]*\}|cmidrule(?:\([^)]*\))?\{[^}]*\})",
                  "\n", body)
    rows = []
    for raw in body.split("\\\\"):
        raw = raw.strip()
        if not raw:
            continue
        cells = [one_line(_detex(c)) for c in raw.split("&")]
        cells = [c for c in cells if c]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def _brace_end(s: str, open_idx: int) -> int:
    if open_idx >= len(s) or s[open_idx] != "{":
        return open_idx
    depth, i = 0, open_idx
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(s)


def _grab_braced(s: str, cmd: str) -> str | None:
    m = re.search(r"\\" + cmd + r"\*?\s*\{", s, re.I)
    if not m:
        return None
    i = m.end()
    depth = 1
    out = []
    while i < len(s) and depth:
        ch = s[i]
        if ch == "\\":
            out.append(s[i:i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
        i += 1
    return "".join(out)


_FMT_JUNK = [
    (re.compile(r"\\(?:textbf|textit|emph|texttt|textrm|textsf|mbox|text|mathrm|mathbf|mathit|operatorname|SI|SIrange|SIlist|num|qty)\s*\{"), ""),
    (re.compile(r"\\[a-zA-Z]+\*?\s*"), " "),
    (re.compile(r"[{}]"), ""),
    (re.compile(r"\$+"), " "),
    (re.compile(r"[ \t]{2,}"), " "),
]


_GREEK = {
    "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3", "delta": "\u03b4",
    "epsilon": "\u03b5", "zeta": "\u03b6", "eta": "\u03b7", "theta": "\u03b8",
    "kappa": "\u03ba", "lambda": "\u03bb", "mu": "\u03bc", "nu": "\u03bd",
    "xi": "\u03be", "pi": "\u03c0", "rho": "\u03c1", "sigma": "\u03c3",
    "tau": "\u03c4", "phi": "\u03c6", "chi": "\u03c7", "psi": "\u03c8",
    "omega": "\u03c9", "Delta": "\u0394", "Sigma": "\u03a3", "Omega": "\u03a9",
    "le": "\u2264", "ge": "\u2265", "neq": "\u2260", "approx": "\u2248",
    "times": "\u00d7", "pm": "\u00b1", "cdot": "\u00b7", "infty": "\u221e",
    "rightarrow": "\u2192", "to": "\u2192", "in": "\u2208",
}
_MATH_RE = re.compile(r"\$\$?(.+?)\$\$?", re.S)
_SUP = {"0": "\u2070", "1": "\u00b9", "2": "\u00b2", "3": "\u00b3",
        "4": "\u2074", "5": "\u2075", "6": "\u2076", "7": "\u2077",
        "8": "\u2078", "9": "\u2079", "-": "\u207b", "+": "\u207a",
        "n": "\u207f", "i": "\u2071"}


def _demath(m: re.Match) -> str:
    body = m.group(1)
    body = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "\u00b0", body)
    for k, v in _GREEK.items():
        body = re.sub(r"\\" + k + r"(?![a-zA-Z])", v, body)
    # x^{2} / x^2 -> superscript where unambiguous, else keep ^2
    def sup(mm):
        inner = mm.group(1)
        if all(c in _SUP for c in inner):
            return "".join(_SUP[c] for c in inner)
        return "^" + inner

    body = re.sub(r"\^\s*\{([^{}]*)\}", sup, body)
    body = re.sub(r"\^\s*(\w)", lambda mm: _SUP.get(mm.group(1), "^" + mm.group(1)), body)
    body = re.sub(r"_\{([^{}]*)\}", r"\1", body)
    body = re.sub(r"_(\w)", r"\1", body)
    body = body.replace("{", "").replace("}", "").replace("\\,", " ").replace("\\;", " ")
    body = re.sub(r"\\[a-zA-Z]+", " ", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    return body.strip() if body.strip() else " "


_DUP_LABEL = re.compile(r"\b(Figure|Fig\.|Table|Equation|Eq\.)\s+\1\s+(\d+)", re.I)
_ABBREV_DUP = re.compile(r"\b(Fig|Tab|Eq)\.\s+(Figure|Table|Equation)\s+(\d+)", re.I)


def _detex(s: str) -> str:
    s = s.replace("~", " ")
    s = re.sub(r"\\(?:begin|end)\s*\{[^}]*\}", " ", s)
    s = re.sub(r"\\(?:label|hspace|vspace|index|centering|includegraphics|clearpage|newpage)\s*(\[[^\]]*\])?\s*(\{[^}]*\})?", " ", s)
    s = _MATH_RE.sub(_demath, s)
    # keep the argument of text commands
    for pat, rep in _FMT_JUNK[:1]:
        prev = None
        while prev != s:
            prev = s
            s = pat.sub(rep, s)
    s = _FMT_JUNK[1][0].sub(_FMT_JUNK[1][1], s)
    s = _FMT_JUNK[2][0].sub(_FMT_JUNK[2][1], s)
    s = _FMT_JUNK[3][0].sub(_FMT_JUNK[3][1], s)
    s = s.replace("\\%", "%").replace("\\&", "&").replace("\\_", "_")
    s = _DUP_LABEL.sub(lambda m: f"{m.group(1)} {m.group(2)}", s)
    s = _ABBREV_DUP.sub(lambda m: f"{m.group(1)}. {m.group(3)}", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return squish(s)


def _emit_tex_prose(chunk: str, src: Source, name: str, section: str | None):
    chunk = re.sub(r"\\(?:begin|end)\s*\{(?:figure|table)\*?\}", "\n", chunk)
    for block in _split_blocks(_detex(chunk)):
        kind, clean = _classify_block(block)
        src.add(clean, kind=kind, source=name, section=section,
                line=None, para=None)


_MD_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _md_clean(s: str) -> str:
    s = re.sub(r"^\s*>\s?", "", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    return s


def _read_md(path: str, src: Source):
    raw = read_text(path)
    name = os.path.basename(path)
    lines = raw.split("\n")
    section = None
    cur: list[str] = []
    cur_start = 0
    h1_seen = False
    table_no = 0
    in_table = False

    def flush():
        nonlocal cur
        if cur:
            block = _md_clean("\n".join(cur)).strip()
            if block:
                kind, clean = _classify_block(block)
                src.add(_md_clean(clean), kind=kind, source=name, section=section,
                        line=cur_start + 1, para=None)
        cur = []

    for i, line in enumerate(lines):
        m = _MD_HEAD.match(line)
        lm = _MD_LIST.match(line)
        if m:
            flush()
            in_table = False
            level = len(m.group(1))
            title = _md_clean(m.group(2)).strip()
            if level == 1 and not h1_seen:
                h1_seen = True
                section = title
                src.add(title, kind="meta-title", source=name, section="title", line=i + 1)
                continue
            section = one_line(title)
            src.add(section, kind="heading", source=name, section=section, line=i + 1)
            continue
        if _MD_TABLE_SEP.match(line):
            continue                       # the |---|---| separator carries no data
        if line.strip().startswith("|") and line.count("|") >= 2:
            flush()
            if not in_table:
                table_no += 1
                in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            src.add(" | ".join(_md_clean(c) for c in cells), kind="table-row",
                    source=name, section=section, label=f"Table {table_no}", line=i + 1)
            continue
        in_table = False
        if lm:
            flush()
            src.add(_md_clean(lm.group(1)).strip(), kind="bullet", source=name,
                    section=section, line=i + 1)
            continue
        if not line.strip():
            flush()
            continue
        if not cur:
            cur_start = i
        cur.append(line)
    flush()


def _read_plain(path: str, src: Source):
    raw = read_text(path)
    name = os.path.basename(path)
    section = None
    for i, block in enumerate(_split_blocks(raw)):
        kind, clean = _classify_block(block)
        if kind == "heading":
            section = one_line(clean)[:60]
        src.add(clean, kind=kind, source=name, section=section, line=None, para=i)


def _read_html(path: str, src: Source):
    import html as _html
    raw = read_text(path)
    name = os.path.basename(path)
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|table|figure)>", "\n\n", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n- ", raw)
    raw = re.sub(r"(?is)<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    txt = _html.unescape(raw)
    section = None
    for i, block in enumerate(_split_blocks(txt)):
        kind, clean = _classify_block(block)
        if kind == "heading":
            section = one_line(clean)[:60]
        src.add(clean, kind=kind, source=name, section=section, para=i)


def _read_docx(path: str, src: Source):
    from docx import Document
    doc = Document(path)
    name = os.path.basename(path)
    section = None
    para_i = 0
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        kind = "heading" if style.startswith("heading") or style.startswith("title") else "para"
        if kind == "heading":
            section = one_line(text)[:60]
        else:
            kind, text = _classify_block(text)
        src.add(text, kind=kind, source=name, section=section, para=para_i)
        para_i += 1
    for ti, table in enumerate(doc.tables, start=1):
        rows = []
        for row in table.rows:
            cells = [one_line(c.text) for c in row.cells]
            if any(cells):
                rows.append(cells)
        for ri, row in enumerate(rows):
            src.add(" | ".join(row), kind="table-row", source=name, section=section,
                    para=para_i, label=f"table{ti}")
            para_i += 1
    src.notes.append(f"{name}: docx with {len(doc.tables)} table(s)")


def _read_bib(path: str, src: Source):
    raw = read_text(path)
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),(.*?)\n\}", raw, re.S):
        key = m.group(2).strip()
        body = m.group(3)
        entry = {"type": m.group(1).lower()}
        for field in ("author", "title", "year", "journal", "booktitle", "doi", "publisher"):
            fm = re.search(r"\b" + field + r"\s*=\s*[\{\"](.*?)[\}\"]\s*,?\s*\n", body, re.S)
            if fm:
                entry[field] = one_line(re.sub(r"[{}]", "", fm.group(1)))
        src.bib[key] = entry
    if src.bib:
        src.notes.append(f"{os.path.basename(path)}: parsed {len(src.bib)} bib entries")
