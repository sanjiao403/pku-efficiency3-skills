#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# tests/selftest.py -- 本包自检：**全部真跑**（不用 mock、不预置答案），结果写 tests/selftest-report.json
#   python3 tests/selftest.py            # 退出码 0 = 全部通过，2 = 有失败
#
# 覆盖 8 组断言：
#   A determinism        同输入两次逐字节一致；产物目录即使落在材料目录里也不会被当材料（自喂）
#   B workorder-negative 工单/示例文件里的数字与名词不得进证据索引（负向对照）
#   C verifier-bites     篡改三连（剥 data-role / 塞材料外数字 / 删一个图元）必须被判红
#   D degradation        无可画内容 -> partial；无渲染后端 -> partial 且仍交 SVG
#   E contract           output_contract 声明的字段必须出现在 result.json 顶层 + 四段契约齐全
#   F bail               顶层异常也要留下诚实的 partial result.json
#   G pdf-stdlib         纯标准库 PDF 文本层抽取（现场造一个纯文本 PDF，屏蔽 pymupdf）
#   H no-absolute-path   产物里不得出现本机绝对路径
import json, os, re, shutil, subprocess, sys, tempfile, time, traceback

sys.dont_write_bytecode = True
PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCR = tempfile.mkdtemp(prefix="apparatus-adv1-selftest-")
PY = sys.executable
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
C = []


def ck(name, ok, detail):
    C.append({"test": name, "ok": bool(ok), "detail": str(detail)[:400]})
    print("[%s] %-32s %s" % ("ok  " if ok else "FAIL", name, str(detail)[:160]))


def run_entry(case, out, env=None):
    e = dict(ENV, **(env or {}))
    p = subprocess.run([PY, os.path.join(PKG, "scripts", "apparatus.py"), "--case", case, "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=SCR)
    rp = os.path.join(out, "result.json")
    R = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else {}
    return p, R


def run_verify(out, matdir, case="", env=None):
    e = dict(ENV, **(env or {}))
    a = [PY, os.path.join(PKG, "scripts", "verify.py"), "--svg", os.path.join(out, "figures", "figure.svg"),
         "--result", os.path.join(out, "result.json"), "--materials", matdir]
    if case:
        a += ["--case", case]
    v = subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, cwd=SCR)
    fails = [re.match(r"\[FAIL\]\s+(\S+)", l).group(1) for l in v.stdout.splitlines()
             if l.startswith("[FAIL]") and re.match(r"\[FAIL\]\s+(\S+)", l)]
    return v, fails


def mkcase(d, cid, mat=None, kind="schematic", contract=True):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    if mat:
        open(os.path.join(d, "material.md"), "w", encoding="utf-8").write(mat[1])
    c = {"case_id": cid, "title": "自检案例 %s（示例，非正式答案）" % cid, "figure_kind": kind}
    if contract:
        c["output_contract"] = {"case_id": "string", "status": "string", "elements": "array",
                                "relations": "array", "data_mapping": "array",
                                "editable_source": "object", "exports": "array",
                                "provenance": "object", "checks": "object", "uncertainty": "array",
                                "sources": "array"}
    json.dump(c, open(os.path.join(d, "case.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return os.path.join(d, "case.json")


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


MAT = ("material.md", """# 自检材料（示例，非正式答案）
| 部件 | 规格 | 数量 |
|-|-|-|
| 培养基储液瓶 Medium reservoir | 1000 mL | 1 |
| 蠕动泵 P-1 | 30 rpm | 1 |
| 氧合器 oxygenator O-1 | 1 |
| 培养腔 perfusion chamber | 37 °C | 1 |
| 废液瓶 waste bottle | 1 |

The culture medium is fed from the medium reservoir to the peristaltic pump P-1.
The peristaltic pump P-1 delivers to the oxygenator O-1.

1. 将培养基储液瓶接入蠕动泵 P-1 进口。
2. 若 pH 偏离则返回步骤 1 重新循环。
3. 结束运行并取样。
""")

# ---------- A determinism ----------
d = os.path.join(SCR, "det")
case = mkcase(d, "det", MAT)
p1, R1 = run_entry(case, os.path.join(SCR, "det-o1"))
p2, R2 = run_entry(case, os.path.join(SCR, "det-o2"))
s1 = sha(os.path.join(SCR, "det-o1", "figures", "figure.svg"))
s2 = sha(os.path.join(SCR, "det-o2", "figures", "figure.svg"))
ck("A1.deterministic_svg", s1 == s2 and R1.get("status") == "success", "sha1=%s sha2=%s status=%s"
   % (s1[:12], s2[:12], R1.get("status")))
# 产物目录落在材料目录里：第二次运行不得把上一次产物当材料
p3, R3 = run_entry(case, os.path.join(d, "out1"))
p4, R4 = run_entry(case, os.path.join(d, "out1"))
mats = (R4.get("provenance") or {}).get("materials") or []
self_fed = [m for m in mats if "out1" in m]
s4 = sha(os.path.join(d, "out1", "figures", "figure.svg"))
ck("A2.no_self_feed", not self_fed and s4 == s1, "materials=%s self_fed=%s sha_same=%s"
   % (mats, self_fed, s4 == s1))

# ---------- B workorder negative control ----------
wd = os.path.join(SCR, "wo")
os.makedirs(wd)
json.dump({"case_id": "wo-only", "title": "工单（示例，非正式答案）",
           "task": "请用 5 L 反应釜与蠕动泵 P-9 画出 Phase 1 装置，温度 88 °C。",
           "output_contract": {"case_id": "string", "status": "string", "elements": "array"}},
          open(os.path.join(wd, "case.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
p5, R5 = run_entry(os.path.join(wd, "case.json"), os.path.join(wd, "out"))
svg5 = open(os.path.join(wd, "out", "figures", "figure.svg"), encoding="utf-8").read()
leaked = [t for t in ("5 L", "反应釜", "P-9", "蠕动泵") if t in svg5]
excl = (R5.get("provenance") or {}).get("excluded_workorder_files") or {}
ck("B1.workorder_not_evidence", R5.get("status") == "partial" and not (R5.get("elements") or [])
   and not leaked and "case.json" in excl and
   ((R5.get("checks") or {}).get("evidence_scope") or {}).get("material_files") == 0,
   "status=%s elements=%d leaked_in_svg=%s excluded=%s"
   % (R5.get("status"), len(R5.get("elements") or []), leaked, sorted(excl.keys())))

# ---------- C verifier bites ----------
v0, f0 = run_verify(os.path.join(SCR, "det-o1"), d, case)
ck("C0.verify_green_baseline", v0.returncode == 0 and not f0, "rc=%s fails=%s" % (v0.returncode, f0))


def tamper(tag, fn):
    src = os.path.join(SCR, "det-o1")
    dst = os.path.join(SCR, "tamper-" + tag)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    sv = os.path.join(dst, "figures", "figure.svg")
    t = open(sv, encoding="utf-8").read()
    open(sv, "w", encoding="utf-8").write(fn(t))
    v, f = run_verify(dst, d, case)
    return v, f


v1, f1 = tamper("role", lambda t: t.replace(" data-role=", " role="))
ck("C1.bites_on_stripped_data_role", v1.returncode == 2 and
   any(x.startswith("provenance") or x.startswith("arrow") for x in f1), "rc=%s fails=%s" % (v1.returncode, f1))
v2, f2 = tamper("num", lambda t: re.sub(r"(<text[^>]*data-role=\"node-label\"[^>]*>)([^<]*)",
                                        r"\1\g<2> 4242", t, count=1))
ck("C2.bites_on_invented_number", v2.returncode == 2 and "provenance.no_invented_numbers" in f2,
   "rc=%s fails=%s" % (v2.returncode, f2))
v3, f3 = tamper("elem", lambda t: re.sub(r'<rect [^>]*data-node="U1"[^>]*/>', "", t, count=1))
ck("C3.bites_on_missing_element", v3.returncode == 2 and "provenance.every_element_drawn" in f3,
   "rc=%s fails=%s" % (v3.returncode, f3))

# ---------- D degradation ----------
bd = os.path.join(SCR, "empty")
c6 = mkcase(bd, "empty", ("material.md", "这是一段没有任何装置清单/编号步骤/阶段标记的描述。\n"))
p6, R6 = run_entry(c6, os.path.join(bd, "out"))
v6, f6 = run_verify(os.path.join(bd, "out"), bd, c6)
ck("D1.empty_is_partial_not_crash", R6.get("status") == "partial" and not (R6.get("elements") or [])
   and v6.returncode == 0, "status=%s elements=%d verify_rc=%s fails=%s"
   % (R6.get("status"), len(R6.get("elements") or []), v6.returncode, f6))
nb = os.path.join(SCR, "nobackend")
os.makedirs(nb, exist_ok=True)
open(os.path.join(nb, "fitz.py"), "w").write('raise ImportError("blocked-in-selftest")\n')
p7, R7 = run_entry(case, os.path.join(SCR, "det-nb"), env={"PYTHONPATH": nb})
ck("D2.no_backend_still_svg", R7.get("status") == "partial"
   and os.path.exists(os.path.join(SCR, "det-nb", "figures", "figure.svg"))
   and not os.path.exists(os.path.join(SCR, "det-nb", "figures", "figure.pdf")),
   "status=%s notes=%s" % (R7.get("status"), (R7.get("checks") or {}).get("render", {}).get("notes", [])[:1]))

# ---------- E contract ----------
decl = set(json.load(open(case, encoding="utf-8"))["output_contract"])
miss = sorted(k for k in decl if k not in R1)
oc = R1.get("output_contract") or {}
ck("E1.contract_fields_present", not miss and all(
    k in oc for k in ("editable_sources", "exports", "data_mapping", "element_traceability")),
   "declared=%d missing=%s sections=%s" % (len(decl), miss, sorted(oc)))
ck("E2.contract_echo_explains", all(isinstance(v, str) and v for v in (R1.get("contract_echo") or {}).values()),
   "echo=%d" % len(R1.get("contract_echo") or {}))

# ---------- F bail ----------
sys.path.insert(0, os.path.join(PKG, "scripts"))
import apparatus  # noqa: E402
bd2 = os.path.join(SCR, "bail")
os.makedirs(bd2, exist_ok=True)
apparatus._bail(case, bd2, "Traceback (most recent call last):\n  File x\nRuntimeError: smoke-test-error\n")
B = json.load(open(os.path.join(bd2, "result.json"), encoding="utf-8"))
ck("F1.bail_writes_honest_result", B.get("status") == "partial" and any("smoke-test-error" in x for x in (B.get("error") or [])),
   "status=%s error=%s" % (B.get("status"), (B.get("error") or [])[-1:]))

# ---------- G pdf via stdlib only ----------
pdfd = os.path.join(SCR, "pdfcase")
os.makedirs(pdfd, exist_ok=True)
lines = ["| Medium reservoir | 1000 mL | 1 |", "| oxygenator O-1 | 1 |", "| waste bottle | 1 |",
         "The medium reservoir is connected to the oxygenator O-1.",
         "The oxygenator O-1 is connected to the waste bottle."]
cs = "".join("BT /F1 10 Tf 50 %d Td (%s) Tj ET\n" % (800 - i * 16, t.replace("(", r"\(").replace(")", r"\)"))
            for i, t in enumerate(lines)).encode("latin-1")
obj = b""
pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
pdf += b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
pdf += b"4 0 obj<</Length " + str(len(cs)).encode() + b">>stream\n" + cs + b"endstream endobj\n"
pdf += b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF\n"
open(os.path.join(pdfd, "material.pdf"), "wb").write(pdf)
json.dump({"case_id": "pdf-only", "title": "PDF 自检（示例，非正式答案）", "figure_kind": "schematic"},
          open(os.path.join(pdfd, "case.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
p8, R8 = run_entry(os.path.join(pdfd, "case.json"), os.path.join(pdfd, "out"), env={"PYTHONPATH": nb})
ex8 = ((R8.get("provenance") or {}).get("extractors") or {})
ck("G1.pdf_stdlib_fallback", len(R8.get("elements") or []) >= 3
   and ex8.get("material.pdf") == "pdftext-stdlib",
   "elements=%d extractor=%s unreadable=%s" % (len(R8.get("elements") or []), ex8,
                                               (R8.get("provenance") or {}).get("unreadable")))

# ---------- I 三格式导出：字节级重测 + 两种负向对照 + 源文件保留式编辑 ----------
exf = (R1.get("checks") or {}).get("exports") or {}
ck("I1.three_formats_measured", bool(exf.get("ok"))
   and exf.get("pdf", {}).get("page_matches_canvas")
   and exf.get("pdf", {}).get("images") == 0
   and exf.get("png", {}).get("px_matches_dpi")
   and exf.get("png", {}).get("dpi") == [300.0, 300.0]
   and (exf.get("render") or {}).get("glyph_ink_rate") == 1.0
   and exf.get("pdf", {}).get("text_ops", 0) > 0,
   "pdf_page=%s image_xo=%s text_ops=%s png_dpi=%s ink=%s"
   % (exf.get("pdf", {}).get("page_mm"), exf.get("pdf", {}).get("images"),
      exf.get("pdf", {}).get("text_ops"), exf.get("png", {}).get("dpi"),
      (exf.get("render") or {}).get("glyph_ink_rate")))
ck("I1b.text_ops_measured_on_inflated_streams",
   (exf.get("pdf", {}).get("text_ops") or 0) > (exf.get("pdf", {}).get("text_ops_raw_compressed_scan") or 0),
   "inflated text_ops=%s vs compressed-scan=%s (D40 口径：必须 inflate 后数)"
   % (exf.get("pdf", {}).get("text_ops"), exf.get("pdf", {}).get("text_ops_raw_compressed_scan")))
ck("I1c.unicode_text_extraction", (exf.get("pdf", {}).get("unicode_chars") or 0) > 0
   and (exf.get("render") or {}).get("coverage", 0) >= 0.85,
   "source=%s unicode_chars=%s cjk=%s coverage=%s"
   % (exf.get("pdf", {}).get("text_source"), exf.get("pdf", {}).get("unicode_chars"),
      exf.get("pdf", {}).get("unicode_cjk"), (exf.get("render") or {}).get("coverage")))


def tamper_files(tag, fn):
    dst = os.path.join(SCR, "tf-" + tag)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(SCR, "det-o1"), dst)
    fn(dst)
    v, f = run_verify(dst, d, case)
    return v, f


def _strip_phys(dst):
    p = os.path.join(dst, "figures", "figure.png")
    b = open(p, "rb").read()
    i = b.find(b"pHYs")
    with open(p, "wb") as fh:
        fh.write(b[:i - 4] + b[i + 13 + 4:] if i > 0 else b)     # 去掉整个 pHYs chunk


v4, f4 = tamper_files("nophys", _strip_phys)
ck("I2.bites_on_png_dpi_tag", v4.returncode == 2 and "export.png_dpi_tag" in f4,
   "rc=%s fails=%s" % (v4.returncode, f4))


def _add_raster(dst):
    p = os.path.join(dst, "figures", "figure.pdf")
    b = open(p, "rb").read()
    open(p, "wb").write(b.replace(b"%%EOF", b"1 0 obj\n<< /Subtype /Image /Width 1 >>\nendobj\n%%EOF", 1))


v5, f5 = tamper_files("rasterpdf", _add_raster)
ck("I3.bites_on_raster_in_pdf", v5.returncode == 2 and "export.pdf_vector_no_raster" in f5,
   "rc=%s fails=%s" % (v5.returncode, f5))

# 源文件保留式编辑：改一个标注 -> 1/总数 变化，其余逐字节不变，且改后仍能过复核
ed = subprocess.run([PY, os.path.join(PKG, "scripts", "edit.py"), "--svg",
                     os.path.join(SCR, "det-o1", "figures", "figure.svg"),
                     "--out", os.path.join(SCR, "det-o1", "figures", "figure.edited.svg"),
                     "--set-text", "U1", "自检改动后的标注"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=ENV, cwd=SCR)
E = json.loads(ed.stdout.strip().splitlines()[-1]) if ed.stdout.strip() else {}
ck("I4.source_preserving_edit", bool(E.get("ok")) and E.get("lines_changed") == 1
   and E.get("byte_identical_outside_target") is True and E.get("structure_preserved") is True,
   "lines_changed=%s outside_identical=%s structure=%s total_lines=%s"
   % (E.get("lines_changed"), E.get("byte_identical_outside_target"),
      E.get("structure_preserved"), E.get("total_lines")))
ve, fe = None, []
ve = subprocess.run([PY, os.path.join(PKG, "scripts", "verify.py"),
                     "--svg", os.path.join(SCR, "det-o1", "figures", "figure.svg"),
                     "--result", os.path.join(SCR, "det-o1", "result.json"),
                     "--materials", d, "--case", case,
                     "--edited", os.path.join(SCR, "det-o1", "figures", "figure.edited.svg")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV, cwd=SCR)
fe = [re.match(r"\[FAIL\]\s+(\S+)", l).group(1) for l in ve.stdout.splitlines()
      if re.match(r"\[FAIL\]\s+(\S+)", l)]
ck("I5.edited_figure_still_verifies", ve.returncode == 0 and not fe,
   "rc=%s fails=%s" % (ve.returncode, fe))

# I6/I7：表现层属性可改且行级字节只动 1 行；溯源字段默认拒改（改引文=改证据来源）
ok_attr = subprocess.run([PY, os.path.join(PKG, "scripts", "edit.py"), "--svg",
                          os.path.join(SCR, "det-o1", "figures", "figure.svg"),
                          "--out", os.path.join(SCR, "det-o1", "figures", "figure.fill.svg"),
                          "--set-attr", "U1", "fill", "#123456"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=ENV, cwd=SCR)
EA = json.loads(ok_attr.stdout.strip().splitlines()[-1]) if ok_attr.stdout.strip() else {}
ck("I6.presentation_attr_edit_line_surgical", bool(EA.get("ok"))
   and EA.get("lines_changed") == 1 and EA.get("byte_identical_outside_target") is True,
   "ok=%s lines_changed=%s outside_identical=%s" % (EA.get("ok"), EA.get("lines_changed"),
                                                    EA.get("byte_identical_outside_target")))
bad_attr = subprocess.run([PY, os.path.join(PKG, "scripts", "edit.py"), "--svg",
                           os.path.join(SCR, "det-o1", "figures", "figure.svg"),
                           "--out", os.path.join(SCR, "det-o1", "figures", "figure.pq.svg"),
                           "--set-attr", "E1", "data-quote", "x"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=ENV, cwd=SCR)
EP = json.loads(bad_attr.stdout.strip().splitlines()[-1]) if bad_attr.stdout.strip() else {}
ck("I7.provenance_attr_edit_refused", bad_attr.returncode == 2 and EP.get("provenance_changed") is True,
   "rc=%s why=%s" % (bad_attr.returncode, (EP.get("why") or "")[:60]))

# ---------- H no absolute paths in outputs ----------
bad_abs = []
for dp, _s, fs in os.walk(SCR):
    for f in fs:
        if f.endswith((".json", ".svg", ".md")):
            t = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
            if re.search(r"[A-Za-z]:\\\\?Users|[A-Za-z]:\\\\?Desktop", t):
                bad_abs.append(os.path.relpath(os.path.join(dp, f), SCR))
ck("H1.no_absolute_paths", not bad_abs, bad_abs[:4])

rep = {"package": os.path.basename(PKG), "python": sys.version.split()[0], "checks": C,
       "passed": sum(1 for c in C if c["ok"]), "failed": sum(1 for c in C if not c["ok"])}
open(os.path.join(PKG, "tests", "selftest-report.json"), "w", encoding="utf-8").write(
    json.dumps(rep, ensure_ascii=False, indent=2))
print("[selftest] passed=%d failed=%d  report=tests/selftest-report.json"
      % (rep["passed"], rep["failed"]))
shutil.rmtree(SCR, ignore_errors=True)
sys.exit(0 if rep["failed"] == 0 else 2)


