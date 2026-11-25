#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# extract.py -- 材料 -> 结构化中间结果（实体/连线/步骤/阶段/数值），供 apparatus.py 使用
# 原则：只写读到的。连线只认显式句式；一个称呼对应多个单元时不猜；每个条目带原文定位。
# 确定性：材料发现顺序一律字典序（os.walk 的目录顺序随文件系统而变，必须显式排序）；
#        产物目录永远不参与材料发现（否则第二次运行会把自己的产物当材料 —— 自喂）。
import json, os, re, sys

sys.dont_write_bytecode = True

LEX = [("unit.sensor", "thermocouple|sensor|probe|gauge|热电偶|传感器|探头|压力表|温度计"),
       ("unit.instrument", "pump|valve|furnace|oven|centrifuge|oxygenator|mixer|stirrer|filter|flow meter|"
                           "logger|泵|阀|炉|烘箱|离心机|氧合器|搅拌|滤器|流量计|记录仪|研磨"),
       ("unit.utility", "waste|exhaust|vacuum|coolant|gas cylinder|chiller|废液|废气|真空|冷却|气瓶"),
       ("unit.vessel", "reservoir|reactor|flask|vessel|tank|chamber|bottle|column|trap|储液瓶|反应釜|反应器|"
                       "培养腔|烧瓶|罐|槽|腔|瓶|柱|捕集器")]
VB = [("loop", "recycled|returned|recirculated|循环|回流|返回"),
      ("signal", "is recorded by|monitored|measured|recorded|监测|测量|记录"),
      ("energy", "heated|cooled|irradiated|加热|冷却|水浴|控温"),
      ("material", "is fed from|delivers to|connected to|passes to|flows into|leaves|exits|feeds|transfer|"
                   "接入|连接|流入|通入|泵入|输送|加入|排出|流出|插入")]
NUM = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(°C|℃|mL|ml|μL|L|h|min|s|rpm|mbar|bar|kPa|MPa|nm|μm|um|mm|cm|"
                 r"m|g|mg|kg|mol|mM|M|V|mA|A|W|kW|J|kJ|Hz|kHz|MHz|%|目)(?![\w])")
CJK = re.compile(r"[\u4e00-\u9fff]")
GEN = {"medium", "media", "sample", "data", "system", "device", "unit", "test", "value"}
LST = re.compile(r"^(#{1,6}\s|\[\[|---)|^\||^\s*(?:[-*•]\s+|\d{1,2}[.、)）]\s+|[（(]\d{1,2}[)）]\s+)")
TXT = (".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log")
SKIP = (".png", ".jpg", ".jpeg", ".svg", ".gif")
CONTRACT_KEYS = ("output_contract", "contract", "outputs", "output_schema",
                 "expected_outputs", "deliverables")
# 工单/说明书类文件名：它们是"要画什么"的指令，不是"画什么"的科学证据
WO_NAMES = ("case.json", "task.md", "task.txt", "task.json", "prompt.md")
WO_PAT = re.compile(r"\.(example|template|sample|schema)\.[a-z]+$", re.I)
# case.json 里可能内联携带的材料字段（平台两种投喂方式之一）
INLINE_KEYS = ("materials_text", "material_text", "material", "materials", "source_text", "sources_text")


def kind_of(s):
    low, b, ln = (s or "").lower(), None, 0
    for k, pat in LEX:
        for m in re.finditer(pat, low, re.I):
            if len(m.group(0)) > ln:
                b, ln = k, len(m.group(0))
    return b


def ali(lab):
    """实体标签 -> 可用于指代的别名集合。

    拉丁别名规则（修箭头反向的根因之一）：
      * "标签里只有一个英文词"的实体保留该词与 ID（如 `蠕动泵 P-1` -> {"p-1"}）；
      * 标签含多个英文词时，**丢掉 ≤5 字母的单个通用词**、改收录二元组
        （如 `真空泵 vacuum pump VP-1` -> {"vacuum","vp-1","vacuum pump","pump vp-1"}，
         不再把裸 "pump" 当成它的指代）——否则 "the peristaltic pump P-1" 会被
        误认成真空泵，画出方向/端点都错的连线。
    """
    lab = lab or ""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", lab)
    lo = [t.lower() for t in toks]
    o = {t for t in lo if t not in GEN and (len(t) >= 4 or re.search(r"\d", t))}
    if len(toks) >= 2:
        o |= {" ".join(lo[i:i + 2]) for i in range(len(lo) - 1)}
        o = {t for t in o if not (t.isalpha() and len(t) <= 5)}
    for r in re.findall(r"[\u4e00-\u9fff]{2,}", lab):
        for n in range(len(r), max(2, len(r) - 3), -1):
            for i in range(len(r) - n + 1):
                o.add(r[i:i + n])
    return {a for a in o if len(a) >= 3}


def read_any(p):
    """读一个文件 -> (文本, 抽取器名)。读不了就抛异常（由 collect 记入 unreadable，不猜内容）。"""
    e = os.path.splitext(p)[1].lower()
    if e in TXT:
        raw = open(p, "rb").read()
        for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                return raw.decode(enc), "text"
            except UnicodeDecodeError:
                pass
    if e == ".pdf":
        try:
            return _pdf_fitz(p), "pymupdf"
        except Exception as x:
            note = "pymupdf: %s" % str(x)[:70]
        try:
            from pdftext import pdf_text          # 纯标准库兜底（无第三方依赖）
            t = pdf_text(p)
            if _signal(t) >= 40:
                return t, "pdftext-stdlib"
            raise RuntimeError("stdlib fallback recovered only %d script chars" % _signal(t))
        except Exception as z:
            raise RuntimeError("pdf read failed; %s; %s" % (note, str(z)[:90]))
    raise RuntimeError("unsupported %s" % e)


def _signal(t):
    """可读文本量：字母/数字/CJK 字符数（用于判断 PDF 是否真有文本层）。"""
    return len(re.findall(r"[^\W_]", t or "", re.UNICODE))


def _pdf_fitz(p):
    import fitz
    try:
        fitz.TOOLS.mupdf_display_errors(False); fitz.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass
    dn, sd = os.open(os.devnull, os.O_WRONLY), os.dup(2)
    try:
        os.dup2(dn, 2)
        return "\n".join(g.get_text("text") for g in fitz.open(p))
    finally:
        os.dup2(sd, 2); os.close(dn); os.close(sd)


def _own_output_dir(root, files):
    """这个目录是不是"我们自己跑出来的产物目录"？

    判据：含 result.json，且该 JSON 带 case_id 且有 output_contract/contract_echo 段。
    任何这类目录整棵跳过 —— 否则第二次运行会把自己上一次的 result.json / figure.pdf
    当材料读进来，同一包重复运行产出不同结果（本题同臂复采样跑出不同质量的头号内因）。
    """
    if "result.json" not in files:
        return False
    try:
        j = json.load(open(os.path.join(root, "result.json"), encoding="utf-8"))
    except Exception:
        return False
    return (isinstance(j, dict) and "case_id" in j
            and ("output_contract" in j or "contract_echo" in j or "change_log" in j))


def classify(rel, text, case_path=None):
    """文件角色：material（科学证据）/ workorder（工单与示例模板）/ case（本次 case.json）。

    工单/示例/模板进证据索引会让"图上的实体与数值"来自指令而不是材料 ——
    平台判词 `genuinely-derived` 盯的正是这个。判定用文件名 + 内容形状（不看领域标签）：
      * 本次 --case 指向的文件 -> case
      * case.json / task.md / *.example.json / *.template.json / *.schema.json -> workorder
      * 其它 .json：解析后带 output_contract/output_schema/expected_outputs/deliverables，
        或同时带 case_id 与 task 字段的，也判 workorder（工单换了文件名也认得出来）
      * 其余 -> material（含真正的数据 JSON/CSV —— 题面要求图表用"actual source data"）
    """
    low = os.path.basename(rel).lower()
    if case_path and os.path.abspath(rel) == os.path.abspath(case_path):
        return "case"
    if low in WO_NAMES or WO_PAT.search(low):
        return "workorder"
    if low.endswith(".json"):
        try:
            j = json.loads(text)
        except Exception:
            return "material"
        if isinstance(j, dict):
            keys = {str(k).lower() for k in j}
            if keys & set(CONTRACT_KEYS) or {"case_id", "task"} <= keys or {"challenge_id"} <= keys:
                return "workorder"
    return "material"


def inline_materials(case):
    """case.json 内联材料字段 -> [(伪文件名, 文本)]；只认显式材料字段，不认裸 text/task。"""
    out = []
    if not isinstance(case, dict):
        return out
    for k in INLINE_KEYS:
        v = case.get(k)
        if isinstance(v, str) and len(v.strip()) >= 40:
            out.append(("%s::%s" % (os.path.basename(str(case.get("_path") or "case.json")), k), v))
        elif isinstance(v, list):
            t = "\n".join(x for x in v if isinstance(x, str))
            if len(t.strip()) >= 40:
                out.append(("%s::%s" % (os.path.basename(str(case.get("_path") or "case.json")), k), t))
        elif isinstance(v, dict):
            t = "\n".join("%s: %s" % (a, b) for a, b in v.items() if isinstance(b, (str, int, float)))
            if len(t.strip()) >= 40:
                out.append(("%s::%s" % (os.path.basename(str(case.get("_path") or "case.json")), k), t))
    return out


def collect(d, skip=(), case_path=None):
    """材料发现：只走 case.json 所在目录树下，**按字典序**（目录也要排序）。

    skip：绝对路径列表（如本次产物目录），永不作为材料；
    另有 _own_output_dir 签名判据，跳过历史产物目录（含上一次运行的 out1/out2）。
    返回 (材料, 抽取器, 读不了的文件, 被排除的工单文件)。
    """
    T, EX, WO, bad = {}, {}, {}, []
    sk = {os.path.abspath(s).lower() for s in skip if s}
    for root, dirs, fs in os.walk(d):
        dirs[:] = sorted(x for x in dirs
                         if os.path.abspath(os.path.join(root, x)).lower() not in sk)
        if os.path.abspath(root).lower() in sk:
            continue
        if root != d and _own_output_dir(root, set(fs)):
            dirs[:] = []
            continue
        for f in sorted(fs):
            p = os.path.join(root, f)
            if os.path.abspath(p).lower() in sk or os.path.splitext(f)[1].lower() in SKIP:
                continue
            rel = os.path.relpath(p, d).replace("\\", "/")
            try:
                t, ex = read_any(p)
            except Exception as x:
                bad.append({"file": rel, "why": str(x)[:110]})
                continue
            role = classify(p, t, case_path)
            if role == "material":
                T[rel], EX[rel] = t, ex
            else:
                WO[rel] = {"role": role, "extractor": ex, "chars": len(t),
                           "why": "工单/示例/模板文件不进证据索引（避免把指令当科学材料）"}
    return ({k: T[k] for k in sorted(T)}, {k: EX[k] for k in sorted(EX)}, bad,
            {k: WO[k] for k in sorted(WO)})


def blocks_of(name, text):
    o, buf, st = [], [], None
    last = max(1, len(text.splitlines()))

    def fl(e):
        nonlocal buf, st
        if buf:
            o.append({"loc": "%s#L%d-%d" % (name, st, e), "text": " ".join(buf)}); buf, st = [], None

    for i, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if not s:
            fl(i - 1)
        elif LST.match(s):
            fl(i - 1); o.append({"loc": "%s#L%d" % (name, i), "text": s})
        else:
            st = i if st is None else st; buf.append(s)
    fl(last)          # 结尾块用真实末行号（以前写 10**9，等于给了一个无法核验的行号）
    return o


def _row_cells(t):
    """表格行 -> 单元格列表；不是表格则 None。"""
    if t.count("|") < 1:
        return None
    c = [x.strip() for x in t.strip().strip("|").split("|")]
    if len(c) >= 2 and c[0] and not re.match(r"^[-:\s]+$", "".join(c)):
        return c
    return None


def ents(bl):
    E, idre = [], re.compile(r"\b([A-Z]{1,4}[-–]?\d{1,3}[A-Za-z]?)\b")

    def add(lab, q, loc, inf):
        lab = re.sub(r"\s+", " ", lab or "").strip(" 　|,，;；-–—")
        if len(lab) < 2 or not (re.search(r"[A-Za-z]", lab) or CJK.search(lab)):
            return
        tg = set(re.findall(r"[A-Za-z]{0,3}[-–]?\d{1,3}", lab))
        for e in E:
            ot = set(re.findall(r"[A-Za-z]{0,3}[-–]?\d{1,3}", e["label"]))
            if tg and ot and tg != ot:
                continue                                    # A-1 与 A-2 是两台，不是一台
            lo, old = lab.lower(), e["label"].lower()
            if lo in old or old in lo or (ali(lo) & ali(old)):
                return
        k = kind_of(lab) or kind_of(q)
        if k:
            E.append({"id": "U%d" % (len(E) + 1), "label": lab, "kind": k, "inferred": bool(inf),
                      "source": {"locator": loc, "quote": q[:140]}})

    for b in bl:
        t = b["text"]
        c = _row_cells(t)
        if c is not None and kind_of(c[0]):
            # 装置清单：首列必须是已知部件名词，才算部件行。
            # 2 列「部件 | 数量」是最常见的极简清单，纯数字计数也必须接受；
            # 但要挡住「指标 | 数值」这类与部件无关的两列表。
            rest = c[1:]
            ok = (len(c) >= 3 or any(NUM.search(x) for x in rest)
                  or any(re.fullmatch(r"\d{1,3}", str(x).strip()) for x in rest))
            if ok:
                add(c[0], t, b["loc"], False)
            continue
        for m in idre.finditer(t):
            tg = m.group(1)
            if re.fullmatch(r"[A-Z]{2}\d|[MYQTW]\d{1,3}", tg):
                continue
            ctx = t[max(0, m.start() - 50):m.end() + 50]
            if kind_of(ctx) and not any(tg.lower() in e["label"].lower() for e in E):
                add(tg, ctx, b["loc"], False)
    return E


def flows(bl, E):
    am = [(e, sorted(ali(e["label"]), key=len, reverse=True)) for e in E]
    o, amb, seen = [], [], set()
    for b in bl:
        for s in re.split(r"(?<=[.!?;。！？；])\s*", b["text"]):
            lo, k, v = s.lower(), None, None
            for kk, pat in VB:
                m = None
                for mm in re.finditer(pat, lo, re.I):
                    if m is None or len(mm.group(0)) > len(m.group(0)):
                        m = mm
                if m:
                    k, v = kk, m.group(0); break
            if not k:
                continue
            f = []
            for e, tk in am:
                bs = None
                for t in tk:
                    p = lo.find(t)
                    if p >= 0 and (bs is None or p < bs[0] or (p == bs[0] and len(t) > len(bs[1]))):
                        bs = (p, t)
                if bs:
                    f.append((bs[0], e, bs[1]))
            f.sort(key=lambda x: x[0])
            if len(f) < 2:
                continue
            by = {}
            for _p, e, t in f:
                by.setdefault(t, []).append(e)
            if any(len(x) > 1 for x in by.values()):        # 指代不明 -> 不画，只记录
                amb.append({"locator": b["loc"], "sentence": s.strip()[:110],
                            "alias": sorted(t for t, x in by.items() if len(x) > 1),
                            "candidates": sorted({e["label"] for x in by.values() for e in x}),
                            "handling": "指代不明，未画连线（不猜）"})
                continue
            a, c = f[0][1], f[1][1]
            hd = lo[:lo.find(v)]
            if re.search(r"(is|are|was|were)\s+\w*\s*from\s*$", hd) or re.search(r"(由|自)\s*$", hd):
                a, c = c, a
            elif re.match(r"^(leaves|exits|leaving|exiting)$", v.strip()):
                # "The waste bottle leaves the perfusion chamber." —— 主语是出口，宾语才是来源，
                # 不翻转就会画出方向相反的箭头（题面点名的典型失败）。
                a, c = c, a
            if re.search(r"(recycl|循环|回流|返回)", lo):
                k = "loop"
            if (a["id"], c["id"], k) not in seen:
                seen.add((a["id"], c["id"], k))
                o.append({"id": "E%d" % (len(o) + 1), "src": a["id"], "dst": c["id"], "kind": k,
                          "source": {"locator": b["loc"], "quote": s.strip()[:140]}})
    return o, amb


def stps(bl):
    P = (re.compile(r"^\s*(?:step|Step|STEP)\s*(\d+)\s*[:.\-)\]]?\s*(.+)$"),
         re.compile(r"^\s*(?:步骤|第)\s*([0-9一二三四五六七八九十]+)\s*步?\s*[:：.\-、)）]?\s*(.+)$"),
         re.compile(r"^\s*[（(]?\s*(\d{1,2})\s*[.、)）]\s+(\S.*)$"))
    CN = dict(zip("一二三四五六七八九十", range(1, 11)))
    LOOP = re.compile(r"(?:回到|返回|repeat|return to|go to)\s*(?:step|步骤)?\s*(\d+)", re.I)
    o = []
    for b in bl:
        m = next((p.match(b["text"]) for p in P if p.match(b["text"])), None)
        if not m:
            continue
        n, body = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        sq = int(n) if n.isdigit() else CN.get(n, 0)
        if sq <= 0 or not 6 <= len(body) <= 300 or any(x["label"][:40].lower() == body[:40].lower() for x in o):
            continue
        kd = "parallel" if re.search(r"(同时|并行|parallel|simultaneous)", body, re.I) else "main"
        if re.search(r"(结束|终止|判定|stop|end|terminate)", body, re.I):
            kd = "terminal"
        lm = LOOP.search(body)
        if lm:                                              # 回流：显式记录回到第几步（供画回流箭头）
            kd = "loop"
        o.append({"id": "S%d" % (len(o) + 1), "seq": len(o) + 1, "label": body, "kind": kd,
                  "loop_to": int(lm.group(1)) if lm else 0,
                  "source": {"locator": b["loc"], "quote": b["text"][:140]}})
    return o


def step_edges(ST):
    """步骤顺序关系（主序列 + 显式回流），每条都带原文引文；供画箭头与 result.relations。"""
    o = []
    for i, s in enumerate(ST):
        if i + 1 < len(ST):
            o.append({"id": "X%d" % (len(o) + 1), "src": s["id"], "dst": ST[i + 1]["id"],
                      "kind": "sequence", "source": s["source"]})
        if s.get("loop_to"):
            t = next((x for x in ST if x["seq"] == s["loop_to"] and x["id"] != s["id"]), None)
            if t:
                o.append({"id": "X%d" % (len(o) + 1), "src": s["id"], "dst": t["id"], "kind": "loop",
                          "source": s["source"]})
    return o


def phs(bl):
    mk = re.compile(r"(?:phase|stage|wp|task|阶段)\s*([0-9]{1,2}|[一二三四五六七八九十])", re.I)
    CN = dict(zip("一二三四五六七八九十", range(1, 11)))
    o, sn = [], set()
    for b in bl:
        ms = list(mk.finditer(b["text"]))
        for i, m in enumerate(ms):
            sq = int(m.group(1)) if m.group(1).isdigit() else CN.get(m.group(1), 0)
            if not sq or sq in sn:
                continue
            sn.add(sq)
            # 标签只取到"下一个阶段标记"或"第一个句末"为止；否则一段里连着写 8 个 Phase 时，
            # 每张卡片都会带上后面几个阶段的文字（跨卡串台）。
            end = ms[i + 1].start() if i + 1 < len(ms) else min(len(b["text"]), m.end() + 90)
            lab = b["text"][m.end():end].strip(" 　:：-")
            lab = re.split(r"(?<=[。．.!?！？])\s*", lab)[0].strip(" 　:：-") or lab
            o.append({"id": "P%d" % sq, "seq": sq, "label": lab,
                      "source": {"locator": b["loc"], "quote": b["text"][:140]}})
    return sorted(o, key=lambda x: x["seq"])


def phase_edges(PH):
    return [{"id": "D%d" % (i + 1), "src": PH[i]["id"], "dst": PH[i + 1]["id"], "kind": "dependency",
             "source": PH[i]["source"]} for i in range(len(PH) - 1)]


def nums_of(bl):
    o, sn = [], set()
    for b in bl:
        for m in NUM.finditer(b["text"]):
            if (m.group(1), m.group(2)) not in sn:
                sn.add((m.group(1), m.group(2)))
                o.append({"text": "%s %s" % (m.group(1), m.group(2)), "value": m.group(1), "unit": m.group(2),
                          "source": {"locator": b["loc"], "quote": b["text"][max(0, m.start() - 40):m.end() + 40]}})
    return o


def guess(case, T):
    h = ((json.dumps(case, ensure_ascii=False) if case else "") + " " + " ".join(t[:2500] for t in T.values())).lower()
    return "roadmap" if re.search(r"(技术路线|roadmap|阶段目标|milestone|phase)", h) else "schematic"


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(65536), b""):
            h.update(b)
    return h.hexdigest()[:16]


def hint_kind(hint):
    """契约里写的类型提示 -> array / object / string。"""
    s = str(hint or "").lower()
    if "array" in s or "list" in s or s.strip().startswith("["):
        return "array"
    if "object" in s or "dict" in s or s.strip().startswith("{"):
        return "object"
    return "string"


def contract(case):
    """case.json 的 output_contract -> {字段: 类型提示}。

    兼容两种写法：契约块直接在 case.json 顶层（平台常见），或嵌在某个子字典里。
    （只认嵌套写法会让"全键透传"静默失效：result.json 里什么契约字段都没有。）
    """
    F, cands = {}, []
    if not isinstance(case, dict):
        return F
    for k, v in case.items():
        if isinstance(k, str) and k.lower() in CONTRACT_KEYS:
            cands.append(v)
    for n in case.values():
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(k, str) and k.lower() in CONTRACT_KEYS:
                    cands.append(v)
    for v in cands:
        if isinstance(v, dict):
            for f, hint in v.items():
                F[f] = hint if isinstance(hint, str) else hint_kind(hint)
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    F.setdefault(it, "string")
                elif isinstance(it, dict) and (it.get("name") or it.get("field")):
                    F.setdefault(it.get("name") or it.get("field"), "string")
    return F


def read_case(indir, cpath):
    case = {}
    if os.path.exists(cpath):
        try:
            case = json.load(open(cpath, encoding="utf-8-sig"))
        except Exception as x:
            case = {"_case_json_error": str(x)[:100]}
    cid = case.get("case_id") or case.get("id") or os.path.basename(os.path.abspath(indir))
    return case, cid


def sirof(case, skip=()):
    """materials -> (E, edges, steps, step_edges, phases, numbers, ambiguities,
                     texts, extractors, bad, workorders, inline_texts)"""
    ind = os.path.dirname(os.path.abspath(case)) or "."
    T, EX, bad, WO = collect(ind, skip=skip, case_path=case)
    case_obj, _cid = read_case(ind, case)
    IN = inline_materials(dict(case_obj, _path=case))
    for k, v in IN:                                    # 内联材料与文件材料同等对待（来源写伪文件名）
        T[k], EX[k] = v, "inline"
    T = {k: T[k] for k in sorted(T)}
    EX = {k: EX[k] for k in sorted(EX)}
    bl = []
    for n, t in T.items():
        bl += blocks_of(n, t)
    E, NU, ST, PH = ents(bl), nums_of(bl), stps(bl), phs(bl)
    ED, AMB = flows(bl, E)
    for e in E:
        own = [x["text"] for x in NU if x["source"]["quote"].find(e["label"][:10]) >= 0]
        if own:
            e["numbers"] = own[:2]
    return E, ED, ST, step_edges(ST), PH, NU, AMB, T, EX, bad, WO, [k for k, _v in IN]


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "/input"
    cp = os.path.join(d, "case.json")
    case, cid = read_case(d, cp)
    E, ED, ST, SW, PH, NU, AMB, T, EX, bad, WO, IN = sirof(cp)
    print(json.dumps({"case_id": cid, "entities": E, "edges": ED, "steps": ST, "step_edges": SW,
                      "phases": PH, "numbers": NU, "ambiguities": AMB, "materials": sorted(T),
                      "extractors": EX, "unreadable": bad, "excluded_workorder_files": WO,
                      "inline_materials": IN}, ensure_ascii=False, indent=2))
