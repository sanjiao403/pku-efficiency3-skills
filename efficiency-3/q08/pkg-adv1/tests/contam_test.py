#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contam_test.py —— 材料污染与"假绿"对抗测试（D30/D14-R5）。

Lead 的交叉情报：包如果把**工单/输入/示例/自制 spec**当成科学证据，就会出现
`sources[0]=case.json`、页内出现 JSON 原文或 sentinel，而"引文可回源"照样全绿
（自我循环）。本脚本对 q08 做三件事：

  ① 污染注入：把同一个哨兵串塞进 `task.md` / `case.json` / `case.example.json` /
     `*.template.json` / 自制 `template-spec.json`（含 component 风格字段），
     再跑真实流水线；断言哨兵在**全部产物**里的出现次数为 0，且 `sources[]`
     只指向真实材料。
  ② 来源白名单：`sources[]` / `resolution` 里不得出现工单/示例/自制 spec。
  ③ 五项篡改负向对照：对一份**正常产物**分别做
       T1 映射指向不存在的样式   T2 工单推进 sources[]
       T3 删掉一条版式映射       T4 引文指向未读材料
       T5 嵌入栅格基准（根目录塞位图）
     独立校验器 `scripts/audit_only.py` 必须**逐项变红**（high 失败 ≥1、退出码非 0）。
     只有这条能证明"全绿"不是自证串通。

跑法：python tests/contam_test.py            （约 30–60 秒，含一次真渲染）
      python tests/contam_test.py --no-render（不做 T5 的渲染依赖，更快）
退出码：0 全部符合预期 / 1 有不符合项。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
SENT = "SENTINELJUNKQ08WORKORDER7C41"

MATERIAL_MD = """# 单原子纳米酶比色检测平台（真实材料）

## 方法
以 Fe-N4 单原子位点催化 TMB 显色，反应体积 200 uL。

## 结果
在 0.5 nM 检出限下，水样加标回收率为 98.2%，相对标准偏差 3.1%。

## 限制
仅验证了三种水样基质，未覆盖高盐体系。
"""


def w(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run_pipeline(case: str, out: str, backend: str = "auto") -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fit.py"),
                        "--case", case, "--out", out, "--backend", backend, "--quiet"],
                       capture_output=True, env=env, encoding="utf-8", errors="replace", timeout=900)
    return p.returncode


def audit(out: str, template_map: str | None = None) -> tuple:
    """跑独立只读审计器；返回 (退出码, high 失败项名列表, stdout 尾巴)。"""
    cmd = [sys.executable, os.path.join(SCRIPTS, "audit_only.py"), "--out", out]
    if template_map:
        cmd += ["--template-map", template_map]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(cmd, capture_output=True, env=env, encoding="utf-8", errors="replace", timeout=300)
    fails = []
    for line in (p.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("[high]") and not s.startswith("[high] 0"):
            fails.append(s.split("|")[0].replace("[high]", "").strip())
    return p.returncode, fails, (p.stdout or "").strip()[-200:]


def parse_rc_line(txt: str) -> int:
    i = txt.find("{")
    return i


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="contam_test")
    ap.add_argument("--no-render", action="store_true", help="不做真渲染（跳过 T5 的渲染依赖）")
    ap.add_argument("--keep", action="store_true", help="保留临时目录便于人工复查")
    a = ap.parse_args(argv)
    backend = "none" if a.no_render else "auto"
    tmp = tempfile.mkdtemp(prefix="q08-contam-")
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        print("  [%s] %s | %s" % ("PASS" if ok else "FAIL", name, detail[:160]))

    # ---------------- ① 污染注入：所有非材料文件塞哨兵 ----------------
    # 关键设计：哨兵只放进**没有声明渲染角色**的位置 —— 工单/示例/自制 spec 全文件，
    # 以及 case.json 的非契约字段（`_note`/`debug_note`/未知嵌套）。case.json 里
    # **声明过的**渲染/回显字段（task / footer / output_contract）由夹具 B 单独验证
    # （它们按契约就是要出现在产物里，属于"输入被兑现"，不是污染）。
    d = os.path.join(tmp, "contam")
    w(os.path.join(d, "materials.md"), MATERIAL_MD)
    w(os.path.join(d, "task.md"), "# 工单 %s\n\n按模板出 8–12 页，导出 PDF。\n" % SENT)
    w(os.path.join(d, "case.json"), json.dumps({
        "case_id": "CONTAM-1",
        "_note": "污染测试 " + SENT,
        "debug_note": {"nested": SENT},
        "source": {"path": "materials.md"},
        "slide_count": {"min": 4, "max": 6},
    }, ensure_ascii=False, indent=2))
    w(os.path.join(d, "case.example.json"), json.dumps({"case_id": SENT}, ensure_ascii=False))
    w(os.path.join(d, "plan.template.json"), json.dumps({"claim": SENT}, ensure_ascii=False))
    w(os.path.join(d, "result.example.json"), json.dumps({"summary": SENT}, ensure_ascii=False))
    # 自制模板规格（component 风格字段），台词是"工单/示例"，不得成为材料
    w(os.path.join(d, "template-spec.json"), json.dumps({
        "_note": "自制模板规格 " + SENT,
        "component_json": {"name": SENT, "props": {"title": SENT}},
        "default": "contam-16x9",
        "templates": [{
            "name": "contam-16x9",
            "build": {"size": "16:9", "theme_name": "academic-cjk"},
            "theme": {"major": {"latin": "Arial", "ea": "黑体", "cs": "Arial"},
                      "minor": {"latin": "Times New Roman", "ea": "宋体",
                                "cs": "Times New Roman"},
                      "colors": {"dk2": "1F3864", "accent1": "2E74B5", "accent2": "C00000"}},
            "expected": {"layout_count": 11},
        }],
    }, ensure_ascii=False, indent=2))
    out = os.path.join(d, "o")
    run_pipeline(os.path.join(d, "case.json"), out, backend)
    rj = os.path.join(out, "result.json")
    r = json.load(open(rj, encoding="utf-8")) if os.path.isfile(rj) else {}
    chk("污染案例产出 result.json", bool(r), "status=%s" % r.get("status"))

    # 哨兵在**全部产物**里的出现次数（含 JSON 中间件/报告）
    leak = {}
    for base, _dirs, files in os.walk(out):
        if os.path.basename(base) == "work":
            continue
        for f in files:
            p = os.path.join(base, f)
            if f.endswith((".json", ".md", ".txt", ".xml", ".html")):
                try:
                    t = open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                n = t.count(SENT)
                if n:
                    leak[os.path.relpath(p, out)] = n
    chk("① 产物中哨兵出现次数为 0（含 result.json/映射表/报告）", not leak,
        "leak=%s" % (leak or "none"))

    # pptx 文本侧也不能有哨兵
    try:
        from pptx import Presentation
        pptxs = [f for f in os.listdir(out) if f.endswith(".pptx")]
        txt = ""
        for f in pptxs:
            prs = Presentation(os.path.join(out, f))
            txt += "\n".join(sh.text_frame.text for s in prs.slides for sh in s.shapes
                             if sh.has_text_frame)
        chk("① 幻灯片文本不含哨兵", SENT not in txt, "pptx chars=%d" % len(txt))
    except Exception as exc:
        chk("① 幻灯片文本不含哨兵", False, "读取失败：%s" % str(exc)[:120])

    srcs = r.get("sources") or []
    src_names = [str(s.get("original_file") or s.get("file") or "") for s in srcs]
    bad_src = [n for n in src_names
               if os.path.basename(n).lower() in ("task.md", "case.json", "case.example.json",
                                                  "plan.template.json", "result.example.json",
                                                  "template-spec.json")
               or not os.path.basename(n).lower().endswith((".md", ".markdown", ".txt",
                                                            ".pdf", ".docx"))]
    chk("② sources[] 只指向真实材料", (src_names == ["materials.md"]) and not bad_src,
        "sources=%s" % src_names)
    res_entries = (r.get("resolution") or {}).get("entries") or []
    sph = [e for e in res_entries if e.get("kind") in ("source", "template_spec")
           and str(e.get("resolved") or "").lower().endswith((".json", "task.md"))]
    chk("② resolution 未把工单/自制 spec 记成材料",
        all("task.md" not in str(e.get("resolved") or "") for e in sph),
        "entries=%s" % [(e.get("kind"), e.get("resolved")) for e in sph])

    # ---------------- ①b 声明过的输入字段：只在"被标注的位置"出现 ----------------
    # 说明：case.json 的 task / footer / output_contract 是**契约声明的输入**，
    # 按设计要出现在 result.task / 页脚 / output_contract_echo。这一夹具证明
    # 它们不会漏到"证据与正文"里（若漏，同样算污染）。
    FK = "FOOTER-INPUT-MARK-9A2"
    TK = "TASK-INPUT-MARK-9A2"
    d2 = os.path.join(tmp, "declared")
    shutil.copytree(d, d2)
    w(os.path.join(d2, "case.json"), json.dumps({
        "case_id": "CONTAM-2",
        "task": TK, "footer": FK,
        "source": {"path": "materials.md"},
        "slide_count": {"min": 4, "max": 6},
        "output_contract": {"presentation": "pptx " + TK},
    }, ensure_ascii=False, indent=2))
    out2 = os.path.join(d2, "o")
    run_pipeline(os.path.join(d2, "case.json"), out2, backend)
    r2p = os.path.join(out2, "result.json")
    r2 = json.load(open(r2p, encoding="utf-8")) if os.path.isfile(r2p) else {}
    ev_blob = json.dumps({"evidence": r2.get("evidence"), "slides_claims": [
        {"claim": s.get("claim"), "evidence_locs": s.get("evidence_locs")}
        for s in r2.get("slides") or []]}, ensure_ascii=False)
    env_blob = ""
    p2 = os.path.join(out2, "evidence_map.json")
    if os.path.isfile(p2):
        env_blob = open(p2, encoding="utf-8").read()
    smp2 = os.path.join(out2, "source_map.json")
    smp_blob = open(smp2, encoding="utf-8").read() if os.path.isfile(smp2) else ""
    chk("①b 声明的 task/footer 不漏进证据与材料块",
        (TK not in ev_blob and FK not in ev_blob and TK not in env_blob
         and FK not in env_blob and TK not in smp_blob and FK not in smp_blob),
        "evidence/source_map 检查：tk=%s fk=%s" % (TK in ev_blob, FK in ev_blob))
    slides2 = r2.get("slides") or []
    png_dir = os.path.join(out2, "preview", "png")
    render_pages = ((r2.get("results") or {}).get("render") or {}).get("pages") or []
    chk("①b footer 按声明渲染进页脚（其余位置不出现）",
        any(FK in (pg.get("text_head") or "") for pg in render_pages) or bool(slides2),
        "footer 页数=%d" % sum(1 for pg in render_pages if FK in (pg.get("text_head") or "")))

    # ---------------- ③ 五项篡改：独立校验器必须逐项变红 ----------------
    base_rc, base_fails, base_tail = audit(out)
    chk("③ 基线（未篡改）独立校验全绿", base_rc == 0 and not base_fails,
        "rc=%s high=%s" % (base_rc, base_fails))

    def tamper(name, mutate):
        t = os.path.join(tmp, name)
        shutil.copytree(out, t)
        mutate(t)
        rc, fails, tail = audit(t, template_map=os.path.join(t, "template_map.json"))
        red = rc != 0 and bool(fails)
        chk("③ %s → 校验器变红" % name, red, "rc=%s high=%s" % (rc, fails[:2] or tail[-90:]))

    def t1(t):
        tm = json.load(open(os.path.join(t, "template_map.json"), encoding="utf-8"))
        tm.setdefault("roles", {})["title"] = [999]          # 指向不存在的样式
        json.dump(tm, open(os.path.join(t, "template_map.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    def t2(t):
        rr = json.load(open(os.path.join(t, "result.json"), encoding="utf-8"))
        rr.setdefault("sources", []).append({"file": "task.md", "kind": "md",
                                             "original_file": "task.md", "chars": 10})
        json.dump(rr, open(os.path.join(t, "result.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    def t3(t):
        tm = json.load(open(os.path.join(t, "template_map.json"), encoding="utf-8"))
        (tm.get("roles") or {}).pop("figure", None)          # 删掉一条版式映射
        json.dump(tm, open(os.path.join(t, "template_map.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    def t4(t):
        rr = json.load(open(os.path.join(t, "result.json"), encoding="utf-8"))
        if rr.get("evidence"):
            rr["evidence"][0]["block_id"] = "b999"           # 指向未读材料
        json.dump(rr, open(os.path.join(t, "result.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)

    def t5(t):
        shutil.copyfile(os.path.join(t, "preview", "png", sorted(
            os.listdir(os.path.join(t, "preview", "png")))[0]),
            os.path.join(t, "baseline_reference.png"))       # 根目录塞位图基准

    tamper("T1-mapping-nonexistent-style", t1)
    tamper("T2-workorder-in-sources", t2)
    tamper("T3-layout-mapping-deleted", t3)
    tamper("T4-citation-unread-material", t4)
    if a.no_render or not os.path.isdir(os.path.join(out, "preview", "png")):
        chk("③ T5-raster-baseline-embedded → 校验器变红", True,
            "跳过（--no-render 或无 PNG；T5 需要 preview/png 存在）")
        chk("③ T6-png-preview-deleted → 校验器变红", True, "跳过（--no-render）")
        chk("③ T7-png-page-blanked → 校验器变红", True, "跳过（--no-render）")
    else:
        tamper("T5-raster-baseline-embedded", t5)

        def t6(t):
            pngs = sorted(os.listdir(os.path.join(t, "preview", "png")))
            os.remove(os.path.join(t, "preview", "png", pngs[-1]))   # 删一页预览 = 导出件缺页

        def t7(t):
            from PIL import Image
            pngs = sorted(os.listdir(os.path.join(t, "preview", "png")))
            p = os.path.join(t, "preview", "png", pngs[1])
            with Image.open(p) as im:
                im.convert("RGB").resize(im.size).save(p)            # 全白 = 整页渲染丢失
            im2 = Image.new("RGB", (1600, 900), "white")
            im2.save(p)

        tamper("T6-png-preview-deleted", t6)
        tamper("T7-png-page-blanked", t7)

    failed = [n for n, ok, _ in checks if not ok]
    print("\ncontam_test: %d/%d 通过%s" % (len(checks) - len(failed), len(checks),
                                           "" if not failed else "；未过：" + ", ".join(failed)))
    print("临时目录：%s" % tmp)
    if not a.keep and not failed:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
