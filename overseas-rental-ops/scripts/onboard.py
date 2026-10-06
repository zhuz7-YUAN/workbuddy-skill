#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""onboard.py — 初始化访谈：谁住、谁办、用哪个邮箱发、回复收哪、要不要抄给别人。

为什么必须先做这一步（真实教训）：
  技能默认"租客=用户=同一人"，但现实里大量场景是 **父母给子女租、朋友代办**。
  一旦代租，五件事同时变了：
    ① 发信人 ≠ 租客  → 署名、口吻、联系方式都要分
    ② 需要有"发件箱"（家长的邮箱），而不是租客的邮箱
    ③ 需要有"回信收件箱"，且要能和发件箱分开
    ④ 往往要**抄送第三人**（家长想让子女/配偶同时看到进度）
    ⑤ 抄送**不能无脑抄** —— 未核实的房源直接抄过去，就是把假消息喂给家人，
       正是"浪费女儿时间"那个坑。所以抄送必须挂在核验门禁后面。

用法：
  python onboard.py init  --out renter.json      # 生成模板
  python onboard.py check --file renter.json     # 校验必填与常见错误
  python onboard.py show  --file renter.json     # 打印"谁—发—收—抄"一张表

只依赖 Python 标准库。
"""

import argparse
import json
import os
import sys

RELATIONS = ["self", "father", "mother", "parent", "relative", "friend", "agent"]
CC_MODES = ["none", "confirmed_only", "all"]

CC_MODE_MEANING = {
    "none": "不抄送任何人",
    "confirmed_only": "只把【已核实可租】的房源抄给第三人（推荐）",
    "all": "每一条原始房源都抄 —— 会把假消息/僵尸房源一起抄过去，慎用",
}

TEMPLATE = {
    "_note": "由 onboard.py init 生成。扁平字段供 outreach.py 模板替换；下划线开头的段是结构化说明。",
    "_readme": [
        "sender_name：发信人署名（家长代问就写家长名）。留空则用租客名 —— 代租时务必填。",
        "_mail.cc_mode：抄送策略。confirmed_only 最稳，all 会把未核实的房源也抄过去。",
        "_mail.from_account：发件邮箱（代租时用家长邮箱，不要用子女邮箱，免得打扰她/他）。",
    ],

    "name": "",
    "name_local": "",
    "school": "",
    "faculty": "",
    "start": "",
    "end_date": "",
    "budget": "",
    "phone": "",
    "email": "",
    "addr": "",
    "sender_name": "",

    "_role": {
        "relation": "self",
        "tenant_gender": "",
        "requester_name": "",
        "requester_relation_to_tenant": "",
        "note": ""
    },

    "_mail": {
        "smtp_file": "smtp.json",
        "from_account": "",
        "from_display": "",
        "reply_to": "",
        "cc": [],
        "cc_mode": "confirmed_only"
    },

    "_target": {
        "city": "",
        "caps": [],
        "budget_month_total_max": None,
        "term_start": "",
        "term_end": "",
        "gender_ok": [],
        "work_place": "",
        "work_place_label": "",
        "commute_mode": ["transit", "walk", "bike"]
    }
}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_init(a):
    out = a.out or "renter.json"
    if os.path.exists(out) and not a.force:
        print("[跳过] %s 已存在。要覆盖加 --force" % out)
        return 0
    with open(out, "w", encoding="utf-8") as f:
        json.dump(TEMPLATE, f, ensure_ascii=False, indent=2)
    print("[已生成] %s" % out)
    print("下一步：按 references/onboarding.md 的访谈提纲逐项填，然后跑")
    print("        python onboard.py check --file %s" % out)
    return 0


def cmd_check(a):
    d = _load(a.file)
    errs, warns = [], []

    # 1) 租客是谁
    if not (d.get("name") or "").strip():
        errs.append("name 未填 —— 不知道给谁租。合同主体必须明确。")
    if not (d.get("school") or "").strip():
        warns.append("school 未填 —— 学校名是给房东最有力的可信度证明，建议填。")

    role = d.get("_role") or {}
    rel = role.get("relation", "self")
    if rel not in RELATIONS:
        errs.append("_role.relation=%r 不在允许值内：%s" % (rel, "/".join(RELATIONS)))
    if rel != "self":
        if not (d.get("sender_name") or "").strip():
            errs.append("relation=%s（代租）但 sender_name 为空 —— 署名会变成租客本人，"
                        "等于替本人发信。代租必须写清发信人。" % rel)
        if not (role.get("requester_name") or "").strip():
            warns.append("_role.requester_name 未填 —— 建议写明是谁在办这件事。")

    # 2) 邮箱三件套
    mail = d.get("_mail") or {}
    frm = (mail.get("from_account") or "").strip()
    reply = (mail.get("reply_to") or "").strip()
    cc = mail.get("cc") or []
    mode = mail.get("cc_mode", "confirmed_only")

    if not frm:
        errs.append("_mail.from_account 未填 —— 没有发件邮箱，一封问询都发不出去。")
    if "@" not in frm and frm:
        errs.append("_mail.from_account 不像邮箱：%s" % frm)
    if frm and not reply:
        warns.append("_mail.reply_to 为空 —— 将默认用发件邮箱收回复，确认可以吗。")
    for c in cc:
        em = (c.get("email") if isinstance(c, dict) else c) or ""
        if "@" not in em:
            errs.append("抄送地址不是邮箱：%s" % em)

    # 3) 抄送策略（本工具的重点）
    if mode not in CC_MODES:
        errs.append("_mail.cc_mode=%r 不在允许值内：%s" % (mode, "/".join(CC_MODES)))
    if mode == "confirmed_only" and not cc:
        warns.append("cc_mode=confirmed_only 但没有抄送对象 —— 该策略无效果。")
    if mode == "all":
        warns.append("cc_mode=all：每一条原始房源都会抄给第三人，**包括未核实的假消息/"
                     "僵尸房源**。这会把筛选成本转嫁给收件人。除非你确定，建议改成 confirmed_only。")

    tenant_em = (d.get("email") or "").strip()
    if rel != "self" and frm and tenant_em and frm.lower() == tenant_em.lower():
        warns.append("发件邮箱与租客邮箱相同 —— 代租场景下通常应使用委托人的邮箱，"
                     "避免用租客账号发信（打扰本人 + 口吻错位）。")

    # 4) 目标参数
    tgt = d.get("_target") or {}
    if not (tgt.get("city") or "").strip():
        warns.append("_target.city 未填 —— 核验层需要城市与邮编才能分流。")
    if not (tgt.get("caps") or []):
        warns.append("_target.caps 未填 —— 房源板常覆盖整个省，没有邮编会把 25 公里外的房子混进来。")
    if not (tgt.get("work_place") or "").strip():
        warns.append("_target.work_place 未填 —— 没有工作/学习地点，就无法算通勤距离与时间，"
                     "房源排序会失去最关键的一列。强烈建议填（学校主楼/实习公司地址）。")

    print("=== 初始化体检：%s ===" % a.file)
    if errs:
        print("\n[必须修] %d 项" % len(errs))
        for e in errs:
            print("  ✗ " + e)
    if warns:
        print("\n[建议修] %d 项" % len(warns))
        for w in warns:
            print("  ! " + w)
    if not errs and not warns:
        print("\n✓ 无问题。可以进入第 0.5 步（谈判授权表）。")
    return 1 if errs else 0


def cmd_show(a):
    d = _load(a.file)
    role = d.get("_role") or {}
    mail = d.get("_mail") or {}
    tgt = d.get("_target") or {}
    rel = role.get("relation", "self")
    cc = mail.get("cc") or []
    mode = mail.get("cc_mode", "confirmed_only")

    def cc_line():
        if not cc:
            return "（无）"
        parts = []
        for c in cc:
            if isinstance(c, dict):
                nm = c.get("name") or ""
                em = c.get("email") or ""
                sc = c.get("scope") or "all"
                parts.append("%s <%s> [%s]" % (nm or "?", em, sc))
            else:
                parts.append(str(c))
        return "、".join(parts)

    print("=" * 64)
    print("            租赁委托关系（onboard 结果）")
    print("=" * 64)
    print("租客（住的人）      ：%s%s%s" % (
        d.get("name") or "?", " / " + d["name_local"] if d.get("name_local") else "",
        "（%s）" % role.get("tenant_gender") if role.get("tenant_gender") else ""))
    if d.get("school") or d.get("faculty"):
        print("                    %s %s" % (d.get("school") or "", d.get("faculty") or ""))
    print("委托人（办这事的人）：%s%s" % (
        role.get("requester_name") or "本人",
        "（%s）" % role.get("requester_relation_to_tenant") if role.get("requester_relation_to_tenant") else ""))
    print("模式                ：%s" % ("本人自租" if rel == "self" else "代租（relation=%s）" % rel))
    print("")
    print("── 邮件链路 ──")
    print("发件箱              ：%s" % (mail.get("from_account") or "未填"))
    print("发信署名            ：%s" % (d.get("sender_name") or d.get("name") or "未填"))
    print("回信收件（reply-to） ：%s" % (mail.get("reply_to") or mail.get("from_account") or "未填"))
    print("抄送对象            ：%s" % cc_line())
    print("抄送策略            ：%s —— %s" % (mode, CC_MODE_MEANING.get(mode, "?")))
    print("SMTP 配置           ：%s" % (mail.get("smtp_file") or "未填"))
    print("")
    print("── 目标 ──")
    print("城市 / 邮编         ：%s / %s" % (tgt.get("city") or "?", ", ".join(tgt.get("caps") or []) or "?"))
    print("工作/学习地点       ：%s%s" % (
        tgt.get("work_place_label") or tgt.get("work_place") or "未填",
        "（%s）" % tgt.get("work_place") if tgt.get("work_place_label") and tgt.get("work_place") else ""))
    print("通勤方式偏好        ：%s" % ("、".join(tgt.get("commute_mode") or []) or "步行为主"))
    print("月总成本上限        ：%s" % (tgt.get("budget_month_total_max") or "?"))
    print("租期                ：%s → %s" % (tgt.get("term_start") or "?", tgt.get("term_end") or "?"))
    print("可接受性别限制      ：%s" % ("、".join(tgt.get("gender_ok") or []) or "不限"))
    print("=" * 64)
    if mode == "all":
        print("⚠️  抄送策略为 all：未核实的房源会直接进入第三人邮箱。")
        print("    建议先在核验层筛过，再改回 confirmed_only。")
    if rel != "self" and not (d.get("sender_name") or "").strip():
        print("⚠️  代租但未设署名：发出的信会被当成租客本人发的。")
    return 0


def main():
    p = argparse.ArgumentParser(description="初始化访谈：谁住 / 谁办 / 发件箱 / 收件箱 / 抄送")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("init", help="生成初始化模板")
    s1.add_argument("--out", default="renter.json")
    s1.add_argument("--force", action="store_true")
    s1.set_defaults(func=cmd_init)

    s2 = sub.add_parser("check", help="校验必填与常见错误")
    s2.add_argument("--file", required=True)
    s2.set_defaults(func=cmd_check)

    s3 = sub.add_parser("show", help="打印 谁—发—收—抄 一张表")
    s3.add_argument("--file", required=True)
    s3.set_defaults(func=cmd_show)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
