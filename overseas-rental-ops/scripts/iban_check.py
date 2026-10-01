#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iban_check.py — 收款账号核验（付押金前必跑一次）。

为什么单独做个工具：海外租房最常见的骗局是"押金打到一个账户，钱没了"。
IBAN 只要错一位，钱可能进别人账户；而假房东给的 IBAN 往往格式就不对。
本工具做三件事：
  1. 格式与校验位（mod-97）—— 一眼看出这是不是个真 IBAN
  2. 国家与长度 —— 该国的 IBAN 应该多长，对不上就是错的
  3. 与合同主体比对 —— 名字对不上是最高危信号

用法：
    python iban_check.py DE89 3704 0044 0532 0130 00
    python iban_check.py IT60X0542811101000000123456 --expect-name "Mario Rossi"
    python iban_check.py --file accounts.txt          # 每行一个 IBAN

只依赖 Python 标准库。声明：本工具只做格式与一致性检查，不能证明账户真实存在。
最终确认要靠银行转账页显示的收款人姓名与合同主体一致。
"""

import argparse
import re
import sys

# 参与 SEPA / 常见留学目的地国家的 IBAN 长度（以官方 IBAN Registry 为准，换国家时先核）
LENGTHS = {
    "IT": 27, "DE": 22, "FR": 27, "ES": 24, "NL": 18, "BE": 16, "PT": 25,
    "AT": 20, "IE": 22, "PL": 28, "CZ": 24, "SK": 24, "HU": 28, "SI": 19,
    "HR": 21, "GR": 27, "FI": 18, "SE": 24, "DK": 18, "NO": 15, "CH": 21,
    "GB": 22, "LU": 20, "EE": 20, "LV": 21, "LT": 20, "RO": 24, "BG": 22,
    "MT": 31, "CY": 28, "IS": 26, "LI": 21, "MC": 27, "SM": 27, "AD": 24,
    "VA": 22, "TR": 26, "UA": 29, "RS": 22, "MK": 19, "AL": 28, "BA": 20,
}

# SEPA 成员（走 SEPA 转账通常 1 个工作日、手续费低）
SEPA = set("""AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE
IS LI NO CH GB MC SM AD VA""".split())

# 非使用欧元的 SEPA 国家（币种不同，转账要留意汇率与到账币种）
NON_EUR = set("CZ DK HU PL SE GB IS LI NO CH RO BG HR".split())

# 高风险/不受 SEPA 约束的常见目的地（提示额外谨慎）
NON_SEPA = set("TR UA RS MK AL BA".split())


def only_alnum(s):
    return re.sub(r"[^A-Za-z0-9]", "", s or "").upper()


def iban_mod97(iban):
    """标准 mod-97 校验：移动前 4 位到末尾，字母转数字后取模，结果应为 1。"""
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def check_one(raw, expect_name=None):
    """返回 (level, lines)。level: ok / warn / bad"""
    iban = only_alnum(raw)
    lines = []
    issues = []
    warns = []

    if not iban:
        return "bad", ["  空值"]

    if len(iban) < 5:
        return "bad", ["  太短，不是 IBAN：%s" % raw]

    cc = iban[:2]
    if not cc.isalpha():
        issues.append("国家码不是两个字母（%s）" % cc)

    if cc in LENGTHS:
        if len(iban) != LENGTHS[cc]:
            issues.append("长度错误：%s 应为 %d 位，实际 %d 位" % (cc, LENGTHS[cc], len(iban)))
    else:
        warns.append("国家码 %s 不在校验表内（可能是非 SEPA 国家或已变更，请人工核实）" % cc)

    if all(c.isalnum() for c in iban):
        if not iban_mod97(iban):
            issues.append("mod-97 校验位不通过 —— 这个 IBAN 是错的（抄错或伪造）")
    else:
        issues.append("含非法字符")

    # 地区/币种提示
    if cc in SEPA:
        if cc in NON_EUR:
            warns.append("%s 属 SEPA 但非欧元区：转账会涉及币种换算，到账金额可能不同" % cc)
    elif cc in NON_SEPA:
        warns.append("%s 不在 SEPA 区：跨境汇款慢、可能被中间行扣费，且追款困难" % cc)
    else:
        warns.append("%s 是否为 SEPA 成员待核（非欧元区汇款到账慢）" % cc)

    if expect_name:
        lines.append("  合同/收款人（你填的）：%s" % expect_name)
        lines.append("  ⚠️ 必须核对：银行转账页显示的收款人姓名是否与上面一致。不一致 = 立刻停手。")

    lines = []
    if issues:
        for i in issues:
            lines.append("  ✗ " + i)
    for w in warns:
        lines.append("  ! " + w)
    if not issues:
        lines.append("  ✓ 格式与校验位通过（仍不能证明账户存在或属于房东）")

    return ("bad" if issues else ("warn" if warns else "ok")), lines


def main():
    p = argparse.ArgumentParser(description="IBAN 格式/校验位/一致性核验（付押金前必跑）")
    p.add_argument("iban", nargs="?", default="", help="IBAN（可带空格）")
    p.add_argument("--expect-name", dest="expect_name", default="", help="合同上的收款人姓名")
    p.add_argument("--file", default="", help="文件路径，每行一个 IBAN")
    args = p.parse_args()

    targets = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            targets = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    elif args.iban:
        targets = [args.iban]
    else:
        p.error("要么给一个 IBAN，要么用 --file")

    worst = "ok"
    print("=== IBAN 核验（%d 个）===" % len(targets))
    for t in targets:
        lvl, lines = check_one(t, args.expect_name or None)
        if lvl == "bad":
            worst = "bad"
        elif lvl == "warn" and worst != "bad":
            worst = "warn"
        icon = {"ok": "✓", "warn": "!", "bad": "✗"}[lvl]
        print("\n%s %s" % (icon, t))
        for ln in lines:
            print(ln)

    print("\n" + "-" * 56)
    if worst == "bad":
        print("结论：❌ 有 IBAN 不通过校验。绝对不要把押金打进去。")
        print("      让房东/中介重发账号，并比对合同上的收款人姓名。")
    elif worst == "warn":
        print("结论：⚠️ 格式通过，但有非欧元/非 SEPA 或待核项，转账前先确认币种与手续费。")
    else:
        print("结论：✅ 格式层面没问题。但仍需在银行转账页核对收款人姓名与合同一致后再付款。")
    print("\n红线：押金只付给合同上的房东或中介对公账户，且必须拿到收据。")
    return 1 if worst == "bad" else 0


if __name__ == "__main__":
    sys.exit(main())
