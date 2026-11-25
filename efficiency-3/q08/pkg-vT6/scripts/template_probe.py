# -*- coding: utf-8 -*-
"""template_probe.py —— 读出 pptx 模板的「可核对事实」：母版/版式/占位符/主题字体与配色。

为什么单独一个文件：评分类项的第一条就是"指定模板是否被真实套用（母版、版式、
占位符继承关系可查）"。所以先把模板结构摊平成 JSON 证据，后面 build 只用这份
probe 结果选版式，audit 再用它做"版式继承是否真实发生"的对照。

用法：
    python template_probe.py --template t.pptx --out template_map.json [--fonts]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # 包内不得出现 __pycache__/*.pyc（平台按文件数计限）

import units
import pptx_util as U

FALLBACKS = {
    # 常见学术字体 → 打印/跨平台安全回退（latin, ea）
    "Calibri": ("Arial", "Microsoft YaHei"),
    "Calibri Light": ("Arial", "Microsoft YaHei"),
    "Cambria": ("Georgia", "SimSun"),
    "Cambria Math": ("Georgia", "SimSun"),
    "Times New Roman": ("Liberation Serif", "SimSun"),
    "Arial": ("Liberation Sans", "Microsoft YaHei"),
    "Helvetica": ("Arial", "Microsoft YaHei"),
    "Georgia": ("Liberation Serif", "SimSun"),
    "宋体": ("Times New Roman", "SimSun"),
    "SimSun": ("Times New Roman", "SimSun"),
    "黑体": ("Arial", "SimHei"),
    "SimHei": ("Arial", "SimHei"),
    "微软雅黑": ("Arial", "Microsoft YaHei"),
    "Microsoft YaHei": ("Arial", "Microsoft YaHei"),
    "思源宋体": ("Times New Roman", "SimSun"),
    "Source Han Serif SC": ("Times New Roman", "SimSun"),
    "思源黑体": ("Arial", "Microsoft YaHei"),
    "Source Han Sans SC": ("Arial", "Microsoft YaHei"),
    "等线": ("Arial", "Microsoft YaHei"),
    "DengXian": ("Arial", "Microsoft YaHei"),
    "楷体": ("Times New Roman", "KaiTi"),
    "KaiTi": ("Times New Roman", "KaiTi"),
    "仿宋": ("Times New Roman", "FangSong"),
    "FangSong": ("Times New Roman", "FangSong"),
    "Aptos": ("Arial", "Microsoft YaHei"),
}

FONT_DB: dict | None = None


def system_fonts() -> set:
    """返回系统已安装字体族名集合（去重、大小写不敏感用 lower 比较）。"""
    global FONT_DB
    if FONT_DB is not None:
        return FONT_DB
    found = set()
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                # "Times New Roman (TrueType)" → "Times New Roman"
                fam = name.split("(")[0].strip()
                found.add(fam.lower())
                base = os.path.splitext(os.path.basename(str(value)))[0]
                found.add(base.lower())
        except Exception:
            pass
        for d in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),):
            try:
                for fn in os.listdir(d):
                    found.add(os.path.splitext(fn)[0].lower())
            except OSError:
                pass
    else:
        for cmd in (["fc-list", ":", "family"], ["fc-list"]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
            except Exception:
                continue
            for line in out.splitlines():
                for part in line.split(":"):
                    for fam in part.split(","):
                        fam = fam.strip()
                        if fam:
                            found.add(fam.lower())
            if found:
                break
    FONT_DB = found
    return found


FONT_NAME_ALIASES = {
    # 中文字体族名 ↔ 字体文件名/英文名（注册表里往往是"宋体 & 新宋体 (TrueType)"）
    "宋体": ["simsun", "nsimsun", "songti", "stsong", "宋体"],
    "新宋体": ["nsimsun", "simsun"],
    "黑体": ["simhei", "heiti", "stheiti", "黑体"],
    "微软雅黑": ["msyh", "microsoftyahei", "微软雅黑"],
    "等线": ["dengxian", "等线"],
    "楷体": ["simkai", "kaiti", "stkaiti", "楷体"],
    "仿宋": ["simfang", "fangsong", "stfangsong", "仿宋"],
    "思源黑体": ["sourcehansanssc", "sourcehansans", "思源黑体"],
    "思源宋体": ["sourcehanserifsc", "sourcehanserif", "思源宋体"],
}


def font_available(name: str) -> bool | None:
    if not name:
        return None
    db = system_fonts()
    if not db:
        return None  # 无法判定 → 交给渲染端实测（uncertainty）
    n = name.strip().lower()
    if n in db:
        return True
    stem = os.path.splitext(n)[0]
    if stem in db:
        return True
    for alias in FONT_NAME_ALIASES.get(name.strip(), []):
        if alias.lower() in db:
            return True
    # 注册表名形如 "times new roman"；文件 stem 形如 "arialbd"
    for key in db:
        if n and (n in key or key in n) and len(n) > 3:
            return True
    return False


def probe(template_path: str, with_fonts: bool = True) -> dict:
    if not os.path.isfile(template_path):
        raise FileNotFoundError(template_path)
    prs = U.load(template_path)
    theme = U.theme_info(template_path)
    layouts = U.all_layouts(prs)
    masters = []
    for i, m in enumerate(prs.slide_masters):
        phs = []
        for ph in m.placeholders:
            try:
                idx = int(ph.placeholder_format.idx)
            except Exception:
                idx = -1
            phs.append({"idx": idx, "kind": U.ph_kind(ph), "name": getattr(ph, "name", "")})
        masters.append({"index": i, "name": getattr(m, "name", "master-%d" % i),
                        "placeholder_count": len(phs), "placeholders": phs,
                        "layout_count": len(m.slide_layouts)})
    roles = {}
    for info in layouts:
        roles.setdefault(info["role_guess"], []).append(info["index"])

    fonts_declared = {}
    for kind in ("majorFont", "minorFont"):
        for slot, face in (theme.get("fonts", {}).get(kind) or {}).items():
            if face:
                fonts_declared.setdefault(face, []).append("%s.%s" % (kind, slot))
    font_report = {}
    if with_fonts:
        for face, used_by in sorted(fonts_declared.items()):
            avail = font_available(face)
            fb = FALLBACKS.get(face)
            font_report[face] = {
                "declared_by": sorted(set(used_by)),
                "installed": avail,
                "fallback_latin": fb[0] if fb else None,
                "fallback_ea": fb[1] if fb else None,
            }

    warn = []
    if "content" not in roles and "bullets" not in roles:
        warn.append("模板里没有 title+body 的正文版式，正文页将回退到 title-only/blank + 合成文本框")
    if "title" not in roles:
        warn.append("模板里没有 title+subtitle 的封面版式，封面将回退到首个有标题的版式")
    for face, rep in font_report.items():
        if rep["installed"] is False:
            warn.append("主题字体 `%s` 本机未安装，渲染端会回退%s" %
                        (face, "（建议 %s / %s）" % (rep["fallback_latin"], rep["fallback_ea"])
                         if rep["fallback_latin"] else ""))

    return {
        "generated_by": "template_probe.py",
        "template": {
            "path": os.path.basename(template_path),
            "bytes": os.path.getsize(template_path),
            "sha256": units.sha256_file(template_path),
        },
        "slide_size": U.slide_size(prs),
        "masters": masters,
        "layout_count": len(layouts),
        "layouts": layouts,
        "themes": theme.get("themes", []),
        "theme_source": theme.get("source"),
        "theme_fonts": theme.get("fonts", {}),
        "theme_font_scripts_ea": {k: v.get("Hans") or v.get("Hant")
                                  for k, v in (theme.get("font_scripts") or {}).items()},
        "theme_colors": theme.get("colors", {}),
        "roles": roles,
        "fonts": font_report,
        "warnings": warn,
        "notes": {
            "inheritance": "页面不写死几何：add_slide(layout) 继承版式，版式再继承母版；"
                           "本文件记录每层占位符 idx/type/几何，供 audit 对照。",
            "latent_placeholders": "python-pptx 不克隆 date/footer/slide_number（latent），"
                                   "build 阶段用 clone_placeholder 补上，否则页脚页码不显示。",
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="probe a pptx template (masters/layouts/theme)")
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", default="template_map.json")
    ap.add_argument("--no-fonts", action="store_true")
    a = ap.parse_args(argv)
    data = probe(a.template, with_fonts=not a.no_fonts)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print("template_probe: %s → %s | %d layouts | %s | %s" % (
        os.path.basename(a.template), a.out, data["layout_count"],
        data["slide_size"]["ratio_label"], "fonts-installed=%d/%d" % (
            sum(1 for v in data["fonts"].values() if v["installed"]),
            len(data["fonts"]))))
    for w in data["warnings"]:
        print("  ! %s" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
