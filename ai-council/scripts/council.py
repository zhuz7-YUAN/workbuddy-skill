# -*- coding: utf-8 -*-
"""
AI Council 主流程：分层抽签 -> 澄清轮 -> 主轮 -> 证据权重汇总

用法：
  python council.py --facts facts.txt --question "该不该给" --seats 8
  python council.py --facts facts.txt --question "..." --seed 42      # 复现同一次抽签
  python council.py --facts facts.txt --question "..." --names A,B,C  # 指定模式（跳过抽签）
  python council.py --facts facts.txt --question "..." --skip-clarify # 跳过澄清轮
"""
import argparse, json, os, random, re, ssl, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

ssl._create_default_https_context = ssl._create_unverified_context

SF_URL = "https://api.siliconflow.cn/v1/chat/completions"


def _key():
    """兼容旧逻辑的兜底 key。池内模型自带 key，这里拿不到也无所谓，返回 None 即可。"""
    for p in (os.path.expanduser("~/.workbuddy/models.json"),
              os.path.expanduser("~/.codebuddy/models.json")):
        if not os.path.exists(p):
            continue
        try:
            models = json.load(open(p, encoding="utf-8")).get("models", [])
        except (OSError, ValueError):
            return None
        for m in models:
            if "siliconflow" in m.get("url", "") and m.get("apiKey"):
                return m["apiKey"]
    return None


KEY = _key()

# 陪审团模型池：直接读你本机 models.json 里配置的所有「硅基流动」模型。
# 不再写死模型名——写死的虚构版本号（如 DeepSeek-V4-Flash / Kimi-K2.7-Code /
# Qwen3.5-397B）在硅基流动真实 API 上根本不存在，会导致全员 404、在任何人电脑上都跑不通。
# 想让陪审团更大、更跨厂商，就在 free-llm-setup 里多配几家硅基流动模型（配置即生效）。
VENDOR_MAP = [
    ("deepseek-ai/", "DeepSeek"), ("Qwen/", "阿里通义"), ("THUDM/", "智谱"),
    ("zai-org/", "智谱"), ("moonshotai/", "月之暗面"), ("MiniMaxAI/", "MiniMax"),
    ("stepfun-ai/", "阶跃星辰"), ("tencent/", "腾讯混元"),
    ("ByteDance-Seed/", "字节"), ("meituan-longcat/", "美团"),
    ("Pro/deepseek-ai/", "DeepSeek"),
]
_REASON_IDS = ("R1", "QwQ", "reasoning", "o1", "DeepSeek-R1", "QwQ-32B", "-R1")


def _vendor_of(model_id):
    for pref, v in VENDOR_MAP:
        if model_id.startswith(pref):
            return v
    return model_id.split("/")[0] if "/" in model_id else model_id


def _load_pool():
    p = None
    for cand in (os.path.expanduser("~/.workbuddy/models.json"),
                 os.path.expanduser("~/.codebuddy/models.json")):
        if os.path.exists(cand):
            p = cand
            break
    if p is None:
        raise SystemExit(
            "没找到 ~/.workbuddy/models.json，陪审团组不起来。\n"
            "解决：运行 free-llm-setup 一键配置免费大模型，\n"
            "      或手动创建 models.json 并加至少一条带 apiKey 和 url 的模型。")
    try:
        models = json.load(open(p, encoding="utf-8")).get("models", [])
    except ValueError as e:
        raise SystemExit(f"models.json 不是合法 JSON，解析失败：{e}\n"
                         "解决：检查文件内容，或重新运行 free-llm-setup 生成。")
    pool = []
    for m in models:
        if not m.get("apiKey") or not m.get("url"):
            continue
        mid = m.get("id") or m.get("name")
        if not mid:
            continue
        pool.append({
            "vendor": _vendor_of(mid),
            "model": mid,
            "kind": "reasoning" if any(k in mid for k in _REASON_IDS) else "fast",
            "label": m.get("name", mid),
            "url": m["url"],
            "apiKey": m["apiKey"],
        })
    if not pool:
        raise SystemExit(
            "models.json 里没有任何带 apiKey 的模型，陪审团组不起来。\n"
            "解决：运行 free-llm-setup 选「硅基流动」路线一键配置，\n"
            "      或手动在 models.json 加至少一条带 apiKey 和 url 的模型。")
    return pool


POOL = _load_pool()

# 裁判必须与陪审团池严格隔离：选手不能给自己打分。
# 默认不启用模型裁判（规则打分更确定、可复现、零额外调用、无利益冲突）。
# --judge 才启用；若指定的裁判恰好在池内，llm_weigh 会自动拒绝并退回规则打分。
JUDGE = None
JUDGE_FORBIDDEN = {m["model"] for m in POOL}   # 任何在池内的模型都不得当裁判

# 规则打分词典（默认走这条路：确定性、可复现、每一分都能解释）
HEDGE = ["都有可能", "视情况", "难以判断", "不好说", "建议咨询", "取决于", "两边",
         "各有利弊", "见仁见智", "无法给出", "需要权衡", "综合考虑", "不太好判断",
         "因人而异", "不一定", "也许", "或许", "可能吧"]
CAUSAL = ["因为", "所以", "导致", "意味着", "如果", "则", "由于", "因此",
          "说明", "表明", "一旦", "于是", "根源", "本质上", "真正的"]
ACTION = ["先", "第一步", "其次", "最后", "条件", "止损", "截止", "之前",
          "之后", "应当", "立即", "立刻", "冻结", "暂停", "设立", "协议", "节点"]
NUMRE = re.compile(r"\d+\s*(天|周|个月|月|年|万|亿|%|倍|美元|元|次)")


def _grams(t, n=4):
    s = re.sub(r"\s+", "", t)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def rule_weigh(answers):
    """规则打分：确定性、可复现、零额外调用。权重判据全部公示。"""
    pools = [_grams(a["text"]) for a in answers]
    novelty = []
    for i, g in enumerate(pools):
        others = [p for j, p in enumerate(pools) if j != i]
        if not others:
            novelty.append(0.0)
            continue
        uniq = len(g - set().union(*others))
        novelty.append(uniq / max(len(g), 1))

    # 独立信息只给少数派：取 70 分位作门槛，避免人人有份
    ranked = sorted(novelty)
    gate = max(0.4, ranked[min(len(ranked) - 1, int(len(ranked) * 0.7))])

    for i, a in enumerate(answers):
        t, w, why = a["text"], 1.0, []
        hedge = sum(t.count(h) for h in HEDGE)
        if hedge >= 2 or (hedge >= 1 and len(t) < 700):
            w *= 0.3
            why.append("骑墙×0.3")
        if NUMRE.search(t):
            w += 0.3
            why.append("可证伪+0.3")
        if sum(t.count(c) for c in CAUSAL) >= 3:
            w += 0.3
            why.append("推理链+0.3")
        if sum(t.count(x) for x in ACTION) >= 3:
            w += 0.3
            why.append("可执行+0.3")
        if novelty[i] >= gate:
            w += 0.2
            why.append(f"独立信息+0.2({novelty[i]:.0%}独有)")
        # 不按字数扣分：简洁而准确的答案不该被罚，啰嗦而空洞的不该被奖
        a["base"] = round(max(0.3, min(2.1, w)), 2)
        a["why"] = "；".join(why) or "基线1.0，无加分项"

    # 相对排名系数。只看绝对分的话各家挤在 1.3~1.8，加权形同虚设——
    # 实测原始票 60% vs 加权票 66%，等于一人一票。必须拉开档位差。
    n = len(answers)
    if n >= 3:
        # 按严格名次切分，不能用阈值——并列分会让「前1/3」膨胀成「前7/9」
        order = sorted(answers, key=lambda a: -a["base"])
        k = max(1, n // 3)
        for i, a in enumerate(order):
            if i < k:
                a["weight"] = round(a["base"] * 1.3, 2)
                a["why"] += "｜本次前1/3 ×1.3"
            elif i >= n - k:
                a["weight"] = round(a["base"] * 0.8, 2)
                a["why"] += "｜本次后1/3 ×0.8"
            else:
                a["weight"] = a["base"]
    else:
        for a in answers:
            a["weight"] = a["base"]
    return True


def llm_weigh(answers, picked=None):
    """可选：模型裁判。必须在陪审团池之外，否则选手给自己打分。"""
    if JUDGE is None:
        return False
    if JUDGE in JUDGE_FORBIDDEN or (picked and JUDGE in {m["model"] for m in picked}):
        print("  [拒绝] 裁判模型在陪审团名单内，选手不能给自己打分，退回规则打分")
        return False
    blob = "\n\n".join(f"--- 回答 {i+1}（{a['vendor']} {a['label']}）---\n{a['text'][:2600]}"
                       for i, a in enumerate(answers))
    try:
        raw, _ = call(JUDGE, "你是严格的计票裁判，只输出 JSON 数组，不要任何解释文字。",
                      WEIGH_Q.format(answers=blob), max_tokens=1024)
        m = re.search(r"\[.*\]", raw, re.S)
        rows = json.loads(m.group(0))
        wmap = {int(r["id"]) - 1: (float(r["weight"]), r.get("reason", "")) for r in rows}
        miss = 0
        for i, a in enumerate(answers):
            if i in wmap:
                w, reason = wmap[i]
                a["weight"] = round(max(0.4, min(2.1, w)), 2)
                a["why"] = reason
            else:
                a["weight"], a["why"], miss = 1.0, "裁判漏项，等权", miss + 1
        return miss == 0
    except Exception as e:
        print("  [警告] 模型裁判失败，退回规则打分：", str(e)[:120])
        return False

SANDBOX = """你是决策顾问。现在是 {when}。

严格约束：
1. 你只知道下面给出的这些事实。不要用你记忆里任何关于此事的公开信息去补全。
2. 不得推测提问者的心理、动机或期望。
3. 不得出现「您可能希望」「如果您在意的是」「建议您考虑」这类措辞。
4. 不得先复述提问者的立场再回答。
5. 不得因为问题涉及情感就软化判断。
6. 直接给判断。不要两边都不得罪，不要空谈道德。"""

CLARIFY_Q = """你是陪审团第 {seat} 位成员。现在轮到你向当事人提一个事实性问题。

【前面成员已经问过的问题】
{history}

硬性规则：
- 不许重复上面任何一个问题，也不许换个说法问同一件事。重复的问题会被作废。
- 必须问一个前面没人问过的、新的角度。
- 只提事实性问题——时间、金额、数量、约束条件、已经发生的行为。
- 不许提建议，不许猜当事人的想法，不许问"你怎么看"。

已知事实：
{facts}

主问题是：{question}

只输出一行，一个问号结尾的问题。不要编号，不要解释，不要多余空行。"""

WEIGH_Q = """你是计票裁判。下面有若干份针对同一问题的回答。
按 rubric 给每一份打权重，权重只看这份答案本身的质量，不许考虑它是哪个模型说的。

基础分 1.0，逐项累加：
- 骑墙（没给明确结论、两边都不得罪）：直接 ×0.4（乘法打折）
- 可证伪（给出具体后果、数字、时间点）：+0.3
- 推理链（从事实推到结论，不是直接抛结论）：+0.3
- 可执行（给出下一步动作、条件或止损线）：+0.3
- 独立信息（提到别人都没看到的事实或角度）：+0.2

权重区间 0.4 ~ 2.1。

严格按 JSON 数组输出，不要任何解释文字：
[{{"id": 1, "weight": 1.9, "reason": "一句话，20字内"}}, ...]

回答如下：
{answers}"""


def call(model, system, user, max_tokens=4096, timeout=300, allow_reasoning=True):
    meta = next((x for x in POOL if x["model"] == model), None)
    url = meta["url"] if meta else SF_URL
    api_key = meta["apiKey"] if meta else KEY
    payload = {"model": model,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "max_tokens": max_tokens, "temperature": 0.7}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + api_key,
                                          "Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    msg = r["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    if not text:
        # 纯推理模型思考太长时会把 max_tokens 吃光，content 为空。
        # 结构化输出场景（澄清轮/裁判）必须拒绝 reasoning 兜底，否则拿回的是思考过程。
        if not allow_reasoning:
            raise RuntimeError(f"{model} 未返回正文（thinking 吃光 token 或纯推理模型）")
        text = "[reasoning] " + (msg.get("reasoning_content") or "").strip()
    return text, round(time.time() - t0, 1)


def draw(pool, seats=8, seed=None, names=None):
    """分层抽签：每厂商优先 1 席（保证厂商多样性），厂商不足 seats 时用同厂商其它模型补满。
    names 非空则走指定模式。"""
    if names:
        picked = [m for m in pool if m["label"] in names or m["vendor"] in names]
        return picked, f"指定模式（{len(picked)} 席，存在常驻偏见风险）"
    rng = random.Random(seed)
    by_vendor = {}
    for m in pool:
        by_vendor.setdefault(m["vendor"], []).append(m)
    vendors = list(by_vendor)
    rng.shuffle(vendors)
    picked = [rng.choice(by_vendor[v]) for v in vendors[:min(seats, len(vendors))]]
    # 厂商数不足 seats 时，用未入选的同厂商模型补满，让陪审团更完整
    if len(picked) < seats:
        used = {m["model"] for m in picked}
        leftovers = [m for m in pool if m["model"] not in used]
        rng.shuffle(leftovers)
        picked += leftovers[:seats - len(picked)]
    if not any(m["kind"] == "reasoning" for m in picked):
        rs = [m for m in pool if m["kind"] == "reasoning" and m["model"] not in {p["model"] for p in picked}]
        if rs:
            r = rng.choice(rs)
            idx = next((i for i, m in enumerate(picked) if m["vendor"] == r["vendor"]),
                       len(picked) - 1)
            picked[idx] = r
    note = f"分层抽签（种子 {seed}），{len(picked)} 席，每厂商优先 1 席，厂商不足时补满"
    return picked, note


def run(models, system, user, allow_reasoning=True, max_tokens=4096):
    out = []
    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {ex.submit(call, m["model"], system, user, max_tokens, 300, allow_reasoning): m
                for m in models}
        for f in as_completed(futs):
            m = futs[f]
            try:
                text, sec = f.result()
                ok = True
            except Exception as e:
                text, sec, ok = f"ERROR {str(e)[:200]}", 0, False
            out.append({**m, "text": text, "sec": sec, "ok": ok})
            print(f"  [{'OK ' if ok else 'ERR'}] {m['vendor']:6s}{m['label']:12s} {sec:6.1f}s")
    order = {m["model"]: i for i, m in enumerate(models)}
    out.sort(key=lambda x: order[x["model"]])
    return out


def weigh(answers, use_llm=False, picked=None):
    """默认规则打分（无任何模型参与评判，天然无利益冲突）；
    --judge 时才用池外模型裁判，失败自动退回规则打分。"""
    if use_llm and llm_weigh(answers, picked):
        return f"模型裁判（{JUDGE}，池外）"
    rule_weigh(answers)
    return "规则打分（无模型参与）"


def _bigrams(t):
    s = re.sub(r"[^\u4e00-\u9fa5]", "", t)
    return {s[i:i + 2] for i in range(max(0, len(s) - 1))}


def cluster(items, threshold=0.34):
    """按中文二元组 Jaccard 归堆。difflib 逐字比对在中文问句上过于严格，
    实测「是否明确用于代孕支出」和「有没有说明具体用途」判不出是同一问。"""
    groups = []
    for q, who in items:
        g_q = _bigrams(q)
        hit, best = None, 0.0
        for g in groups:
            g_g = _bigrams(g["q"])
            if not g_q or not g_g:
                continue
            ratio = len(g_q & g_g) / len(g_q | g_g)
            if ratio > best:
                best, hit = ratio, g
        if hit is not None and best >= threshold:
            hit["who"].append(who)
            if len(q) < len(hit["q"]):
                hit["q"] = q
        else:
            groups.append({"q": q, "who": [who]})
    groups.sort(key=lambda g: -len(g["who"]))
    return groups


def write_questions(path, groups, question, facts_path):
    """生成待回答的问题清单。用户填完再进投票。"""
    n_ask = sum(len(g["who"]) for g in groups)
    L = [f"# 陪审团质询清单\n",
         f"主问题：**{question}**\n",
         f"事实文件：`{facts_path}`\n",
         f"\n{len(groups)} 问。陪审团**轮流**提问，后问的看得到前面问过什么，",
         f"且不许重复——所以每一问都是别人没问到的角度，没有凑数题。\n",
         f"\n在每条 `你的回答：` 后面填写。写不出来就写「不知道」——",
         f"不知道本身也是信息，模型会据此调整判断。\n",
         f"\n填完保存，然后跑：`python council.py vote --out <同一个目录>`\n",
         "\n---\n"]
    for i, g in enumerate(groups, 1):
        L.append(f"\n## Q{i} · {g['who'][0]} 问\n\n{g['q']}\n\n你的回答：\n\n")
    open(path, "w", encoding="utf-8").write("\n".join(L))


def read_answers(path):
    """从填好的问题清单里解析用户答案"""
    import re as _re
    txt = open(path, encoding="utf-8").read()
    blocks = _re.split(r"\n## Q\d+[^\n]*\n", txt)[1:]
    out = []
    for b in blocks:
        lines = [x for x in b.split("\n") if x.strip()]
        if not lines:
            continue
        q = lines[0].strip()
        idx = next((i for i, x in enumerate(lines) if x.strip().startswith("你的回答")), None)
        if idx is None:
            continue
        # 用户常把答案直接写在「你的回答：」同一行，也可能换行写，两种都要能读
        same = lines[idx].split("：", 1)[-1].split(":", 1)[-1].strip()
        rest = " ".join(x.strip() for x in lines[idx + 1:] if x.strip())
        a = (same + " " + rest).strip()
        if a:
            out.append((q, a))
    return out


def cmd_clarify(a):
    facts = open(a.facts, encoding="utf-8").read().strip()
    os.makedirs(a.out, exist_ok=True)
    picked, note = draw(POOL, a.seats, a.seed, [x for x in a.names.split(",") if x])
    print(f"\n== 陪审团 ==\n{note}")
    for m in picked:
        print(f"   {m['vendor']} {m['label']}")

    # 排除纯推理模型（会吐思考碎片）与 reasoning 类（实测 R1 单独 187s，把全场拖慢三倍）
    askers = [m for m in picked
              if not m.get("pure_reasoning") and m.get("kind") != "reasoning"]
    print(f"\n== 质询：{len(askers)} 家轮流提问 ==")
    print("   规则：后问的看得到前面问过什么，且不许重复（可见 + 禁重复 = 强制多样性）")
    print("   （推理型模型不参与提问，留到投票时发力。串行进行，请稍候）\n")

    # 串行：每位成员必须看到前面所有问题才能提问，这是本质上的信息依赖
    asked, asked_by, res, dropped = [], [], [], []
    for i, m in enumerate(askers, 1):
        history = "\n".join(f"{j}. {q}" for j, q in enumerate(asked, 1)) \
            if asked else "（你是第一位，还没有人提问）"
        try:
            q = None
            sec = 0
            for attempt in range(2):      # 思考型模型偶发吃光 token，重试一次
                try:
                    text, sec = call(m["model"], "你只负责提问，不负责回答。",
                                     CLARIFY_Q.format(facts=facts, question=a.question,
                                                      history=history, seat=i),
                                     max_tokens=8192, allow_reasoning=False)
                    cand = next((x.strip() for x in text.split("\n")
                                 if x.strip().endswith(("？", "?")) and 8 < len(x.strip()) < 140), None)
                    if not cand:
                        raise RuntimeError("未提取到有效问题")
                    q = cand.lstrip("0123456789.、- ")
                    break
                except Exception:
                    if attempt == 0:
                        print(f"       {m['label']} 未返回有效问题，重试一次…")
                    else:
                        raise

            dup = next((old for old in asked
                        if len(_bigrams(q) & _bigrams(old))
                        / max(1, len(_bigrams(q) | _bigrams(old))) >= 0.34), None)
            if dup:
                dropped.append({"who": f"{m['vendor']} {m['label']}", "q": q, "dup": dup})
                print(f"   [{i}/{len(askers)}] {m['vendor']} {m['label']:11s} "
                      f"重复，作废 —— {q[:38]}")
                res.append({**m, "text": q, "sec": sec, "ok": True, "dropped": True})
                continue
            asked.append(q)
            asked_by.append(f"{m['vendor']} {m['label']}")
            res.append({**m, "text": q, "sec": sec, "ok": True, "dropped": False})
            print(f"   [{i}/{len(askers)}] {m['vendor']} {m['label']:11s} {sec:6.1f}s  {q[:50]}")
        except Exception as e:
            res.append({**m, "text": f"ERROR {str(e)[:120]}", "sec": 0,
                        "ok": False, "dropped": False})
            print(f"   [{i}/{len(askers)}] {m['vendor']} {m['label']:11s} 失败：{str(e)[:44]}")

    groups = [{"q": q, "who": [who]} for q, who in zip(asked, asked_by)]
    qpath = os.path.join(a.out, "questions.md")
    write_questions(qpath, groups, a.question, a.facts)

    json.dump({"stage": "clarified", "draw": note, "picked": picked,
               "facts_path": os.path.abspath(a.facts), "facts": facts,
               "question": a.question, "when": a.when, "clarify": res,
               "groups": groups},
              open(os.path.join(a.out, "state.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print(f"\n== 汇总为 {len(groups)} 问 ==")
    for i, g in enumerate(groups, 1):
        mark = f"[{len(g['who'])}家]" if len(g["who"]) > 1 else "      "
        print(f"  Q{i:<2}{mark} {g['q'][:56]}")
    print(f"\n>>> 已写入 {qpath}")
    print(">>> 打开填写「你的回答」，保存后再跑：")
    print(f"    python council.py vote --out {a.out}")
    print("\n【停在这里等你。填完再继续——不让模型带着缺口投票。】")


def cmd_pack(a):
    """导出提示词包：可粘进 WorkBuddy 内置模型、国外模型或任何 AI，
    拿回答案后交给 AI 并入计票。用于突破本脚本 API 池的厂商限制。"""
    facts = open(a.facts, encoding="utf-8").read().strip()
    os.makedirs(a.out, exist_ok=True)
    txt = f"""# AI Council 提示词包

把下面两段分别粘进任意 AI（WorkBuddy 内置模型、ChatGPT、Claude、Gemini 都行），
拿到回答后整段复制回给 AI，它会并入计票。

## 一、系统提示（粘进"系统提示/角色设定"栏；没有该栏就粘在问题前面）

{SANDBOX.format(when=a.when)}

## 二、问题（粘进输入框）

{facts}

{a.question}

按这个格式答：
①最坏情况 ②概率区间 ③真正的问题 ④第三条路 ⑤一句话结论

---
回答请原样复制回给 AI，并注明是哪个模型。
"""
    path = os.path.join(a.out, "pack.md")
    open(path, "w", encoding="utf-8").write(txt)
    print(f"已生成 {path}")
    print("把它粘进你想用的任何模型，拿回答案交给 AI 即可并入计票。")


def cmd_vote(a):
    st = json.load(open(os.path.join(a.out, "state.json"), encoding="utf-8"))
    qpath = os.path.join(a.out, "questions.md")
    answered = read_answers(qpath) if os.path.exists(qpath) else []

    facts = st["facts"]
    if answered:
        facts += "\n\n【经陪审团提问后补充的事实】\n" + "\n".join(
            f"问：{q}\n答：{ans}" for q, ans in answered)
        print(f"=== 已并入 {len(answered)} 条回答 ===")
    else:
        print("=== 警告：问题清单里没有读到回答，将只用原始事实投票 ===")
        print("    信息缺口未补，结论可信度下降。")

    picked = st["picked"]
    global JUDGE
    if a.judge is not None:
        if a.judge == "auto":
            rs = [m for m in POOL if m["kind"] == "reasoning"]
            JUDGE = rs[0]["model"] if rs else None
        else:
            JUDGE = a.judge
    print(f"\n== 主轮：{len(picked)} 家同时投票（材料完全一致）==")
    answers = run(picked, SANDBOX.format(when=st["when"]),
                  facts + "\n\n" + st["question"] +
                  "\n\n按这个格式答：\n①最坏情况 ②概率区间 ③真正的问题 ④第三条路 ⑤一句话结论")

    print("\n== 证据权重 ==")
    if a.judge is not None and JUDGE:
        print(f"   裁判：{JUDGE}（须在陪审团名单外；若在名单内将自动退回规则打分）")
    mode = weigh(answers, a.judge is not None and JUDGE is not None, picked)
    for x in answers:
        print(f"   {x['vendor']} {x['label']:11s} ×{x['weight']:.2f}  {x['why']}")

    json.dump({"draw": st["draw"], "picked": picked, "clarify": st["clarify"],
               "groups": st["groups"], "answered": answered,
               "answers": answers, "weigh_mode": mode},
              open(os.path.join(a.out, "council.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n完成 -> {a.out}/council.json  （{mode}）")


def main():
    ap = argparse.ArgumentParser(
        description="AI Council：clarify 阶段先让陪审团提问并停下来等用户回答，"
                    "vote 阶段才让所有家拿着完整材料同时投票")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clarify", help="第一阶段：陪审团各提一问，汇总后停下来等你回答")
    c.add_argument("--facts", required=True)
    c.add_argument("--question", required=True)
    c.add_argument("--when", default="事发当时")
    c.add_argument("--seats", type=int, default=8)
    c.add_argument("--seed", type=int, default=None)
    c.add_argument("--names", default="")
    c.add_argument("--out", default="council_out")

    p = sub.add_parser("pack", help="导出提示词包，可粘进 WorkBuddy 内置模型 / 国外模型 / 任何 AI")
    p.add_argument("--facts", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--when", default="事发当时")
    p.add_argument("--out", default="council_out")

    v = sub.add_parser("vote", help="第二阶段：并入你的回答后，所有家同时投票")
    v.add_argument("--out", default="council_out")
    v.add_argument("--judge", nargs="?", const="auto", default=None,
                    help="启用模型裁判（可选=指定裁判模型名，须为硅基流动模型且不在抽签名单内）；"
                         "不指定模型则用池内推理型；默认规则打分")

    a = ap.parse_args()

    if getattr(a, "question", None) and a.question.count("?") + a.question.count("？") > 1:
        print("!! 主问题里不止一个问号。按沙箱规则第 3 条，一次只能问一个问题。")
        if input("仍要继续？[y/N] ").strip().lower() != "y":
            return
    if a.cmd == "clarify":
        cmd_clarify(a)
    elif a.cmd == "pack":
        cmd_pack(a)
    else:
        cmd_vote(a)


if __name__ == "__main__":
    main()
