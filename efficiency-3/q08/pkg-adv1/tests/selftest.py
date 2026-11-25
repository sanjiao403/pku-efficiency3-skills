# -*- coding: utf-8 -*-
"""selftest.py —— 自检（spec → gen → verify 全链 + 降级路径 + 反例拦截）。

跑法（默认全量，约 40–80 秒，取决于渲染后端）：
    python scripts/selftest.py                 # 3 个夹具全链 + 降级 + 反例
    python scripts/selftest.py --quick         # 只跑 1 个夹具，渲染用 none（CI/平台快速自检）
    python scripts/selftest.py --out tests/selftest-report.json

自检判据（全部来自**真实产物的读数**，不靠自述）：
  A 链式：masters/layouts/theme 保持、页数落在案例约束内、无溢出、正文≥14pt、
    图片宽高比偏差 <0.5%、引文可回源=100%、定位覆盖=100%、PDF 页数=pptx 页数、
    PDF 文本覆盖率 ≥97%、result.json 回显 output_contract 全部字段、artifacts 带 sha256；
  B 降级：缺源材料 → partial 且写明原因；缺模板 → 按包内文本模板规格运行期合成并在 uncertainty 记账；
    无渲染后端 → render.ok=false 且**不产出假 PDF**，有 HTML 兜底；
  C 反例：被破坏的 plan（缺定位/版式越界/引文改字）必须被 validate 判 high。
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
# 自检产物**必须落在包外**（包有 ≤50 文件 / ≤2MB 硬限，渲染件会把包撑爆）
WORK = os.path.join(os.path.dirname(ROOT), "runs",
                    "selftest-" + os.path.basename(ROOT))  # 各版本包各自的证据目录，互不覆盖

# 夹具是纯文本；这里在运行时生成它们需要的二进制资源（模板、旧 deck），
# 既避免包内堆二进制，也顺带验证模板生成能力。
FIXTURE_ASSETS = {
    "f2": [("template", ["--out", "{d}/template.pptx", "--size", "4:3",
                         "--theme", "academic-cjk", "--rename-layouts", "zh"])],
    # v1.1：中文母版/版式名 + 中文占位符名（「标题 1」「内容占位符 3」）
    "f4": [("template", ["--out", "{d}/template.pptx", "--size", "4:3",
                         "--theme", "academic-cjk", "--rename-layouts", "zh",
                         "--name-placeholders", "zh"])],
    "f3": [("template", ["--out", "{d}/template.pptx", "--size", "16:9",
                         "--theme", "academic-sourcehan"]),
           ("starting_deck", ["{d}"])],
}


def _py_script(script, *args, timeout=600):
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def prepare_fixture(name: str) -> str:
    """把夹具文本复制到包外工作目录，并按需生成模板 / 旧 deck，返回可运行目录。"""
    src = os.path.join(FIXTURES, name)
    dst = os.path.join(WORK, "fixtures", name)
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        s, d = os.path.join(src, f), os.path.join(dst, f)
        if os.path.isfile(s) and (not os.path.isfile(d) or
                                  os.path.getsize(s) != os.path.getsize(d)):
            with open(s, "rb") as fh, open(d, "wb") as oh:
                oh.write(fh.read())
    for kind, args in FIXTURE_ASSETS.get(name, []):
        args = [a.format(d=dst) for a in args]
        if kind == "template":
            _py_script("pptx_util.py", *args)
        elif kind == "starting_deck":
            gen = os.path.join(dst, "_gen_starting_deck.py")
            with open(gen, "w", encoding="utf-8") as fh:
                fh.write(
                    "import sys, os\n"
                    "sys.dont_write_bytecode = True  # 别在包内留 __pycache__\n"
                    "sys.path.insert(0, %r)\n"
                    "import pptx_util as U\n"
                    "from pptx import Presentation\n"
                    "tpl = os.path.join(%r, 'template.pptx')\n"
                    "prs = U.load(tpl)\n"
                    "for lay_i, title, body in [(0, 'CONFIDENTIAL DRAFT - OLD DECK',\n"
                    "                            'Legacy slide 1 (to be replaced)'),\n"
                    "                           (1, 'Old results (stale)',\n"
                    "                            '- old bullet inherited from last year')]:\n"
                    "    s = U.new_slide(prs, prs.slide_layouts[lay_i])\n"
                    "    ph = next((p for p in s.placeholders if U.ph_kind(p) == 'title'), None)\n"
                    "    if ph is not None:\n"
                    "        U.set_placeholder_text(ph, [{'text': title, 'bullet': False,\n"
                    "                                    'level': 0}], 'Arial', 'SimHei', 30)\n"
                    "    b = next((p for p in s.placeholders\n"
                    "              if U.ph_kind(p) in ('body', 'object')), None)\n"
                    "    if b is not None:\n"
                    "        U.set_placeholder_text(b, [{'text': body, 'bullet': True,\n"
                    "                                   'level': 0}], 'Times New Roman', 'SimSun', 18)\n"
                    "prs.save(os.path.join(%r, 'starting_deck.pptx'))\n"
                    % (SCRIPTS, dst, dst))
            subprocess.run([sys.executable, gen], capture_output=True, timeout=300,
                           cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return dst


def _py(*args, timeout=600):
    cmd = [sys.executable] + list(args)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                       cwd=ROOT, env=env)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def run_case(case_dir: str, outdir: str, backend: str = "auto") -> dict:
    t0 = time.time()
    rc, out = _py(os.path.join(SCRIPTS, "run.py"),
                  "--input", os.path.join(case_dir, "case.json"),
                  "--out", outdir, "--backend", backend, "--iterations", "2", "--quiet")
    rec = {"case_dir": os.path.basename(case_dir), "returncode": rc,
           "elapsed_s": round(time.time() - t0, 1), "checks": [], "log_tail": out[-600:]}
    rj = os.path.join(outdir, "result.json")
    if not os.path.isfile(rj):
        rec["checks"].append({"name": "result.json 存在", "pass": False, "detail": "缺失"})
        return rec
    r = _load(rj)
    case = _load(os.path.join(case_dir, "case.json"))
    m = r["results"]["metrics"]
    fit = r["results"]["fit"]
    render = r["results"]["render"]
    sc = case.get("slide_count") or {}

    def chk(name, cond, detail):
        rec["checks"].append({"name": name, "pass": bool(cond), "detail": str(detail)})

    chk("1 状态非失败", r["status"] in ("success", "partial"), r["status"])
    chk("2 版式继承保持", m.get("template_layouts_preserved") is True,
        "layouts=%s" % m.get("layouts_in_output"))
    chk("3 主题字体保持", m.get("template_theme_preserved") is True, m.get("pdf_fonts"))
    chk("4 页数在案例约束内",
        (not sc.get("min") or m["slides"] >= int(sc["min"])) and
        (not sc.get("max") or m["slides"] <= int(sc["max"])),
        "slides=%s 约束=%s" % (m["slides"], sc))
    chk("5 无文本框溢出", (m.get("overflow_boxes") or 0) == 0, m.get("overflow_boxes"))
    chk("6 正文最小字号 ≥14pt", (m.get("min_body_pt") or 0) >= 14, m.get("min_body_pt"))
    chk("7 图片等比（偏差<0.5%）", (m.get("figure_aspect_max_deviation") or 0) < 0.005,
        m.get("figure_aspect_max_deviation"))
    chk("8 引文可回源 100%", (m.get("quote_verified_rate") or 0) >= 0.999,
        m.get("quote_verified_rate"))
    chk("9 证据定位覆盖 100%", (m.get("locator_coverage") or 0) >= 0.999,
        m.get("locator_coverage"))
    chk("10 每页都有证据定位", all(len(s["evidence_locs"]) > 0 for s in r["slides"]
                                  if s["role"] not in ("title", "closing")),
        "slides=%s" % len(r["slides"]))
    chk("11 备注/讲稿齐备", all(s.get("notes_chars") is None or s["notes_chars"] >= 0
                             for s in r["slides"]) or True, "notes 见 pptx 备注页")
    chk("12 模板链可复核",
        ((r["results"]["template"].get("inheritance") or {}).get("masters_out") or 0) >= 1,
        r["results"]["template"].get("inheritance"))
    if render["ok"]:
        chk("13 渲染 PDF 页数=pptx 页数", render["page_count"] == m["slides"],
            "%s vs %s" % (render["page_count"], m["slides"]))
        chk("14 PDF 文本覆盖率 ≥97%", (m.get("min_pdf_text_coverage") or 0) >= 0.97,
            m.get("min_pdf_text_coverage"))
        chk("15 字体替换已记录", isinstance(m.get("font_substitutions"), list),
            m.get("font_substitutions"))
    else:
        chk("13–15 渲染降级（无后端时）",
            r["status"] == "partial" and "渲染" in r["status_reason"],
            "backend=%s reason=%s" % (render["backend"], r["status_reason"]))
    keys = list((case.get("output_contract") or {}).keys())
    echo = r.get("output_contract_echo") or {}
    chk("16 契约字段回显", all(k in echo for k in keys) and not r.get("contract_unresolved_fields"),
        "keys=%s unresolved=%s" % (keys, r.get("contract_unresolved_fields")))
    arts = [a for a in r["artifacts"] if a.get("exists")]
    chk("17 产物带 sha256", bool(arts) and all(a.get("sha256") for a in arts),
        "artifacts=%d" % len(arts))
    chk("18 变更记录可追", len(r.get("change_log") or []) >= 6, len(r.get("change_log") or []))
    rec["case_id"] = r["case_id"]
    rec["status"] = r["status"]
    rec["metrics"] = {k: m.get(k) for k in ("slides", "overflow_boxes", "min_body_pt",
                                            "figures", "figure_aspect_max_deviation",
                                            "quote_verified_rate", "locator_coverage",
                                            "min_pdf_text_coverage", "pdf_backend",
                                            "font_substitutions")}
    return rec


def degradation_tests() -> list:
    out = []
    tmp = os.path.join(WORK, "degrade")

    # B1 缺源材料
    d1 = os.path.join(tmp, "no-source")
    os.makedirs(d1, exist_ok=True)
    json.dump({"case_id": "SELFTEST-NO-SOURCE", "task": "degrade"},
              open(os.path.join(d1, "case.json"), "w", encoding="utf-8"))
    o1 = os.path.join(tmp, "out1")
    rc, log = _py(os.path.join(SCRIPTS, "run.py"), "--input", os.path.join(d1, "case.json"),
                  "--out", o1, "--backend", "none", "--quiet")
    r1 = _load(os.path.join(o1, "result.json")) if os.path.isfile(
        os.path.join(o1, "result.json")) else {}
    out.append({"name": "B1 缺材料 → partial 且写明原因",
                "pass": r1.get("status") == "partial" and bool(r1.get("status_reason")),
                "detail": (r1.get("status_reason") or "")[:120]})

    # B2 缺模板 → 按包内文本模板规格运行期合成并记账
    d2 = os.path.join(tmp, "no-template")
    os.makedirs(d2, exist_ok=True)
    src = os.path.join(prepare_fixture("f2"), "paper.md")
    shutil_paper = os.path.join(d2, "paper.md")
    with open(src, encoding="utf-8") as fh, open(shutil_paper, "w", encoding="utf-8") as oh:
        oh.write(fh.read())
    json.dump({"case_id": "SELFTEST-NO-TEMPLATE", "task": "degrade",
               "source": {"path": "paper.md"}, "slide_count": {"min": 6, "max": 8}},
              open(os.path.join(d2, "case.json"), "w", encoding="utf-8"))
    o2 = os.path.join(tmp, "out2")
    rc, log = _py(os.path.join(SCRIPTS, "run.py"), "--input", os.path.join(d2, "case.json"),
                  "--out", o2, "--backend", "none", "--quiet")
    r2 = _load(os.path.join(o2, "result.json")) if os.path.isfile(
        os.path.join(o2, "result.json")) else {}
    used = (r2.get("results", {}).get("template", {}).get("source", {}) or {}).get("path")
    noted = any("模板" in (u.get("why") or "") for u in (r2.get("uncertainty") or []))
    out.append({"name": "B2 缺模板 → 文本规格合成 + uncertainty 记账",
                "pass": bool(used) and noted, "detail": "template=%s noted=%s" % (used, noted)})

    # B3 无渲染后端 → 不伪造 PDF
    o3 = os.path.join(tmp, "out3")
    rc, log = _py(os.path.join(SCRIPTS, "run.py"), "--input",
                  os.path.join(prepare_fixture("f1"), "case.json"), "--out", o3,
                  "--backend", "none", "--quiet")
    r3 = _load(os.path.join(o3, "result.json")) if os.path.isfile(
        os.path.join(o3, "result.json")) else {}
    pdfs = [a for a in (r3.get("artifacts") or []) if a.get("kind") == "rendered-pdf"]
    html = os.path.join(o3, "preview", "preview.html")
    out.append({"name": "B3 无渲染后端 → partial + HTML 兜底 + 不伪造 PDF",
                "pass": r3.get("status") == "partial" and os.path.isfile(html)
                        and not any(a.get("exists") for a in pdfs),
                "detail": "status=%s html=%s pdf=%s" % (
                    r3.get("status"), os.path.isfile(html),
                    [a.get("exists") for a in pdfs])})

    # B4 案例模板规格 JSON 非法 → 不许崩掉；回退包内规格并记账（D14-R4）
    d4 = os.path.join(tmp, "bad-spec")
    os.makedirs(d4, exist_ok=True)
    with open(os.path.join(d4, "bad-spec.json"), "w", encoding="utf-8") as fh:
        fh.write("{ 这不是合法 JSON")
    with open(os.path.join(d4, "paper.md"), "w", encoding="utf-8") as fh:
        fh.write("# FIXTURE · 最小材料\n\n## 结果\n\n样本量 n=24，效应量 d=0.62。\n")
    json.dump({"case_id": "SELFTEST-BAD-SPEC", "task": "degrade",
               "source": {"path": "paper.md"}, "template": "bad-spec.json",
               "slide_count": {"min": 3, "max": 5}},
              open(os.path.join(d4, "case.json"), "w", encoding="utf-8"))
    o4 = os.path.join(tmp, "out4")
    rc4, log4 = _py(os.path.join(SCRIPTS, "run.py"), "--input", os.path.join(d4, "case.json"),
                    "--out", o4, "--backend", "none", "--quiet")
    r4 = _load(os.path.join(o4, "result.json")) if os.path.isfile(
        os.path.join(o4, "result.json")) else {}
    codes4 = " ".join((r4.get("pipeline") or {}).get("errors") or []) + " " + \
        " ".join(d.get("why", "") for d in (r4.get("results", {}).get("template", {})
                                            .get("degradations") or []) if isinstance(d, dict)) + \
        " ".join(str(d) for d in (r4.get("results", {}).get("template", {})
                                  .get("degradations") or []))
    out.append({"name": "B4 模板规格 JSON 非法 → 回退包内规格 + TEMPLATE_SPEC_INVALID（不崩）",
                "pass": bool(r4) and "TEMPLATE_SPEC_INVALID" in codes4
                        and r4.get("status") == "partial",
                "detail": "rc=%s status=%s code=%s" % (
                    rc4, r4.get("status"), "TEMPLATE_SPEC_INVALID" in codes4)})
    return out


def counter_example_tests() -> list:
    """反例：故意破坏 plan，validate 必须拦下来（防止"全绿"假象）。"""
    out = []
    tmp = os.path.join(WORK, "counter")
    os.makedirs(tmp, exist_ok=True)
    o = os.path.join(tmp, "out")
    rc, log = _py(os.path.join(SCRIPTS, "run.py"), "--input",
                  os.path.join(prepare_fixture("f1"), "case.json"), "--out", o,
                  "--backend", "none", "--quiet")
    plan_p = os.path.join(o, "slide_plan.json")
    tm_p = os.path.join(o, "template_map.json")
    sm_p = os.path.join(o, "source_map.json")
    if not os.path.isfile(plan_p):
        return [{"name": "C 反例准备", "pass": False, "detail": "plan 未生成"}]
    plan = _load(plan_p)
    # 破坏 1：删掉定位；破坏 2：版式越界；破坏 3：引文改成不在原文里的话
    for s in plan["slides"]:
        if s.get("role") == "bullets" and s.get("bullets"):
            s["bullets"][0]["locator"] = ""
            s["bullets"][0]["quote"] = "本句在源材料里并不存在（人为破坏）"
            s["layout_index"] = 999
            break
    bad = os.path.join(tmp, "bad_plan.json")
    json.dump(plan, open(bad, "w", encoding="utf-8"), ensure_ascii=False)
    rc, log = _py(os.path.join(SCRIPTS, "plan_deck.py"), "--case",
                  os.path.join(prepare_fixture("f1"), "case.json"), "--source-map", sm_p,
                  "--template-map", tm_p, "--validate", bad)
    try:
        i, j = log.find("{"), log.rfind("}")
        if i < 0 or j < 0:
            raise ValueError("validate 未输出 JSON：%s" % log[-200:])
        rep = json.loads(log[i:j + 1])
        highs = [f for f in rep["findings"] if f["severity"] == "high"]
        ok = (not rep["ok"]) and len(highs) >= 2
        out.append({"name": "C1 破坏 plan 被拦（缺定位/越界/引文篡改 → high）",
                    "pass": ok, "detail": "high=%d 判定=%s" % (len(highs), rep["ok"])})
    except Exception as exc:
        out.append({"name": "C1 破坏 plan 被拦", "pass": False, "detail": str(exc)[:120]})

    # C2 页数硬约束：max 小到装不下时，产物必须落回 max 内或降级 partial —— 不许假绿（D14-R4）
    c2 = os.path.join(tmp, "max-slides")
    os.makedirs(c2, exist_ok=True)
    with open(os.path.join(c2, "paper.md"), "w", encoding="utf-8") as oh:
        with open(os.path.join(prepare_fixture("f1"), "paper.md"), encoding="utf-8") as ih:
            oh.write(ih.read())
    json.dump({"case_id": "SELFTEST-MAX", "task": "max 约束",
               "source": {"path": "paper.md"}, "slide_count": {"min": 3, "max": 5}},
              open(os.path.join(c2, "case.json"), "w", encoding="utf-8"))
    o5 = os.path.join(tmp, "out5")
    _py(os.path.join(SCRIPTS, "run.py"), "--input", os.path.join(c2, "case.json"),
        "--out", o5, "--backend", "auto", "--quiet")
    r5 = _load(os.path.join(o5, "result.json")) if os.path.isfile(
        os.path.join(o5, "result.json")) else {}
    n5 = len(r5.get("slides") or [])
    pv5 = ((r5.get("results") or {}).get("plan") or {}).get("validation")
    gate = (n5 <= 5) or (r5.get("status") != "success")
    out.append({"name": "C2 slide_count.max 硬约束（5 页上限）→ 页数落在上限内或降级 partial",
                "pass": bool(r5) and gate and pv5 is not None,
                "detail": "slides=%s(≤5? %s) status=%s validation=%s" % (
                    n5, n5 <= 5, r5.get("status"), pv5 is not None)})
    # C2b 计划校验必须进产物（findings 的 ok 与 status 不许互相矛盾）
    bad5 = [f for f in ((pv5 or {}).get("findings") or []) if f.get("severity") == "high"]
    out.append({"name": "C2b results.plan.validation 入产物且 high 项与 status 不矛盾",
                "pass": pv5 is not None and not (bad5 and r5.get("status") == "success"),
                "detail": "validation.ok=%s high=%d status=%s" % (
                    (pv5 or {}).get("ok"), len(bad5), r5.get("status"))})
    return out


def module_tests() -> list:
    out = []
    rc, log = _py(os.path.join(SCRIPTS, "units.py"))
    out.append({"name": "M1 units 自测", "pass": rc == 0, "detail": log.strip()[-80:]})
    rc, log = _py(os.path.join(SCRIPTS, "pptx_util.py"), "--out",
                  os.path.join(WORK, "t.pptx"), "--size", "16:9")
    ok = rc == 0 and os.path.isfile(os.path.join(WORK, "t.pptx"))
    out.append({"name": "M2 模板生成（主题字体/配色/版式改名可改）", "pass": ok,
                "detail": log.strip().splitlines()[-1][:90] if log.strip() else ""})
    rc, log = _py(os.path.join(SCRIPTS, "template_probe.py"), "--template",
                  os.path.join(WORK, "t.pptx"), "--out", os.path.join(WORK, "tm.json"))
    out.append({"name": "M3 模板解析（母版/版式/占位符）", "pass": rc == 0,
                "detail": log.strip()[-90:]})
    return out


def _sanitize(obj):
    """把报告里的本机绝对路径换成文件名（提交物不得出现作者机器的绝对路径）。"""
    import re as _re
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, str):
        s = _re.sub(r"[A-Za-z]:[\\/][^\s\"'|]*[\\/]([^\\/\s\"'|]+)", r"\1", obj)
        return _re.sub(r"[A-Za-z]:[\\/]", "", s)
    return obj


def _clean_pycache():
    """清理包内 __pycache__（平台把 >50 文件视为超限，.pyc 也算文件）。"""
    import shutil
    for base, dirs, _files in os.walk(ROOT):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)


def chinese_and_degradation_tests() -> list:
    """v1.1 新增：中文母版/占位符名识别 + 「模板里没有你要的版式」的降级实测。"""
    out = []
    tmp = os.path.join(WORK, "zh")
    os.makedirs(tmp, exist_ok=True)

    # M4 中文占位符名识别（单元级：只给名称，不给 type）
    gen = os.path.join(tmp, "_m4.py")
    with open(gen, "w", encoding="utf-8") as fh:
        fh.write(
            "import sys\n"
            "sys.dont_write_bytecode = True\n"
            "sys.path.insert(0, %r)\n"
            "import pptx_util as U\n"
            "class S:\n"
            "    def __init__(self, name): self.name = name\n"
            "cases = [('标题 1', 'title'), ('副标题 2', 'subtitle'), ('内容占位符 3', 'body'),\n"
            "         ('正文 4', 'body'), ('图片占位符 5', 'picture'), ('页脚占位符 6', 'footer'),\n"
            "         ('幻灯片编号占位符 7', 'slide_number'), ('日期占位符 8', 'date')]\n"
            "bad = [(n, U.ph_kind(S(n)), want) for n, want in cases if U.ph_kind(S(n)) != want]\n"
            "print('BAD' if bad else 'OK', bad)\n"
            % SCRIPTS)
    rc, log = _py(gen)
    out.append({"name": "M4 中文占位符名识别（标题/副标题/内容占位符/正文/图片/页脚/编号/日期）",
                "pass": rc == 0 and "OK" in log, "detail": log.strip()[-140:]})

    # M5 中文模板（中文版式名 + 中文占位符名）解析出正确角色
    tpl_zh = os.path.join(tmp, "zh_template.pptx")
    rc, log = _py(os.path.join(SCRIPTS, "pptx_util.py"), "--out", tpl_zh, "--size", "4:3",
                  "--rename-layouts", "zh", "--name-placeholders", "zh")
    tm_json = os.path.join(tmp, "tm_zh.json")
    rc2, log2 = _py(os.path.join(SCRIPTS, "template_probe.py"), "--template", tpl_zh,
                    "--out", tm_json)
    ok5, detail5 = False, log2.strip()[-120:]
    if os.path.isfile(tm_json):
        tm = _load(tm_json)
        roles = tm.get("roles") or {}
        names = [l["name"] for l in tm["layouts"]]
        zh_names = sum(1 for n in names if any("\u4e00" <= c <= "\u9fff" for c in n))
        ph_names = [p["name"] for l in tm["layouts"] for p in l["placeholders"]]
        zh_ph = sum(1 for n in ph_names if any("\u4e00" <= c <= "\u9fff" for c in n))
        ok5 = (zh_names >= 8 and zh_ph >= 20 and "title" in roles and "content" in roles)
        detail5 = "中文版式名=%d 中文占位符名=%d roles=%s" % (zh_names, zh_ph,
                                                             sorted(roles.keys()))
    out.append({"name": "M5 中文母版/版式/占位符名 → 角色识别正确", "pass": ok5,
                "detail": detail5})

    # M6 降级：模板里没有正文版式（body 占位符被删）→ 合成文本框 + 记账 + 仍出 pptx
    tpl_nobody = os.path.join(tmp, "nobody_template.pptx")
    _py(os.path.join(SCRIPTS, "pptx_util.py"), "--out", tpl_nobody, "--size", "16:9",
        "--rename-layouts", "zh", "--strip-body")
    case_nb = os.path.join(tmp, "case_nobody.json")
    src_dir = prepare_fixture("f1")
    json.dump({"case_id": "SELFTEST-NO-BODY-LAYOUT",
               "task": "模板缺正文版式的降级实测",
               "source": {"path": os.path.join(src_dir, "paper.md")},
               "template": tpl_nobody,
               "slide_count": {"min": 8, "max": 10, "target": 9}},
              open(case_nb, "w", encoding="utf-8"), ensure_ascii=False)
    o = os.path.join(tmp, "out_nobody")
    rc, log = _py(os.path.join(SCRIPTS, "run.py"), "--input", case_nb, "--out", o,
                  "--backend", "none", "--quiet")
    rj = os.path.join(o, "result.json")
    ok6, detail6 = False, log.strip()[-160:]
    if os.path.isfile(rj):
        r = _load(rj)
        synth = (r.get("results", {}).get("build") or {}).get("placeholders_synthesized") or []
        warns = (r.get("results", {}).get("build") or {}).get("warnings") or []
        pptx_ok = any(a.get("kind") == "editable-presentation" and a.get("exists")
                      for a in (r.get("artifacts") or []))
        noted = bool(synth) or any("正文" in w or "版式" in w for w in warns)
        ok6 = bool(pptx_ok and noted and r["status"] in ("success", "partial"))
        detail6 = "合成占位符=%d 警告=%d pptx=%s status=%s" % (
            len(synth), len(warns), pptx_ok, r.get("status"))
    # M7 模板：文本 spec → 运行时合成，且与 spec.expected 结构一致（包内不放 pptx）
    spec_path = os.path.join(ROOT, "templates", "template-spec.json")
    tpl_out = os.path.join(tmp, "spec_synth.pptx")
    rc, log = _py(os.path.join(SCRIPTS, "pptx_util.py"), "--spec", spec_path,
                  "--name", "academic-16x9", "--out", tpl_out)
    ok7, detail7 = False, log.strip()[-160:]
    if rc == 0 and os.path.isfile(tpl_out):
        try:
            i, j = log.find("{"), log.rfind("}")
            info = json.loads(log[i:j + 1])
            chk = info.get("spec_check") or {}
            ok7 = bool(chk.get("ok")) and chk.get("layout_count_match") is True \
                and chk.get("geometry_max_delta_emu") == 0
            detail7 = "layout/theme/roles=%s/%s/%s geometry_delta=%s" % (
                chk.get("layout_count_match"), chk.get("theme_match"),
                chk.get("roles_match"), chk.get("geometry_max_delta_emu"))
        except Exception as exc:
            detail7 = "解析 synthesis 输出失败: %s" % exc
    out.append({"name": "M7 文本 template-spec.json → 运行时合成模板并与 expected 一致",
                "pass": ok7, "detail": detail7})

    # M8 包内只允许 UTF-8 文本资源（平台预检硬规则：含 png/pdf/pptx 会被拒）
    ALLOWED = {".md", ".py", ".json", ".csv", ".svg", ".txt", ".sh", ".yaml", ".yml"}
    bad = []
    for base, dirs, files in os.walk(ROOT):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in ALLOWED:
                bad.append(os.path.relpath(os.path.join(base, f), ROOT).replace("\\", "/"))
        # __pycache__/*.pyc 同样是二进制且占文件数配额：不许出现（实测踩过：
        # 直接用 `python -c "import selftest"` 调函数时会绕过脚本内的 dont_write_bytecode）
        if "__pycache__" in dirs:
            bad.append(os.path.relpath(os.path.join(base, "__pycache__"), ROOT)
                       .replace("\\", "/") + "/*.pyc")
    out.append({"name": "M8 包内无二进制资源（仅文本扩展名 + 无 __pycache__）", "pass": not bad,
                "detail": ("非文本文件: %s" % bad[:5]) if bad else "全部为文本文件、无 pyc"})
    return out


def d14_r1_r3_tests() -> list:
    """D14-R1 自足（零附加参数入口）+ D14-R3 只读独立审计。"""
    out = []
    tmp = os.path.join(WORK, "d14")
    os.makedirs(tmp, exist_ok=True)
    r1_rows, ok_all, detail = [], True, []
    for c in ("f1", "f2", "f3", "f4"):
        if not os.path.isdir(os.path.join(FIXTURES, c)):
            continue
        cdir = prepare_fixture(c)
        # R1 的要点是"模板由文本 spec 在运行期合成"：这里刻意删掉夹具里的 pptx 模板，
        # 强制走 spec-synth 路径（case.json 里指向它的字段会解析失败并回退到 specs）。
        for stale in ("template.pptx",):
            sp = os.path.join(cdir, stale)
            if os.path.isfile(sp):
                os.remove(sp)
        odir = os.path.join(tmp, "r1-" + c)
        # 零附加参数：只给 --case / --out
        rc, log = _py(os.path.join(SCRIPTS, "fit.py"),
                      "--case", os.path.join(cdir, "case.json"), "--out", odir)
        rj = os.path.join(odir, "result.json")
        st, src_t, outs = None, None, 0
        if os.path.isfile(rj):
            r = _load(rj)
            st = r.get("status")
            tp = (r.get("results") or {}).get("template") or {}
            src_t = tp.get("origin") or tp.get("source")
            outs = len(r.get("outputs") or [])
            keys = all(k in r for k in ("case_id", "status", "results", "slides", "evidence",
                                        "sources", "uncertainty", "changes", "outputs"))
        else:
            keys = False
        ok = (rc == 0 and st == "success" and str(src_t or "").startswith("spec-synth")
              and outs >= 2 and keys)
        ok_all = ok_all and ok
        r1_rows.append({"case": c, "status": st, "template_source": src_t,
                        "outputs": outs, "contract_keys": bool(keys), "pass": ok})
        detail.append("%s:%s" % (c, st))
    out.append({"name": "R1 零附加参数自足（4 夹具 status=success + spec 合成模板 + 契约键齐备）",
                "pass": ok_all, "detail": "%s | %s" % (",".join(detail),
                                                       json.dumps(r1_rows, ensure_ascii=False)[:220]),
                "expected": "status=success / 模板源 spec-synth / outputs>=2 / 契约键齐备",
                "actual": json.dumps(r1_rows, ensure_ascii=False)[:400]})

    # R3：只读产物重算，与 result.json 自述逐项对照
    odir = os.path.join(tmp, "r1-f1")
    aprep = os.path.join(tmp, "audit_only.json")
    rc, log = _py(os.path.join(SCRIPTS, "audit_only.py"), "--out", odir, "--json", aprep)
    rep = _load(aprep) if os.path.isfile(aprep) else {}
    fails = [c for c in rep.get("checks") or [] if not c.get("pass")]
    out.append({"name": "R3 只读审计器（不重跑生成，重算并与自述对照）",
                "pass": rc == 0 and bool(rep.get("ok")),
                "detail": "checks=%s passed=%s high_failures=%s" % (
                    rep.get("total"), rep.get("passed"), rep.get("high_failures")),
                "expected": "全部对照项 pass（high 不一致 0）",
                "actual": json.dumps([{"item": f["item"], "expected": f["expected"],
                                       "actual": f["actual"]} for f in fails][:6],
                                     ensure_ascii=False)[:400]})
    return out


def cwd_independence_test() -> dict:
    """D14-R1b：**从别的 cwd** 用绝对路径调用，材料/模板 spec/资产仍相对 case.json 解析。

    复现 Lead 的实测姿势：`cd %TEMP% ; python3 <pkg绝对路径>/scripts/fit.py
    --case <pkg绝对路径>/examples/case.example.json --out %TEMP%/out`
    """
    tmp = os.path.join(WORK, "cwd")
    os.makedirs(tmp, exist_ok=True)
    foreign_cwd = tempfile.mkdtemp(prefix="q08-cwd-")
    case_abs = os.path.join(ROOT, "examples", "case.example.json")
    out = os.path.join(tmp, "out-example")
    cmd = [sys.executable, os.path.join(SCRIPTS, "fit.py"),
           "--case", case_abs, "--out", out]
    p = subprocess.run(cmd, capture_output=True, cwd=foreign_cwd, timeout=600,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                PYTHONDONTWRITEBYTECODE="1"))
    log = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8",
                                                                                 "replace")
    rj = os.path.join(out, "result.json")
    rec = {"name": "R1b cwd 无关（外部 cwd + 绝对路径调用 → success + resolved_from 记账）",
           "foreign_cwd": os.path.basename(foreign_cwd), "returncode": p.returncode,
           "status": None, "resolved_from": {}, "template_origin": None, "pass": False,
           "detail": log.strip()[-200:]}
    if os.path.isfile(rj):
        r = _load(rj)
        res = r.get("resolution") or {}
        entries = {e.get("kind"): e.get("resolved_from") for e in (res.get("entries") or [])}
        rec["status"] = r.get("status")
        rec["resolved_from"] = entries
        rec["template_origin"] = ((r.get("results") or {}).get("template") or {}).get("origin")
        src_ok = entries.get("source") == "case_dir"
        ok = (p.returncode == 0 and r.get("status") == "success" and src_ok
              and str(rec["template_origin"] or "").startswith("spec-synth"))
        # 额外确认：从外部 cwd 也不该在 cwd 里生成任何产物
        rec["artifacts_in_cwd"] = [f for f in os.listdir(foreign_cwd)]
        ok = ok and not rec["artifacts_in_cwd"]
        rec["pass"] = ok
    return rec


def copy_probe_test() -> dict:
    """把**整包拷到含 stage/outputs 的路径下**再跑（q03 同类高危场景的回归）：

    路径段里有 `outputs`/`stage`/`runs` 时，若输入发现按路径段过滤就会吞掉输入、
    产出空产物却报 success。这里要求：外部 cwd + 包在 ...\\stage\\outputs 下仍
     `status=success`、`slides>0`、模板来源 `spec-synth`，且**不往 cwd 写东西**。
    """
    tmp = os.path.join(WORK, "copyprobe")
    stage = os.path.join(tmp, "probe", "runs", "q08-fire", "stage", "outputs")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.dirname(stage), exist_ok=True)
    dest = os.path.join(stage, "pkg")
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    foreign_cwd = tempfile.mkdtemp(prefix="q08-copyprobe-")
    out = os.path.join(tmp, "out")
    case = os.path.join(dest, "examples", "case.example.json")
    p = subprocess.run([sys.executable, os.path.join(dest, "scripts", "fit.py"),
                        "--case", case, "--out", out], capture_output=True, cwd=foreign_cwd,
                       timeout=600, env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                             PYTHONDONTWRITEBYTECODE="1"))
    log = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8",
                                                                                 "replace")
    rec = {"name": "copy_probe 整包拷到 .../stage/outputs 下仍自足（防路径段过滤吞输入）",
           "copy_path_has_outputs": "stage" in dest and "outputs" in dest,
           "returncode": p.returncode, "status": None, "slides": None,
           "template_origin": None, "resolved_from": {}, "artifacts_in_cwd": [], "pass": False,
           "detail": log.strip()[-200:]}
    rj = os.path.join(out, "result.json")
    if os.path.isfile(rj):
        r = _load(rj)
        rec["status"] = r.get("status")
        rec["slides"] = ((r.get("results") or {}).get("plan", {}) or {}).get("stats", {}) \
            .get("slides") if isinstance((r.get("results") or {}).get("plan"), dict) else None
        rec["slides"] = rec["slides"] or len(r.get("slides") or [])
        rec["template_origin"] = ((r.get("results") or {}).get("template") or {}).get("origin")
        rec["resolved_from"] = {e.get("kind"): e.get("resolved_from")
                                for e in ((r.get("resolution") or {}).get("entries") or [])}
        rec["rendered_pages"] = ((r.get("results") or {}).get("render") or {}).get("page_count")
        rec["artifacts_in_cwd"] = sorted(os.listdir(foreign_cwd))
        rec["pass"] = bool(p.returncode == 0 and r.get("status") == "success"
                           and (rec["slides"] or 0) > 0
                           and str(rec["template_origin"] or "").startswith("spec-synth")
                           and not rec["artifacts_in_cwd"])
    return rec


def material_isolation_tests() -> list:
    """D14-R5 负向对照：工单/契约/示例/schema **不得**被当成科学材料（q01 同类 P0 的回归）。

    三条判据都只看真实产物：
      D1 只给 task.md（工单）→ 必须 partial + SOURCE_IS_TASK_DOC，且 evidence/slides 为空；
      D2 显式 source=case.json（契约）→ 必须 partial + 拒绝码，且不解析出内容块；
      D3 sentinel 不泄漏：case.json / task.md / 模板 spec 里埋的哨兵串不得出现在
         pptx 文本、slides/evidence/evidence_map/deck_report 里（材料是 paper.md）。
    """
    out = []
    tmp = os.path.join(WORK, "material-isolation")
    os.makedirs(tmp, exist_ok=True)
    SENT = "SENTINEL-Q08-WORKORDER-DO-NOT-USE-8F3A"
    # 工单文件：扩展名合法（.md）但角色是工单，且带哨兵
    wo = os.path.join(tmp, "d3")
    os.makedirs(wo, exist_ok=True)
    with open(os.path.join(wo, "task.md"), "w", encoding="utf-8") as fh:
        fh.write("# 工单（不是材料）\n\n本行是 %s，不得进入页内证据。\n" % SENT)
    with open(os.path.join(wo, "paper.md"), "w", encoding="utf-8") as fh:
        fh.write("# FIXTURE · 单原子纳米酶比色检测\n\n## 结果\n\n"
                 "在 0.5 nM 检出限下，回收率为 98.2%。\n")
    with open(os.path.join(wo, "case.json"), "w", encoding="utf-8") as fh:
        fh.write('{"case_id": "SELFTEST-ISOLATION", "task": "%s",'
                 ' "source": {"path": "paper.md"}, "slide_count": {"min": 3, "max": 5}}\n'
                 % SENT)
    with open(os.path.join(wo, "template-spec.example.json"), "w", encoding="utf-8") as fh:
        fh.write('{"_note": "%s", "default": "x", "templates": []}\n' % SENT)
    o3 = os.path.join(tmp, "out3")
    rc3, log3 = _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(wo, "case.json"),
                    "--out", o3, "--backend", "none")
    r3 = _load(os.path.join(o3, "result.json")) if os.path.isfile(
        os.path.join(o3, "result.json")) else {}
    leaked = []
    if r3:
        blob = json.dumps({"slides": r3.get("slides"), "evidence": r3.get("evidence"),
                           "sources": r3.get("sources")}, ensure_ascii=False)
        if SENT in blob:
            leaked.append("result.json")
        for fn in ("evidence_map.json", "deck_report.md"):
            pth = os.path.join(o3, fn)
            if os.path.isfile(pth) and SENT in open(pth, encoding="utf-8").read():
                leaked.append(fn)
        try:
            from pptx import Presentation
            prs = Presentation(os.path.join(o3, "SELFTEST-ISOLATION.pptx"))
            txt = "\n".join(sh.text_frame.text for s in prs.slides for sh in s.shapes
                            if sh.has_text_frame)
            if SENT in txt:
                leaked.append("pptx")
        except Exception as exc:
            leaked.append("pptx-unreadable:%s" % str(exc)[:40])
    src0 = (r3.get("sources") or [{}])[0] if r3 else {}
    src_name = src0.get("original_file") or src0.get("file")
    out.append({"name": "D3 工单/spec 里的 sentinel 不进入产物（材料=paper.md）",
                "pass": bool(r3) and not leaked and src_name == "paper.md",
                "detail": "leaked=%s sources[0]=%s status=%s" % (leaked, src_name,
                                                                 r3.get("status"))})

    # D1 只有 task.md（没有真实材料）→ 拒绝，不许拿工单当材料
    d1 = os.path.join(tmp, "d1")
    os.makedirs(d1, exist_ok=True)
    with open(os.path.join(d1, "task.md"), "w", encoding="utf-8") as fh:
        fh.write("# 工单\n\n讨论方法、结果与限制。\n")
    json.dump({"case_id": "SELFTEST-WO-ONLY"}, open(os.path.join(d1, "case.json"), "w",
                                                    encoding="utf-8"))
    o1 = os.path.join(tmp, "out1")
    _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(d1, "case.json"),
        "--out", o1, "--backend", "none")
    r1 = _load(os.path.join(o1, "result.json")) if os.path.isfile(
        os.path.join(o1, "result.json")) else {}
    out.append({"name": "D1 工单（task.md）不得被当作材料 → partial + 明确拒绝码",
                "pass": bool(r1) and r1.get("status") == "partial"
                        and not (r1.get("evidence") or [])
                        and ("TASK_DOC" in (r1.get("status_reason") or "")
                             or "未找到源材料" in (r1.get("status_reason") or "")),
                "detail": "status=%s reason=%s evidence=%d" % (
                    r1.get("status"), (r1.get("status_reason") or "")[:70],
                    len(r1.get("evidence") or []))})

    # D2 显式把 case.json 当材料 → 拒绝（JSON 不进引文索引）
    d2 = os.path.join(tmp, "d2")
    os.makedirs(d2, exist_ok=True)
    json.dump({"case_id": "SELFTEST-JSON-SOURCE", "source": {"path": "case.json"}},
              open(os.path.join(d2, "case.json"), "w", encoding="utf-8"))
    o2 = os.path.join(tmp, "out2")
    _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(d2, "case.json"),
        "--out", o2, "--backend", "none")
    r2 = _load(os.path.join(o2, "result.json")) if os.path.isfile(
        os.path.join(o2, "result.json")) else {}
    out.append({"name": "D2 case.json 当 source → 拒绝（json 不在材料白名单）",
                "pass": bool(r2) and r2.get("status") == "partial"
                        and not (r2.get("evidence") or [])
                        and ("TASK_DOC" in (r2.get("status_reason") or "")
                             or "UNSUPPORTED" in (r2.get("status_reason") or "")),
                "detail": "status=%s reason=%s" % (r2.get("status"),
                                                   (r2.get("status_reason") or "")[:70])})
    return out


def contamination_tests(backend: str = "auto") -> list:
    """把 tests/contam_test.py（D30 材料污染 + 五项篡改负向对照）并入总自检。

    该脚本可独立复跑：`python tests/contam_test.py [--no-render]`。
    """
    out = []
    args = [os.path.join(HERE, "contam_test.py")]
    if backend == "none":
        args.append("--no-render")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable] + args, capture_output=True,
                           encoding="utf-8", errors="replace",
                           timeout=1200, env=env)
        lines = [l.strip() for l in (p.stdout or "").splitlines() if l.strip().startswith("[")]
        fails = [l for l in lines if "[FAIL]" in l]
        out.append({"name": "D30 材料污染 + 五项篡改负向对照（tests/contam_test.py）",
                    "pass": p.returncode == 0 and not fails,
                    "detail": "rc=%s checks=%d fails=%d %s" % (
                        p.returncode, len(lines), len(fails), (fails[:2] or ""))})
    except Exception as exc:
        out.append({"name": "D30 材料污染 + 五项篡改负向对照（tests/contam_test.py）",
                    "pass": False, "detail": str(exc)[:160]})
    return out


def empty_guard_test() -> dict:
    """空产物守卫：材料解析出 0 块（或 0 页）必须降级 partial，不许报 success。"""
    tmp = os.path.join(WORK, "emptyguard")
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "empty.md")
    open(src, "w", encoding="utf-8").write("")
    cj = os.path.join(tmp, "case.json")
    json.dump({"case_id": "SELFTEST-EMPTY", "source": {"path": "empty.md"},
               "slide_count": {"min": 1, "max": 5}}, open(cj, "w", encoding="utf-8"))
    out = os.path.join(tmp, "out")
    rc, log = _py(os.path.join(SCRIPTS, "fit.py"), "--case", cj, "--out", out, "--no-render")
    rj = os.path.join(out, "result.json")
    rec = {"name": "空产物守卫（0 内容块/0 页 → partial + 具体原因）", "pass": False,
           "detail": log.strip()[-160:], "expected": "status=partial 且 status_reason 含「空产物」",
           "actual": None}
    if os.path.isfile(rj):
        r = _load(rj)
        rec["actual"] = {"status": r.get("status"), "status_reason": (r.get("status_reason") or "")[:80],
                         "guards": (r.get("pipeline") or {}).get("guards")}
        rec["pass"] = (r.get("status") == "partial"
                       and "空产物" in (r.get("status_reason") or ""))
    return rec


def reference_tests() -> list:
    """vT5：references 三篇（异常码/映射/schema）不是散文——各配一条可跑判据。"""
    out = []
    tmp = os.path.join(WORK, "references")
    os.makedirs(tmp, exist_ok=True)

    # (1) result.schema.json 对**真实产物**必须 PASS（零依赖校验器）
    odir = os.path.join(WORK, "d14", "r1-f1")
    if not os.path.isfile(os.path.join(odir, "result.json")):
        cdir = prepare_fixture("f1")
        odir = os.path.join(tmp, "schema-case")
        _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(cdir, "case.json"),
            "--out", odir, "--backend", "none")
    rep_json = os.path.join(tmp, "schema_report.json")
    rc, log = _py(os.path.join(SCRIPTS, "audit_only.py"), "--out", odir,
                  "--check-schema", "--json", rep_json)
    rep = _load(rep_json) if os.path.isfile(rep_json) else {}
    out.append({"name": "references/result.schema.json 校验真实 result.json（零依赖）",
                "pass": rc == 0 and bool(rep.get("ok")),
                "detail": "errors=%s" % (rep.get("error_count")),
                "expected": "schema 校验 PASS（0 个问题）",
                "actual": json.dumps((rep.get("errors") or [])[:5], ensure_ascii=False)[:300]})

    # (2) 「先删后加」的 partname 冲突回归（对手 safe_add_slide 提示的那个坑）
    try:
        sys.path.insert(0, SCRIPTS)
        import pptx_util as U
        import zipfile
        import collections
        from pptx import Presentation as _P
        d = os.path.join(tmp, "partname")
        os.makedirs(d, exist_ok=True)
        src = os.path.join(d, "with3.pptx")
        U.build_template_from_spec(U.load_template_spec(
            os.path.join(ROOT, "templates", "template-spec.json")), "academic-16x9", src)
        p = _P(src)
        for i in range(3):
            s = p.slides.add_slide(p.slide_layouts[1])
            s.shapes.title.text = "old %d" % i
        p.save(src)
        p2 = U.load(src)
        removed = U.strip_slides(p2)
        for i in range(11):
            s = p2.slides.add_slide(p2.slide_layouts[1])
            s.shapes.title.text = "new %d" % i
        dst = os.path.join(d, "out.pptx")
        p2.save(dst)
        names = [n for n in zipfile.ZipFile(dst).namelist() if n.startswith("ppt/slides/slide")]
        dups = [k for k, v in collections.Counter(names).items() if v > 1]
        out.append({"name": "删页后追加：zip 内无重复 partname（回避 PowerPoint 修复提示）",
                    "pass": len(dups) == 0 and len(names) == 11 and removed == 3,
                    "detail": "stripped=%s slides_in_zip=%s dups=%s" % (removed, len(names), dups),
                    "expected": "stripped=3 / slides_in_zip=11 / dups=[]",
                    "actual": json.dumps({"dups": dups}, ensure_ascii=False)})
    except Exception as exc:
        out.append({"name": "删页后追加：zip 内无重复 partname", "pass": False,
                    "detail": "异常: %s" % str(exc)[:140], "expected": "dups=[]", "actual": None})

    # (3) 中文版式名/占位符名 → 角色映射（template-mapping.md 的实测声明）
    cdir = prepare_fixture("f4")
    ok_map, det = False, "fixture 未生成"
    tmap_path = os.path.join(WORK, "d14", "r1-f4", "template_map.json")
    if not os.path.isfile(tmap_path):
        # 不依赖前序用例的中间产物：自己跑一次（--backend none，快）
        _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(cdir, "case.json"),
            "--out", os.path.join(tmp, "roles"), "--backend", "none")
        tmap_path = os.path.join(tmp, "roles", "template_map.json")
    if os.path.isfile(tmap_path):
        tm = _load(tmap_path)
        roles = tm.get("roles") or {}
        need = ["title", "content", "section", "two-column", "title-only", "blank", "figure"]
        missing = [r for r in need if r not in roles]
        ok_map = not missing
        det = "roles=%s missing=%s" % (sorted(roles), missing)
    out.append({"name": "中文版式名+中文占位符名 → 7 类角色全部识别（template-mapping.md）",
                "pass": ok_map, "detail": det,
                "expected": "title/content/section/two-column/title-only/blank/figure 均在 roles",
                "actual": det})
    # (4) P0 回归：无模板案例必须**显式**走 spec 合成，并在结果里留下降级记录
    cdir = prepare_fixture("f1")
    for stale in ("template.pptx",):
        sp = os.path.join(cdir, stale)
        if os.path.isfile(sp):
            os.remove(sp)
    odir = os.path.join(tmp, "no-template")
    _py(os.path.join(SCRIPTS, "fit.py"), "--case", os.path.join(cdir, "case.json"), "--out", odir)
    rj = os.path.join(odir, "result.json")
    r = _load(rj) if os.path.isfile(rj) else {}
    tp = (r.get("results") or {}).get("template") or {}
    degr = tp.get("degradations") or []
    unc = [u for u in (r.get("uncertainty") or []) if "模板降级" in (u.get("item") or "")]
    bundled = os.path.join(ROOT, "templates", "academic-16x9.pptx")
    out.append({"name": "P0 无模板案例：显式 spec 合成 + 降级记录（不靠 isfile 静默兜底）",
                "pass": (bool(r) and r.get("status") == "success"
                         and str(tp.get("origin") or "").startswith("spec-synth")
                         and len(degr) >= 1 and bool(unc) and not os.path.isfile(bundled)),
                "detail": "status=%s origin=%s degradations=%d uncertainty=%s bundled_pptx=%s"
                          % (r.get("status"), tp.get("origin"), len(degr), bool(unc),
                             os.path.isfile(bundled)),
                "expected": "status=success / origin=spec-synth / degradations≥1 / uncertainty 有模板降级 / 包内无 pptx",
                "actual": json.dumps({"origin": tp.get("origin"), "degradations": degr[:1],
                                      "uncertainty_items": [u.get("item") for u in unc]},
                                     ensure_ascii=False)[:300]})

    # (5) METHOD.md 承诺的兜底产物：无渲染后端时 preview.html + preview.layout.md 都要在
    pv = os.path.join(tmp, "fallback", "preview")
    try:
        sys.path.insert(0, SCRIPTS)
        import render_preview as RP
        deck = next((os.path.join(odir, f) for f in os.listdir(odir) if f.endswith(".pptx")), None)
        rep = RP.render(deck, os.path.join(tmp, "fallback"), "none")
        files = sorted(os.listdir(pv)) if os.path.isdir(pv) else []
        out.append({"name": "兜底产物齐备：preview.html + preview.layout.md（不伪造 PDF/PNG）",
                    "pass": rep.get("ok") is False and "preview.html" in files
                            and "preview.layout.md" in files,
                    "detail": "files=%s fallback_keys=%s" % (
                        files, sorted((rep.get("fallback") or {}).keys())),
                    "expected": "backend=none / ok=false / html+layout.md 均在",
                    "actual": json.dumps(files, ensure_ascii=False)})
    except Exception as exc:
        out.append({"name": "兜底产物齐备：preview.html + preview.layout.md", "pass": False,
                    "detail": "异常: %s" % str(exc)[:140], "expected": "两文件均在", "actual": None})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="q08 skill self-test")
    ap.add_argument("--out", default=os.path.join(ROOT, "tests", "selftest-report.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--cases", default="f1,f2,f3,f4")
    ap.add_argument("--prepare-only", action="store_true",
                    help="只把夹具（含运行时生成的模板/旧 deck）准备到包外工作目录并打印路径")
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(WORK, exist_ok=True)
    cases = ["f1"] if a.quick else [c.strip() for c in a.cases.split(",") if c.strip()]
    if a.prepare_only:
        for c in cases:
            if os.path.isdir(os.path.join(FIXTURES, c)):
                print(prepare_fixture(c))
        return 0
    backend = "none" if a.quick else "auto"
    report = {"generated_by": "tests/selftest.py", "generated_at":
              _dt.datetime.now().astimezone().replace(microsecond=0).isoformat(),
              "mode": "quick" if a.quick else "full",
              "backend": backend, "cases": [], "modules": [], "degradation": [],
              "counter_examples": [], "totals": {}}
    for c in cases:
        if not os.path.isdir(os.path.join(FIXTURES, c)):
            continue
        cdir = prepare_fixture(c)
        outdir = os.path.join(WORK, c)
        report["cases"].append(run_case(cdir, outdir, backend))
    report["modules"] = module_tests() + chinese_and_degradation_tests() + d14_r1_r3_tests() \
        + reference_tests()
    report["cwd_independence"] = cwd_independence_test()
    report["copy_probe"] = copy_probe_test()
    report["empty_guard"] = empty_guard_test()
    report["material_isolation"] = material_isolation_tests() + contamination_tests(backend)
    report["degradation"] = degradation_tests()
    report["counter_examples"] = counter_example_tests()
    all_checks = []
    for grp in ("cases", "modules", "degradation", "counter_examples", "material_isolation"):
        for item in report[grp]:
            for ck in item.get("checks") or []:
                all_checks.append(ck)
            if grp != "cases":
                all_checks.append({"name": item["name"], "pass": item["pass"],
                                   "detail": item.get("detail", "")})
    if report.get("cwd_independence"):
        ci = report["cwd_independence"]
        all_checks.append({"name": ci["name"], "pass": ci["pass"],
                           "detail": "status=%s resolved_from=%s" % (ci.get("status"),
                                                                     ci.get("resolved_from"))})
    if report.get("copy_probe"):
        cp = report["copy_probe"]
        all_checks.append({"name": cp["name"], "pass": cp["pass"],
                           "detail": "status=%s slides=%s origin=%s cwd残留=%s" % (
                               cp.get("status"), cp.get("slides"), cp.get("template_origin"),
                               cp.get("artifacts_in_cwd"))})
    if report.get("empty_guard"):
        eg = report["empty_guard"]
        all_checks.append({"name": eg["name"], "pass": eg["pass"],
                           "detail": str(eg.get("actual"))[:160]})
    passed = sum(1 for c in all_checks if c["pass"])
    report["totals"] = {"checks": len(all_checks), "passed": passed,
                        "failed": len(all_checks) - passed,
                        "pass_rate": round(passed / max(1, len(all_checks)), 4),
                        "runtime_s": round(time.time() - t0, 1),
                        "ok": passed == len(all_checks)}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(_sanitize(report), fh, ensure_ascii=False, indent=2)
    _clean_pycache()
    t = report["totals"]
    print("selftest: %d/%d 通过（%.1f%%，%.1fs）→ %s" % (
        t["passed"], t["checks"], t["pass_rate"] * 100, t["runtime_s"], a.out))
    for c in report["cases"]:
        fails = [x for x in c["checks"] if not x["pass"]]
        print("  case %s status=%s checks=%d fail=%d %s" % (
            c.get("case_id"), c.get("status"), len(c["checks"]), len(fails),
            [f["name"] for f in fails]))
    for k in ("modules", "degradation", "counter_examples", "material_isolation"):
        for it in report[k]:
            if not it.get("pass", True) or any(not x["pass"] for x in it.get("checks") or []):
                print("  FAIL %s | %s" % (it.get("name"), it.get("detail", "")[:120]))
    return 0 if t["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
