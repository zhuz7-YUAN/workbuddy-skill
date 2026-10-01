#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inbox.py — 收信闭环：把房东/中介的回复读进来、分类、匹配台账、给出建议动作。

这一环补的是整条链上最大的断点：
  前面能把问询发出去（outreach.py），但**回复回来之后仍是人工读、人工判断、人工录**。
  发 20 封就有 20 封回复 —— 这才是量最大的一段。

三条设计纪律（重要，别绕过）：
  1. **分类不靠猜。** 每条判定都必须能说出"命中了哪几个关键词"。
     没命中任何规则的标 needs_review，交给人看，**绝不硬猜**。
  2. **默认只读。** 不加 --writeback 不改台账；不加 --draft 不生成回复文案。
  3. **不自动推送给第三人。** 推送给家人（抄送）仍必须走 outreach.py 的 --confirmed 门禁。

用法：
  python inbox.py --mail smtp.json                      # 读最近的回复并分类
  python inbox.py --mail smtp.json --since 7            # 只看最近 7 天
  python inbox.py --mail smtp.json --db rental/housing.db          # 同时匹配台账
  python inbox.py --mail smtp.json --writeback          # 把判定写回台账
  python inbox.py --mail smtp.json --mandate mandate.json          # 对照授权表给"可否自动回"
  python inbox.py --mail smtp.json --json out.json      # 结构化输出

只依赖 Python 标准库。
"""

import argparse
import email
import imaplib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 分类规则（多语言，全部可解释）────────────────────────────────
# 命中即打标；优先级见 CATEGORY_PRIORITY
RULES = {
    "bounce": [
        "mailer-daemon", "postmaster", "undeliver", "delivery status",
        "delivery failure", "returned mail", "退信", "无法投递", "投递失败",
        "address not found", "recipient rejected",
    ],
    "unavailable": [
        # 已租掉 / 不再可用
        "non è più disponibile", "non piu disponibile", "non e piu disponibile",
        "non è disponibile", "già affittata", "gia affittata", "già affittato",
        "affittata", "affittato", "occupata", "occupato", "non disponibile",
        "purtroppo è stata", "no longer available", "not available anymore",
        "already rented", "already taken", "it's taken", "is taken",
        "已租", "租出去了", "已经租出去", "已出租", "没有了", "已订",
    ],
    "declined": [
        # 明确拒绝（含"只租 12 个月"这类与我们硬约束冲突的）
        "solo 12 mesi", "solo dodici mesi", "minimo 12 mesi", "minimo dodici",
        "non accettiamo", "non è possibile", "non e possibile", "purtroppo no",
        "mi dispiace", "minimum 12", "12-month minimum", "only 12 months",
        "we only", "not possible", "cannot", "can not", "we don't accept",
        "sorry, no", "unfortunately", "不行", "不接受", "只能租", "抱歉", "不行哦",
    ],
    "negotiating": [
        "possiamo discutere", "possiamo parlare", "se vuole possiamo",
        "dipende", "valutiamo", "proposta", "trattabile", "si può trattare",
        "let's discuss", "we can discuss", "negotiable", "depends on",
        "可以商量", "商量", "可谈", "看情况", "有空间",
    ],
    "available": [
        "ancora disponibile", "ancora libera", "ancora libero", "è libera",
        "e libera", "è libero", "si può vedere", "possiamo fissare",
        "sono disponibile", "venite a vedere", "still available", "it is available",
        "yes, available", "available from", "you can see it", "viewing",
        "还在", "可以看", "可看房", "有空", "可以租", "欢迎看房",
    ],
}
# 优先级：越靠前越强。退信 > 已租 > 明确拒绝 > 在谈 > 可租
CATEGORY_PRIORITY = ["bounce", "unavailable", "declined", "negotiating", "available"]

CATEGORY_LABEL = {
    "bounce": "退信/投递失败",
    "unavailable": "已租掉/不再可用",
    "declined": "明确拒绝",
    "negotiating": "在谈（有弹性）",
    "available": "答复可租",
    "needs_review": "需人工判读",
}

# 关键要素抽取（用于生成简报，不做判断）
# price 的顺序很重要：带"租金"词前缀的模式必须排在裸数字模式之前，
# 否则 "caparra 300 euro ... affitto 320 euro" 会把押金当成租金。
FIELDS = {
    "deposit": [r"caparra[^\d]{0,20}(\d[\d\.,]*)", r"cauzione[^\d]{0,20}(\d[\d\.,]*)",
                r"deposit[^\d]{0,20}(\d[\d\.,]*)", r"kaution[^\d]{0,20}(\d[\d\.,]*)",
                r"押金[^\d]{0,10}(\d[\d\.,]*)"],
    "price": [r"affitto[^\d]{0,20}(\d[\d\.,]*)", r"canone[^\d]{0,20}(\d[\d\.,]*)",
              r"miete[^\d]{0,20}(\d[\d\.,]*)", r"rent[^\d]{0,20}(\d[\d\.,]*)",
              r"prezzo[^\d]{0,20}(\d[\d\.,]*)", r"租金[^\d]{0,10}(\d[\d\.,]*)",
              r"(\d{3,4})\s*(?:€|eur|euro)", r"€\s*(\d{3,4})"],
    "months": [r"(\d{1,2})\s*mesi", r"(\d{1,2})\s*months", r"(\d{1,2})\s*个月",
               r"(\d{1,2})\s*monat\w*"],
}

# 否定语境：出现在数值前，说明"没有押金"，不是金额
NEG_CTX = ["nessuna", "nessun ", "senza", "no deposit", "without", "免", "无押金", "不要押金"]


def _num(s):
    """'1.200' / '320,00' / '320' → 只留数字，便于比较。"""
    return re.sub(r"[^\d]", "", s or "")


def _clean_num(v):
    """去掉尾随标点，并校验像个真实金额（2–9 位数字）。不合理返回 None。"""
    v = (v or "").rstrip(".,")
    d = _num(v)
    if not d or not (2 <= len(d) <= 9):
        return None
    return v


def _decode(s):
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def extract_body(msg):
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                try:
                    return p.get_payload(decode=True).decode(
                        p.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    pass
        for p in msg.walk():
            if p.get_content_type() == "text/html":
                try:
                    return p.get_payload(decode=True).decode(
                        p.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    pass
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="ignore")
    except Exception:
        return ""


def classify(subject, frm, body):
    """返回 (category, hits)。hits = 命中的关键词列表（可解释）。"""
    blob = ("%s %s %s" % (subject, frm, body)).lower()
    per = {}
    for cat, kws in RULES.items():
        hits = [k for k in kws if k in blob]
        if hits:
            per[cat] = hits
    if not per:
        return "needs_review", []
    for cat in CATEGORY_PRIORITY:
        if cat in per:
            return cat, per[cat][:4]
    return "needs_review", []


def grab_fields(text):
    out = {}
    t = text.replace("\u00a0", " ")
    # 抽押金：排除"没有押金"这类否定语境与不合理的数字
    for p in FIELDS["deposit"]:
        for m in re.finditer(p, t, re.I):
            v = _clean_num(m.group(1))
            if not v:
                continue
            ctx = t[max(0, m.start() - 30):m.start()].lower()
            if any(n in ctx for n in NEG_CTX):
                continue
            out["deposit"] = v
            break
        if "deposit" in out:
            break
    dep = _num(out.get("deposit", ""))
    # 抽租金：按模式优先级找，跳过与押金相同的数值（避免把 caparra 当 canone）
    for p in FIELDS["price"]:
        got = ""
        for m in re.finditer(p, t, re.I):
            v = _clean_num(m.group(1))
            if not v:
                continue
            if dep and _num(v) == dep:
                continue
            got = v
            break
        if got:
            out["price"] = got
            break
    # 租期
    for p in FIELDS["months"]:
        m = re.search(p, t, re.I)
        if m:
            out["months"] = m.group(1)
            break
    return out


def sender_email(frm):
    m = re.search(r"<([^>]+)>", frm or "")
    return (m.group(1) if m else (frm or "")).strip().lower()


def db_lookup(db, addr):
    """按发件邮箱在台账里找对应的问询记录。返回 list of dict。"""
    if not db or not os.path.exists(db):
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT c.id AS contact_id, c.listing_id, c.target, c.sent_at, c.outcome, "
            "       l.title, l.city, l.url, l.total_month "
            "FROM contacts c LEFT JOIN listings l ON l.id = c.listing_id "
            "WHERE lower(c.target) = ? ORDER BY c.sent_at DESC", (addr,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _fmt(v):
    """460.0 → '460'，避免简报里出现浮点尾巴。"""
    try:
        f = float(v)
        return ("%g" % f)
    except (TypeError, ValueError):
        return str(v)


def mandate_verdict(mandate, fields, category):
    """对照授权表，给出"可否自动回 / 需人工决策"。返回 (verdict, reason)

    注意：unavailable / declined / bounce 是**对方已给出结论**的情形，
    此时租期与价格分析没有意义，不要把它拼进理由里 —— 否则会出现
    "明确拒绝"却附上"租期落在授权范围内"这种自相矛盾的表述。
    """
    if not mandate:
        return "", ""
    A = mandate.get("A_hard", {})
    B = mandate.get("B_flexible", {})

    if category == "bounce":
        return "需人工处理", "投递失败，换渠道或核对地址"
    if category == "unavailable":
        return "自动可处理", "已租掉/不再可用 → 标 excluded，不再投入，无需打扰第三人"
    if category == "declined":
        return "自动可处理", "对方已明确拒绝 → 标 excluded。若理由是租期，可记下备选（subentro）"

    reasons = []
    hard_break = False

    # 价格
    pr = fields.get("price")
    p = None
    if pr:
        try:
            p = float(_num(pr) or "nan")
        except ValueError:
            p = None
    if p is not None and p == p:
        cap = A.get("budget_month_total_max")
        tgt = B.get("price_target")
        if cap is not None and p > float(cap):
            hard_break = True
            reasons.append("报价 %s > 预算上限 %s" % (_fmt(p), _fmt(cap)))
        elif tgt is not None and p > float(tgt):
            reasons.append("报价 %s 高于心理价位 %s（第 5 档，仍在预算内）" % (_fmt(p), _fmt(tgt)))
        else:
            reasons.append("报价 %s 未超心理价位" % _fmt(p))

    # 租期：房东要求的租期 vs 我方授权能签的上限
    mo = fields.get("months")
    if mo and str(mo).isdigit():
        n = int(mo)
        tmax = B.get("term_max_months_if_landlord_insists")
        if tmax is not None and n > int(tmax):
            hard_break = True
            reasons.append("房东要求 %d 个月 > 可让上限 %s 个月" % (n, tmax))
        else:
            reasons.append("房东要求 %d 个月，在可接受范围内" % n)

    if hard_break:
        return "需人工决策", "；".join(reasons) + " —— 越出授权边界，必须由委托人决定"
    if category == "negotiating":
        tail = ("；" + "；".join(reasons)) if reasons else ""
        return "自动可处理（授权范围内）", "按让步梯度回一轮" + tail
    if category == "available":
        tail = ("；" + "；".join(reasons)) if reasons else ""
        return "自动可处理（授权范围内）", "约看房或索要合同要点" + tail
    return "需人工判读", "分类未命中规则" + (("；" + "；".join(reasons)) if reasons else "")


def fetch(mail_cfg, since_days, limit, folder="INBOX"):
    host = mail_cfg.get("imap_host", "imap.qq.com")
    port = int(mail_cfg.get("imap_port", 993))
    user = (mail_cfg.get("sender") or "").strip()
    code = (mail_cfg.get("auth_code") or "").strip()
    if not user or not code:
        print("!! 邮箱配置缺少 sender / auth_code")
        sys.exit(2)
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, code)
    M.select(folder)
    if since_days:
        d = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = M.search(None, "(SINCE %s)" % d)
    else:
        typ, data = M.search(None, "ALL")
    ids = (data[0].split() if data and data[0] else [])
    out = []
    for i in ids[-limit:]:
        typ, d = M.fetch(i, "(RFC822)")
        if not d or not d[0]:
            continue
        msg = email.message_from_bytes(d[0][1])
        frm = _decode(msg.get("From"))
        sub = _decode(msg.get("Subject"))
        body = extract_body(msg)
        out.append({"from": frm, "addr": sender_email(frm), "subject": sub,
                    "date": msg.get("Date", ""), "body": body})
    M.logout()
    return out


def main():
    p = argparse.ArgumentParser(description="收信闭环：读取→分类→匹配台账→建议")
    p.add_argument("--mail", required=True, help="邮箱配置 JSON（含 sender / auth_code）")
    p.add_argument("--db", default="", help="台账路径（给了才匹配房源）")
    p.add_argument("--mandate", default="", help="谈判授权表（给了才判断可否自动回）")
    p.add_argument("--since", type=int, default=14, help="只看最近 N 天（0=不限）")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--writeback", action="store_true", help="把判定写回台账")
    p.add_argument("--json", dest="json_out", default="")
    a = p.parse_args()

    mail_cfg = json.load(open(a.mail, encoding="utf-8"))
    mandate = json.load(open(a.mandate, encoding="utf-8")) if a.mandate else None
    if not a.db:
        a.db = os.environ.get("RENTAL_DB") or os.path.join(
            os.path.expanduser("~"), ".overseas-rental", "housing.db")
        if not os.path.exists(a.db):
            a.db = ""

    print("读取邮箱：%s（最近 %s 天）" % (mail_cfg.get("sender"), a.since or "不限"))
    mails = fetch(mail_cfg, a.since, a.limit, a.folder)
    print("共取回 %d 封。\n" % len(mails))

    rows = []
    for m in mails:
        cat, hits = classify(m["subject"], m["from"], m["body"])
        fields = grab_fields(m["subject"] + "\n" + m["body"])
        matched = db_lookup(a.db, m["addr"]) if a.db else []
        verdict, reason = mandate_verdict(mandate, fields, cat)
        rows.append({"mail": m, "cat": cat, "hits": hits, "fields": fields,
                     "matched": matched, "verdict": verdict, "reason": reason})

    # 分桶输出
    buckets = [
        ("需你决策 / 需人工处理", lambda r: r["verdict"].startswith("需")),
        ("可自动处理（授权范围内）", lambda r: r["verdict"].startswith("自动")),
        ("未匹配授权表（仅分类）", lambda r: not r["verdict"]),
    ]
    shown = set()
    for title, pred in buckets:
        sel = [r for r in rows if pred(r) and id(r) not in shown]
        if not sel:
            continue
        print("=" * 72)
        print("【%s】%d 封" % (title, len(sel)))
        print("=" * 72)
        for r in sel:
            shown.add(id(r))
            m = r["mail"]
            print("\n· %s" % (m["subject"][:78] or "(无主题)"))
            print("  %s  ← %s" % (m["date"][:31], m["from"][:70]))
            print("  判定：%s" % CATEGORY_LABEL[r["cat"]])
            if r["hits"]:
                print("  依据：命中关键词 %s" % "、".join(r["hits"]))
            if r["fields"]:
                print("  要素：%s" % "，".join("%s=%s" % (k, v) for k, v in r["fields"].items()))
            if r["matched"]:
                for mt in r["matched"][:2]:
                    print("  台账：#%s 房源 %s（%s）月总成本 %s 原状态 %s" % (
                        mt["contact_id"], (mt["title"] or "")[:34], mt["city"] or "-",
                        mt["total_month"], mt["outcome"]))
            else:
                print("  台账：未匹配到问询记录（陌生来信，需人工确认）")
            if r["verdict"]:
                print("  建议：%s —— %s" % (r["verdict"], r["reason"]))
        print()

    # 汇总
    print("-" * 72)
    from collections import Counter
    c = Counter(r["cat"] for r in rows)
    print("分类汇总：" + "、".join("%s=%d" % (CATEGORY_LABEL[k], v) for k, v in c.most_common()))
    auto = sum(1 for r in rows if r["verdict"].startswith("自动"))
    need = sum(1 for r in rows if r["verdict"].startswith("需"))
    if mandate:
        print("授权表判定：可自动处理 %d 封 ／ 需你决策 %d 封" % (auto, need))
    print("提醒：分类未命中规则的会标「需人工判读」——本工具不猜。")
    print("      推送给家人（抄送）仍走 outreach.py 的 --confirmed 门禁，此处不做。")

    if a.json_out:
        payload = [{"subject": r["mail"]["subject"], "from": r["mail"]["from"],
                    "addr": r["mail"]["addr"], "date": r["mail"]["date"],
                    "category": r["cat"], "hits": r["hits"], "fields": r["fields"],
                    "matched_contact_ids": [m["contact_id"] for m in r["matched"]],
                    "verdict": r["verdict"], "reason": r["reason"]} for r in rows]
        json.dump(payload, open(a.json_out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("\n[已写出] %s" % a.json_out)

    if a.writeback:
        if not a.db:
            print("\n!! --writeback 需要台账（--db 或先 init）")
            sys.exit(1)
        con = sqlite3.connect(a.db)
        n = 0
        for r in rows:
            if not r["matched"]:
                continue
            outcome = {"available": "available", "negotiating": "negotiating",
                       "unavailable": "unavailable", "declined": "declined",
                       "bounce": "no_response"}.get(r["cat"], "")
            if not outcome:
                continue
            for mt in r["matched"]:
                con.execute("UPDATE contacts SET reply_at=?, outcome=?, summary=?, "
                            "next_action=? WHERE id=?",
                            (datetime.now().strftime("%Y-%m-%d %H:%M"), outcome,
                             ("[%s] %s" % (CATEGORY_LABEL[r["cat"]], r["reason"]))[:300],
                             r["verdict"], mt["contact_id"]))
                n += 1
        con.commit(); con.close()
        print("\n[已写回台账] 更新 %d 条问询记录" % n)
    else:
        print("\n（未改台账。要写回加 --writeback）")


if __name__ == "__main__":
    main()
