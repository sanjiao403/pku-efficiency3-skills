#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# tests/contamination_check.py -- 证据污染三条件协议（可复跑）
#   python3 tests/contamination_check.py [--pkg <另一个包目录>]
#
# ① 哨兵串塞进 task.md / case.json / *.example.json / *.template.json，与真材料并置：
#    证据索引里不得出现非材料文件，且每条引文 locator 都必须落在材料集合内。
# ② 哨兵在产物（figure.svg / result.json）里出现次数必须为 0。
# ③ 对正常产物做五种篡改，复核必须**逐项变红** —— 只有这条能证明不是假绿：
#    改名 data-node / 删一个图元 / 嵌栅格 / 引文指向未读材料 / 把工单推进材料集合。
#
# 用 --pkg 指向别的包时，会自动探测其入口与复核脚本（本包同名的 scripts/apparatus.py +
# scripts/verify.py），用于"父臂 vs 新臂"对照。
import argparse, json, os, re, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SENT = "SENTINELJUNKTEXT4417"
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
C = []

MAT = """# 方法（真材料，示例，非正式答案）
| 部件 | 规格 | 数量 |
|-|-|-|
| 培养基储液瓶 Medium reservoir | 1000 mL | 1 |
| 蠕动泵 P-1 | 30 rpm | 1 |
| 氧合器 oxygenator O-1 | 1 |
| 培养腔 perfusion chamber | 37 °C | 1 |
| 废液瓶 waste bottle | 1 |

The culture medium is fed from the medium reservoir to the peristaltic pump P-1.
The peristaltic pump P-1 delivers to the oxygenator O-1.
The oxygenator O-1 is connected to the perfusion chamber.

1. 将培养基储液瓶接入蠕动泵 P-1 进口。
2. 若 pH 偏离则返回步骤 1 重新循环。
3. 结束运行并取样。
"""


def ck(name, ok, detail):
    C.append({"test": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print("[%s] %-40s %s" % ("ok  " if ok else "FAIL", name, str(detail)[:150]))


def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(t)


def verify(pkg, out, mat, case):
    v = subprocess.run([sys.executable, os.path.join(pkg, "scripts", "verify.py"),
                        "--svg", os.path.join(out, "figures", "figure.svg"),
                        "--result", os.path.join(out, "result.json"),
                        "--materials", mat, "--case", case],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=ENV, cwd=mat)
    fails = [re.match(r"\[FAIL\]\s+(\S+)", l).group(1) for l in v.stdout.splitlines()
             if re.match(r"\[FAIL\]\s+(\S+)", l)]
    return v.returncode, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default=PKG)
    a = ap.parse_args()
    pkg = os.path.abspath(a.pkg)
    tmp = tempfile.mkdtemp(prefix="contam-")
    d = os.path.join(tmp, os.path.basename(pkg))
    os.makedirs(d, exist_ok=True)
    w(os.path.join(d, "methods.md"), MAT)
    w(os.path.join(d, "task.md"), "Work order %s: score correctness.\n" % SENT)
    # 工单里除了哨兵，还塞一条"假部件表行 + 假流向句 + 假数值"：
    # 如果工单被当材料，这些会直接出现在图里（②的强判据）。
    json.dump({"case_id": "contam",
               "note": SENT + " | 反应釜 R-9 | 5 L | 1 |",
               "method_note": "The pump P-9 is connected to the reaction flask R-9.",
               "output_contract": {"elements": "array", "status": "string",
                                   "figure_svg": "editable svg " + SENT}},
              open(os.path.join(d, "case.json"), "w", encoding="utf-8"), ensure_ascii=False)
    w(os.path.join(d, "case.example.json"), json.dumps({"case_id": SENT}, ensure_ascii=False))
    w(os.path.join(d, "spec.template.json"), json.dumps({"entities": SENT}, ensure_ascii=False))
    w(os.path.join(d, "result.example.json"), json.dumps({"case_id": SENT}, ensure_ascii=False))
    case = os.path.join(d, "case.json")
    out = os.path.join(d, "o1")
    p = subprocess.run([sys.executable, os.path.join(pkg, "scripts", "apparatus.py"),
                        "--case", case, "--out", out], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=ENV, cwd=d)
    R = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
    svg = open(os.path.join(out, "figures", "figure.svg"), encoding="utf-8").read()

    # ---- ① 证据索引里不得混入工单/示例文件，引文必须落在材料内 ----
    prov = R.get("provenance") or {}
    mats = set(prov.get("materials") or [])
    nonmat = [m for m in mats if os.path.basename(m).lower() in
              ("case.json", "task.md", "case.example.json", "spec.template.json", "result.example.json")]
    locs = [(e.get("source") or {}).get("locator") for e in (R.get("elements") or [])]
    locs += [(e.get("source") or {}).get("locator") for e in (R.get("relations") or [])]
    locs = [x for x in locs if x]
    orphan = sorted({str(x).split("#")[0] for x in locs if str(x).split("#")[0] not in mats})
    excl = sorted((prov.get("excluded_workorder_files") or {}).keys())
    ck("1a.evidence_index_is_materials_only", not nonmat and bool(mats) and not orphan,
       "materials=%s non_material=%s orphan_locators=%s excluded=%s"
       % (sorted(mats), nonmat or "none", orphan or "none", excl))
    ck("1b.workorder_files_are_declared", len(excl) >= 3,
       "excluded=%s" % ["%s(%s)" % (k, v.get("role")) for k, v in
                        (prov.get("excluded_workorder_files") or {}).items()])

    # ---- ② 哨兵不得出现在产物里 ----
    graph = json.dumps({k: R.get(k) for k in ("elements", "relations", "data_mapping", "summary",
                                              "status_reason", "output_contract", "change_log")},
                       ensure_ascii=False)
    full = json.dumps(R, ensure_ascii=False)
    fake = ("R-9", "反应釜", "P-9", "5 L")
    leak = {k: svg.count(k) for k in fake if k in svg}
    ck("2.sentinel_absent_from_artifacts",
       svg.count(SENT) == 0 and graph.count(SENT) == 0 and full.count(SENT) == 0 and not leak,
       "svg=%d result_graph=%d result_full=%d fake_entity_in_svg=%s"
       % (svg.count(SENT), graph.count(SENT), full.count(SENT), leak or "none"))

    # ---- ③ 五种篡改必须逐项变红 ----
    base_rc, base_f = verify(pkg, out, d, case)
    ck("3.0.baseline_verify_green", base_rc == 0 and not base_f, "rc=%s fails=%s" % (base_rc, base_f))

    def tamper(tag, svg_fn=None, res_fn=None):
        dst = os.path.join(tmp, "t-" + tag)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(out, dst)
        if svg_fn:
            sv = os.path.join(dst, "figures", "figure.svg")
            src = open(sv, encoding="utf-8").read()      # 先读后写：open(...,"w") 会先截断
            open(sv, "w", encoding="utf-8").write(svg_fn(src))
        if res_fn:
            rp = os.path.join(dst, "result.json")
            j = json.load(open(rp, encoding="utf-8"))
            res_fn(j)
            json.dump(j, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
        return verify(pkg, dst, d, case)

    rc1, f1 = tamper("rename-id", svg_fn=lambda t: t.replace('data-node="U1"', 'data-node="U91"', 1))
    ck("3.1.data_node_renamed_goes_red", rc1 == 2 and "provenance.every_element_drawn" in f1,
       "rc=%s fails=%s" % (rc1, f1))
    rc2, f2 = tamper("drop-node", svg_fn=lambda t: re.sub(r'<rect [^>]*data-node="U1"[^>]*/>', "", t, count=1))
    ck("3.2.node_deleted_goes_red", rc2 == 2 and "provenance.every_element_drawn" in f2,
       "rc=%s fails=%s" % (rc2, f2))
    rc3, f3 = tamper("raster", svg_fn=lambda t: t.replace("</svg>",
                                                          '<image href="data:image/png;base64,AAAA"/></svg>'))
    ck("3.3.embedded_raster_goes_red", rc3 == 2 and "svg.no_raster_or_foreign" in f3,
       "rc=%s fails=%s" % (rc3, f3))

    def _badloc(j):
        j["elements"][0]["source"]["locator"] = "secret-unread.md#L1"
    rc4, f4 = tamper("bad-locator", res_fn=_badloc)
    ck("3.4.unread_material_citation_goes_red", rc4 == 2 and "provenance.locators_resolve" in f4,
       "rc=%s fails=%s" % (rc4, f4))

    def _promote(j):
        j["provenance"]["materials"] = sorted(set(j["provenance"]["materials"]) | {"task.md"})
        j["elements"][0]["source"] = {"locator": "task.md#L1", "quote": SENT}
    rc5, f5 = tamper("promote-workorder", res_fn=_promote)
    ck("3.5.workorder_promoted_goes_red", rc5 == 2 and
       ("provenance.no_workorder_sources" in f5 or "provenance.locators_resolve" in f5),
       "rc=%s fails=%s" % (rc5, f5))

    # ---- 4. QA 终检 P1：改 locator + materials 两处，不能让"从未读过的材料"当证据 ----
    def _ghost(j):
        j["provenance"]["materials"] = sorted(set(j["provenance"]["materials"]) | {"ghost.md"})
        j["elements"][0]["source"]["locator"] = "ghost.md#L1"
    rc6, f6 = tamper("ghost-material", res_fn=_ghost)
    ck("4a.ghost_material_goes_red", rc6 == 2 and "provenance.locators_exist_in_input" in f6,
       "rc=%s fails=%s" % (rc6, f6))

    def _oob(j):
        j["elements"][0]["source"]["locator"] = "methods.md#L9999"
    rc7, f7 = tamper("line-out-of-range", res_fn=_oob)
    ck("4b.line_out_of_range_goes_red", rc7 == 2 and "provenance.locator_lines_in_range" in f7,
       "rc=%s fails=%s" % (rc7, f7))

    def _fakequote(j):
        j["elements"][1]["source"]["quote"] = "这条引文在材料里根本不存在 1234"
    rc8, f8 = tamper("fabricated-quote", res_fn=_fakequote)
    ck("4c.fabricated_quote_goes_red", rc8 == 2 and "provenance.quotes_found_in_material" in f8,
       "rc=%s fails=%s" % (rc8, f8))

    rep = {"package": os.path.basename(pkg), "sentinel": SENT, "checks": C,
           "passed": sum(1 for c in C if c["ok"]), "failed": sum(1 for c in C if not c["ok"])}
    if pkg == PKG:
        open(os.path.join(HERE, "contamination-report.json"), "w", encoding="utf-8").write(
            json.dumps(rep, ensure_ascii=False, indent=2))
    print("[contam] pkg=%s passed=%d failed=%d" % (os.path.basename(pkg), rep["passed"], rep["failed"]))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if rep["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())




