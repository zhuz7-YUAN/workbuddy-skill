#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mandate.py — 谈判授权表：把"哪些能松、哪些不能松"一次问清、落表、校验、出简报。

为什么要它：重复谈判的根因不是话术不够，是每次都要重新想一遍"我能退到哪"。
落成授权表后，每一轮谈判都是查表执行。

用法：
    python mandate.py init  --out mandate.json      # 生成空白模板（AI 访谈后逐项填）
    python mandate.py check --file mandate.json     # 校验漏填与自相矛盾
    python mandate.py brief --file mandate.json     # 输出授权简报 + 五档让步梯度

只依赖 Python 标准库。
"""

import argparse
import json
import os
import sys

TEMPLATE = {
    "_note": "谈判授权表。A=硬约束(越线即放弃) B=可让(按梯度让) C=筹码(拿去换条件) D=红线(AI 不得放宽)。",
    "who": {
        "name": "",
        "city": "",
        "term_start": "",
        "term_end": "",
    },
    "A_hard": {
        "budget_month_total_max": None,
        "commute_max_min": None,
        "term_min_months": None,
        "term_max_end_date": "",
        "contract_registered_required": True,
        "restrictions": []
    },
    "B_flexible": {
        "price_target": None,
        "term_max_months_if_landlord_insists": None,
        "can_accept_self_find_substitute": True,
        "start_earliest": "",
        "commute_can_extend_min": 0,
        "room_type_fallbacks": [],
        "bills_included_acceptable": True
    },
    "C_chips": {
        "sign_immediately": True,
        "prepay_months_available": 0,
        "find_takeover_myself": True,
        "stay_whole_period_no_break": True,
        "student_docs_available": []
    },
    "D_red_lines": {
        "no_payment_before_viewing": True,
        "no_unregistered_private_stay": True,
        "no_payment_to_non_contract_party": True,
        "no_cash_without_receipt": True,
        "deposit_max_months": 3,
        "no_promise_impossible_term": True
    }
}

CONCESSION_LADDER = [
    "第 1 档（最轻）：承认对方条件合理 + 表达强烈意愿 + 强调「我能立刻签、立刻付」",
    "第 2 档：可让部分价格/位置弹性  ↔ 换对方接受租期",
    "第 3 档：一次性预付 2 个月      ↔ 换掉担保要求",
    "第 4 档：承诺自己找接手的（subentro） ↔ 换掉「12 个月起租」",
    "第 5 档（最重）：接受略超心理价位（仍在预算上限内） ↔ 换立刻成交",
    "—————————————————————————————————",
    "⛔ 到此为止。再往上就是 A 线 / D 线，直接放弃，不要为了成交破线。",
]


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_init(args):
    out = args.out or "mandate.json"
    if os.path.exists(out) and not args.force:
        print("[跳过] %s 已存在。要覆盖请加 --force" % out)
        return 0
    with open(out, "w", encoding="utf-8") as f:
        json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
    print("[已生成] %s" % out)
    print("下一步：AI 按 references/negotiation_mandate.md 的四条线（A/B/C/D）访谈你，逐项填进去，")
    print("        然后跑  python mandate.py check --file %s" % out)
    return 0


def _is_blank(v):
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, list) and len(v) == 0:
        return True
    return False


def cmd_check(args):
    m = _load(args.file)
    problems = []
    warnings = []

    A = m.get("A_hard", {})
    B = m.get("B_flexible", {})
    C = m.get("C_chips", {})
    D = m.get("D_red_lines", {})

    # 1) 漏填（A 线全必填，因为它是"越线即放弃"）
    for k in ("budget_month_total_max", "commute_max_min", "term_min_months", "term_max_end_date"):
        if _is_blank(A.get(k)):
            problems.append("A_hard.%s 未填（硬约束不能空）" % k)
    if _is_blank(B.get("price_target")):
        warnings.append("B_flexible.price_target 未填 → 谈判没有「心理价位」锚点，容易一路让到底")

    # 2) 自相矛盾
    bmax = A.get("budget_month_total_max")
    tgt = B.get("price_target")
    if isinstance(bmax, (int, float)) and isinstance(tgt, (int, float)):
        if tgt > bmax:
            problems.append("心理价位(%s) > 预算绝对上限(%s)：锚点高于红线，谈判会直接破线" % (tgt, bmax))

    tmin = A.get("term_min_months")
    tmax = B.get("term_max_months_if_landlord_insists")
    if isinstance(tmin, (int, float)) and isinstance(tmax, (int, float)):
        if tmax < tmin:
            problems.append("房东坚持时的最长租期(%s) < 最短可接受租期(%s)：无解" % (tmax, tmin))

    # 3) 红线与 B 线打架
    dep = D.get("deposit_max_months")
    if isinstance(dep, (int, float)):
        if dep > 4:
            warnings.append("D_red_lines.deposit_max_months=%s 偏大，欧洲常见 1–3 个月" % dep)

    # 4) 筹码全空 → 没法谈
    chips_open = [k for k, v in C.items() if v not in (False, 0, None, "", [])]
    if not chips_open:
        problems.append("C_chips 全空：没有任何筹码，谈不动。至少留一项（立刻签 / 预付 / 自己找接手）")

    # 5) 红线被关掉
    for k in ("no_payment_before_viewing", "no_unregistered_private_stay"):
        if D.get(k) is False:
            problems.append("D_red_lines.%s 被设为 false —— 这是不可放宽的红线" % k)

    print("=== 授权表校验：%s ===" % args.file)
    if problems:
        print("\n[必须修] %d 项" % len(problems))
        for p in problems:
            print("  ✗ " + p)
    if warnings:
        print("\n[建议修] %d 项" % len(warnings))
        for w in warnings:
            print("  ! " + w)
    if not problems and not warnings:
        print("\n✓ 无问题。授权表可用。")
    return 1 if problems else 0


def cmd_brief(args):
    m = _load(args.file)
    who = m.get("who", {})
    A = m.get("A_hard", {})
    B = m.get("B_flexible", {})
    C = m.get("C_chips", {})
    D = m.get("D_red_lines", {})

    L = []
    L.append("=" * 58)
    L.append("           谈判授权简报（AI 不得越界）")
    L.append("=" * 58)
    L.append("租客：%s    城市：%s" % (who.get("name") or "?", who.get("city") or "?"))
    L.append("租期：%s → %s" % (who.get("term_start") or "?", who.get("term_end") or "?"))
    L.append("")
    L.append("── A 硬约束（越线即放弃，不谈判）──")
    L.append("  预算月总成本上限：%s" % (A.get("budget_month_total_max") or "未填"))
    L.append("  通勤上限：%s 分钟" % (A.get("commute_max_min") or "未填"))
    L.append("  最短可接受租期：%s 个月" % (A.get("term_min_months") or "未填"))
    L.append("  最晚住到：%s" % (A.get("term_max_end_date") or "未填"))
    L.append("  必须正规注册合同：%s" % ("是" if A.get("contract_registered_required") else "否"))
    if A.get("restrictions"):
        L.append("  房源类型限制：%s" % "、".join(map(str, A["restrictions"])))
    L.append("")
    L.append("── B 可让（按梯度让，不是一开始就给）──")
    L.append("  心理价位：%s" % (B.get("price_target") or "未填"))
    L.append("  房东坚持时长租时最多接受到：%s 个月" % (B.get("term_max_months_if_landlord_insists") or "未填"))
    L.append("  可接受自己找接手人(subentro)：%s" % ("是" if B.get("can_accept_self_find_substitute") else "否"))
    L.append("  可提前起租日：%s" % (B.get("start_earliest") or "未填"))
    L.append("  通勤可放宽：%s 分钟（换更便宜）" % B.get("commute_can_extend_min", 0))
    if B.get("room_type_fallbacks"):
        L.append("  可退到房型：%s" % "、".join(map(str, B["room_type_fallbacks"])))
    L.append("")
    L.append("── C 筹码（拿去换条件，主动出牌）──")
    L.append("  可立刻签约：%s" % ("是" if C.get("sign_immediately") else "否"))
    L.append("  可预付月数：%s" % C.get("prepay_months_available", 0))
    L.append("  我自己找接手的：%s" % ("是" if C.get("find_takeover_myself") else "否"))
    L.append("  全程不中断：%s" % ("是" if C.get("stay_whole_period_no_break") else "否"))
    if C.get("student_docs_available"):
        L.append("  可出示学校材料：%s" % "、".join(map(str, C["student_docs_available"])))
    L.append("")
    L.append("── D 红线（遇到就退出，AI 不得代答）──")
    L.append("  不看房不付款：%s" % ("是" if D.get("no_payment_before_viewing") else "!! 已关"))
    L.append("  不签未注册私约：%s" % ("是" if D.get("no_unregistered_private_stay") else "!! 已关"))
    L.append("  只付合同主体：%s" % ("是" if D.get("no_payment_to_non_contract_party") else "!! 已关"))
    L.append("  现金必留收据：%s" % ("是" if D.get("no_cash_without_receipt") else "!! 已关"))
    L.append("  押金上限：%s 个月" % D.get("deposit_max_months"))
    L.append("")
    L.append("── 让步梯度（从第 1 档开始，一档一档让，不跳档）──")
    for line in CONCESSION_LADDER:
        L.append("  " + line)
    L.append("")
    L.append("纪律：发给房东的每一句话都必须落在本简报范围内。超出范围先回来问租客。")
    L.append("=" * 58)
    text = "\n".join(L)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("\n[已写入] %s" % args.out)
    return 0


def main():
    p = argparse.ArgumentParser(description="谈判授权表：init / check / brief")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("init", help="生成空白授权表模板")
    p1.add_argument("--out", default="mandate.json")
    p1.add_argument("--force", action="store_true")
    p1.set_defaults(func=cmd_init)

    p2 = sub.add_parser("check", help="校验漏填与自相矛盾")
    p2.add_argument("--file", required=True)
    p2.set_defaults(func=cmd_check)

    p3 = sub.add_parser("brief", help="输出授权简报 + 让步梯度")
    p3.add_argument("--file", required=True)
    p3.add_argument("--out", default="")
    p3.set_defaults(func=cmd_brief)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
