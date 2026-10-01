#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contract_check.py — 租赁合同风险扫描：把合同里的关键条款与红旗挖出来。

为什么需要它：门禁清单说"合同 8 项逐条核对"，但**给一个语言不熟的学生一份
意大利语合同让她自己找**"退租通知期""押金退还条件"——等于没做。
而这是整条链上风险最高的一步：签错会影响居留、押金、退租。

输入：合同的纯文本（txt）。PDF 先用阅读器/AI 转成文本再喂进来。
输出：逐条 —— 状态 + 原文摘录 + 为什么重要 + 该怎么办。

三条纪律：
  1. **找不到就明说找不到**（标 ✖ 缺失），并告诉你"这条必须去问房东"。
     绝不因为正则没匹配上就假装"没问题"。
  2. **每条判定都附原文摘录**，便于人工复核，不让你盲信结论。
  3. **只提示，不代替律师。** 本工具是筛子，不是法律意见。

用法：
  python contract_check.py --file contratto.txt
  python contract_check.py --file contratto.txt --lang it
  python contract_check.py --file contratto.txt --json out.json

只依赖 Python 标准库。
"""

import argparse
import json
import re
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 每条检查：id / 标题 / 正则列表 / 重要度 / 为什么 / 该怎么做
# sev: high=不看清楚就别签 / mid=要问清楚 / low=确认一下
CHECKS = [
    {
        "id": "disdetta", "sev": "high",
        "title": "退租通知期（preavviso / disdetta）",
        "pat": [r"preavvis\w*[^.\n]{0,90}", r"disdett\w*[^.\n]{0,90}"],
        "why": "错过通知期会被多扣一个月甚至更久，是**最常被忽略、也最贵**的一条。",
        "todo": "抄下具体天数/月数与通知方式（挂号信 raccomandata / PEC），立刻设日历提醒。",
    },
    {
        "id": "deposito", "sev": "high",
        "title": "押金金额与退还条件（deposito cauzionale / caparra）",
        "pat": [r"(?:deposito\s+cauzionale|caparra|cauzione)[^.\n]{0,110}"],
        "why": "押金是你最大一笔风险敞口；退还条件不写清，退租时几乎必吵。",
        "todo": "核对：金额（几欧？几个月？）、退还时间（退租后几天）、扣减条件。"
                "**押金超过 3 个月要有充分理由**，否则谈。",
    },
    {
        "id": "tipo_contratto", "sev": "high",
        "title": "合同类型（transitorio / 4+4 / concordato）",
        "pat": [r"contratto\s+(?:transitori\w*|a\s+canone\s+concordat\w*|libero)",
                r"locazione\s+transitori\w*", r"4\s*\+\s*4", r"3\s*\+\s*2"],
        "why": "只有 `transitorio`（临时性质）才名正言顺地短租。写成长租类型却只住 4 个月，"
               "合同与事实不符，退租时吃亏。",
        "todo": "确认类型；短租必须争取 transitorio。若房东写别的类型，问清为什么。",
    },
    {
        "id": "registrazione", "sev": "high",
        "title": "合同是否注册（registrazione / registrato）",
        "pat": [r"registrat\w*[^.\n]{0,90}", r"registrazione[^.\n]{0,90}", r"imposta\s+di\s+registro[^.\n]{0,70}"],
        "why": "**未注册的合同办不了居留，押金也没有法律凭据。** 注册费通常由房东承担。",
        "todo": "要求房东提供税务局注册回执（Agenzia delle Entrate）。合同上必须有双方税号。",
    },
    {
        "id": "durata", "sev": "high",
        "title": "租期起止（durata / decorrenza / scadenza）",
        "pat": [r"durata[^.\n]{0,100}", r"decorren\w*[^.\n]{0,90}", r"scadenz\w*[^.\n]{0,90}"],
        "why": "合同租期必须覆盖你的实际居住区间，否则中间会出现「无合同期」。",
        "todo": "核对起止日期与你实际住的时间一致；多出来的月份问清能否 subentro 接手。",
    },
    {
        "id": "canone", "sev": "mid",
        "title": "租金与调整机制（canone / aggiornamento ISTAT）",
        "pat": [r"canone[^.\n]{0,90}", r"aggiornament\w*[^.\n]{0,80}", r"ISTAT[^.\n]{0,70}"],
        "why": "有些合同含「每年按 ISTAT 涨租」条款，长期会累积。",
        "todo": "确认是否含涨租条款；短租应争取不涨。",
    },
    {
        "id": "spese", "sev": "mid",
        "title": "杂费与分摊（spese / oneri accessori）",
        "pat": [r"spese\s+(?:accessorie|condominiali|incluse|escluse)[^.\n]{0,90}",
                r"oneri\s+accessori[^.\n]{0,80}"],
        "why": "意大利学生房杂费常 €80–150/月，只看租金会低估 30–45%。",
        "todo": "写清：杂费多少、含哪些（水/电/气/网/暖气/物业）、按月付还是按实际结算。",
    },
    {
        "id": "subentro", "sev": "mid",
        "title": "转租/接手（subaffitto / subentro / cessione）",
        "pat": [r"subaffitt\w*[^.\n]{0,80}", r"subentr\w*[^.\n]{0,80}", r"cession\w*\s+di\s+contratto[^.\n]{0,60}"],
        "why": "允许 subentro 是你谈短租的主武器：房东不怕空房才肯松口。",
        "todo": "争取写入「允许提前找接手人」；若明确禁止（vietato），退租时会更被动。",
    },
    {
        "id": "manutenzione", "sev": "mid",
        "title": "维修责任（manutenzione ordinaria / straordinaria）",
        "pat": [r"manutenzion\w*[^.\n]{0,90}", r"riparazion\w*[^.\n]{0,80}"],
        "why": "把「大修」推给租客的条款会带来意外支出。",
        "todo": "常规小修归你、结构性大修归房东；写清谁负责。",
    },
    {
        "id": "penale", "sev": "high",
        "title": "违约金与解约罚则（penale / clausola risolutiva）",
        "pat": [r"penal\w*[^.\n]{0,90}", r"clausola\s+risolutiv\w*[^.\n]{0,80}", r"risoluzione[^.\n]{0,70}"],
        "why": "高额违约金会让你「想走也走不了」。",
        "todo": "看清触发条件与金额；与押金上限一起评估总风险。",
    },
    {
        "id": "cf", "sev": "mid",
        "title": "双方税号（codice fiscale）",
        "pat": [r"codice\s+fiscale[^.\n]{0,80}", r"\bC\.?F\.?\s*[:.]?\s*[A-Z0-9]{10,16}"],
        "why": "合同上没有双方税号 = 无法正常注册 = 影响居留。",
        "todo": "确认合同里有两个人的税号。你没有的话必须先办。",
    },
    {
        "id": "immobile", "sev": "mid",
        "title": "房屋标识与产权人（indirizzo / catastale / proprietario）",
        "pat": [r"catastal\w*[^.\n]{0,70}", r"foglio\s+\d+", r"particella\s+\d+",
                r"proprietari\w*[^.\n]{0,80}"],
        "why": "产权人不明确时，押金可能付给了无权出租的人（假房东骗局）。",
        "todo": "核对合同上的房东姓名/税号与身份证件一致；要求看产权或委托书。",
    },
    {
        "id": "pagamento", "sev": "high",
        "title": "付款方式与收据（modalità di pagamento / ricevuta）",
        "pat": [r"pagament\w*[^.\n]{0,90}", r"bonific\w*[^.\n]{0,70}", r"ricevut\w*[^.\n]{0,70}"],
        "why": "只收现金不开收据 = 退押金无凭据。",
        "todo": "优先银行转账（有流水）；现金必须当场出签字收据。",
    },
]

# 红旗词：出现即高危，必须解释
RED_FLAGS = [
    (r"non\s+rimborsabil\w*", "押金/款项不退还", "high"),
    (r"senza\s+registrazion\w*", "合同不注册", "high"),
    (r"vietat\w*\s+(?:il\s+)?subaffitt\w*", "明确禁止转租", "mid"),
    (r"vietat\w*\s+(?:il\s+)?subentr\w*", "明确禁止接手（subentro）", "mid"),
    (r"solo\s+(?:in\s+)?contanti", "只收现金", "high"),
    (r"in\s+contanti", "现金支付（无凭证风险）", "mid"),
    (r"caparra\s+confirmatoria", "定金性质（caparra confirmatoria）：违约可能被没收", "mid"),
    (r"deposito\s+cauzionale[^.\n]{0,25}(?:pari\s+a\s+)?(?:tre|3)\s+mensilit",
     "押金达 3 个月，偏高", "mid"),
    (r"cauzione[^.\n]{0,25}(?:tre|3)\s+mensilit", "押金达 3 个月，偏高", "mid"),
    (r"preavvis\w*[^.\n]{0,25}(?:sei|6)\s+mesi",
     "通知期长（6 个月）——对短租极不利", "high"),
    (r"rinuncia\s+al\s+preavviso", "放弃通知期（对你不利）", "high"),
    (r"imposta\s+di\s+registro[^.\n]{0,45}carico\s+del\s+conduttore",
     "注册税推给租客（通常应由房东承担）", "high"),
    (r"registr\w*[^.\n]{0,50}a\s+cura\s+del\s+conduttore",
     "注册义务推给租客（通常由房东办理）", "high"),
    (r"spese\s+straordinarie[^.\n]{0,45}(?:carico|a\s+cura)\s+del\s+conduttore",
     "结构性大修推给租客（异常）", "high"),
]


SEV_LABEL = {"high": "🔴 高", "mid": "🟡 中", "low": "⚪ 低"}


def find_first(text, pats):
    for p in pats:
        m = re.search(p, text, re.I)
        if m:
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            return s[:150]
    return None


def scan(text):
    results = []
    for c in CHECKS:
        excerpt = find_first(text, c["pat"])
        results.append({"id": c["id"], "title": c["title"], "sev": c["sev"],
                        "found": bool(excerpt), "excerpt": excerpt or "",
                        "why": c["why"], "todo": c["todo"]})
    flags = []
    for pat, desc, sev in RED_FLAGS:
        for m in re.finditer(pat, text, re.I):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 60):m.end() + 60]).strip()
            flags.append({"desc": desc, "sev": sev, "hit": s[:80], "context": ctx[:170]})
            break
    return results, flags


def main():
    p = argparse.ArgumentParser(description="租赁合同风险扫描")
    p.add_argument("--file", required=True)
    p.add_argument("--json", dest="json_out", default="")
    a = p.parse_args()

    text = open(a.file, encoding="utf-8", errors="ignore").read()
    if len(text.strip()) < 60:
        print("!! 文本太短，可能没读到内容。PDF 请先转成文本。")
        return 2
    results, flags = scan(text)

    missing = [r for r in results if not r["found"]]
    found_high = [r for r in results if r["found"] and r["sev"] == "high"]

    print("=" * 74)
    print("            租赁合同风险扫描（%d 字）" % len(text))
    print("=" * 74)

    print("\n【逐条核对】\n")
    for r in results:
        icon = "✔" if r["found"] else "✖"
        print("%s %s  %s" % (icon, SEV_LABEL[r["sev"]], r["title"]))
        if r["found"]:
            print("    原文：%s" % r["excerpt"])
        else:
            print("    **合同里没找到这一条** —— 这正是要问房东的。")
        print("    为什么重要：%s" % r["why"])
        print("    该怎么做：%s\n" % r["todo"])

    if flags:
        print("=" * 74)
        print("【红旗条款】%d 处 —— 逐条看，别跳" % len(flags))
        print("=" * 74)
        for f in flags:
            print("\n🚩 %s｜%s" % (SEV_LABEL[f["sev"]], f["desc"]))
            print("    命中：%s" % f["hit"])
            print("    上下文：%s" % f["context"])
        print()

    print("=" * 74)
    print("【汇总】")
    print("  已找到条款：%d/%d" % (len(results) - len(missing), len(results)))
    if missing:
        print("  ⚠️ 未找到（必须去问房东，不代表没问题）：")
        for r in missing:
            print("     · %s" % r["title"])
    if found_high:
        print("  高风险条款（已找到，要逐字读）：")
        for r in found_high:
            print("     · %s" % r["title"])
    if not flags:
        print("  红旗条款：未命中（不等于没有 —— 表述可能不同，仍需人工通读）")
    print()
    print("⚠️ 本工具是筛子不是律师：它只按关键词定位条款位置并标出常见红旗，")
    print("   不判断条款是否合法、不构成法律意见。签约前如有疑问，请学校国际办或")
    print("   当地租客协会（如意大利的 SUNIA / UDI）协助复核，多数对学生会免费。")

    if a.json_out:
        json.dump({"checks": results, "red_flags": flags},
                  open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n[已写出] %s" % a.json_out)
    return 1 if (flags or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
