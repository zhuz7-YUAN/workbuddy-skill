#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify.py —— 房源核验规则引擎
把"索引页抄来的字段"变成"能下结论的判定"，并对每条给出原因。

规则实现在 references/verification_rules.md，本脚本是其可执行版本。

用法：
  verify.py --db rental/housing.db --city Trento --caps 38121,38122,38123,38100
  verify.py --json-in listings.json          # 不依赖台账，直接核验一份 JSON
  verify.py --db ... --explain 12            # 只看某条的判定理由

判定档位：direct(可直接联系) / inquiry(先问再推) / nearby(不在目标城市)
         / unverified(未核实) / excluded(已排除)
"""
import argparse, json, os, sqlite3, datetime, re, sys

TODAY = datetime.date.today()


def parse_date(s):
    """支持 dd/mm/yyyy 与 yyyy-mm-dd；解析失败返回 None"""
    if not s:
        return None
    s = str(s).strip()
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def months_between(a, b):
    return round((b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.0, 1)


def verify_one(it, city, caps, max_vacant, budget, has_positive_reply=False):
    """返回 (verdict, flags[])"""
    flags = []
    verdict = "unverified"

    # 1) 空置状态（必须来自详情页）
    st = (it.get("status") or "").strip().lower()
    if st in ("occupata", "occupato", "occupied", "已占"):
        return "excluded", ["已占用（Occupata）"]
    if st not in ("libera", "libero", "free", "空"):
        flags.append("状态未知（需进详情页确认 Stato）")

    # 2) 城市
    cap = str(it.get("cap") or "").strip()
    if not cap:
        flags.append("城市/CAP 未确认（详情页地址没读到）")
    elif caps and cap not in caps:
        return "nearby", flags + ["不在%s（CAP %s）" % (city, cap)]

    # 3) 起租日
    fd = parse_date(it.get("free_from"))
    vac = None
    if fd is None:
        flags.append("起租日未标注，需确认")
    elif fd > TODAY:
        flags.append("%s 起可住（现在不能住）" % fd.strftime("%Y-%m-%d"))
    else:
        vac = months_between(fd, TODAY)
        if vac > max_vacant:
            flags.append("僵尸房源（已空置约 %s 个月）" % vac)

    # 4) 月总成本
    rent = it.get("rent")
    extra = it.get("extra_fees") or 0
    if rent:
        total = round(float(rent) + float(extra), 0)
        if budget and total > budget:
            flags.append("月总成本 €%s 超预算" % total)

    # 5) 最短租期
    ms = it.get("min_stay_months")
    if ms is None:
        ms = it.get("min_stay")
    msn = None
    if ms is not None:
        s = str(ms).lower()
        m = re.search(r"(\d+)", s)
        if m:
            msn = float(m.group(1))
        elif "anno" in s or "annual" in s or "年" in s:
            msn = 12.0
        elif "mese" in s or "month" in s:
            msn = 1.0
    if msn is None:
        flags.append("最短租期未读，需确认")
    elif msn > 6:
        flags.append("最短租期 %.0f 个月，需谈缩短/转租" % msn)

    # 6) C2C 时效
    pa = it.get("posted_at")
    hot = int(it.get("hot_comments") or 0)
    if pa:
        pd = None
        for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                pd = datetime.datetime.strptime(str(pa)[:len(f) + 2], f)
                break
            except ValueError:
                pass
        if pd:
            hrs = (datetime.datetime.now() - pd).total_seconds() / 3600.0
            if hrs > 12 or hot >= 2:
                flags.append("大概率已租走（发布 %.0f 小时、%d 人已私信）" % (hrs, hot))

    # 7) 汇总判定
    must_inquiry = any(("不能住" in f) or ("需谈" in f) or ("需确认" in f)
                       or ("大概率已租走" in f) or ("状态未知" in f) for f in flags)
    if has_positive_reply and not must_inquiry and vac is not None and vac <= max_vacant:
        verdict = "direct"
    elif must_inquiry:
        verdict = "inquiry"
    else:
        verdict = "direct" if has_positive_reply else "unverified"
    return verdict, flags


def run(items, city, caps, max_vacant, budget, positive_ids=()):
    out = []
    for it in items:
        v, fl = verify_one(it, city, caps, max_vacant, budget,
                           has_positive_reply=(str(it.get("id")) in positive_ids))
        it["verdict"] = v
        it["flags"] = fl
        out.append(it)
    return out


def render(items):
    order = {"direct": 0, "inquiry": 1, "nearby": 2, "unverified": 3, "excluded": 4}
    items = sorted(items, key=lambda x: order.get(x["verdict"], 9))
    print("%-4s %-11s %-30s %-12s %-9s %s" % ("#", "判定", "标题", "城市/CAP", "月总成本", "标记"))
    print("-" * 118)
    for it in items:
        print("%-4s %-11s %-30s %-12s %-9s %s" % (
            it.get("id", "-"), it["verdict"], (it.get("title") or it.get("url") or "")[:29],
            ("%s %s" % (it.get("city") or "?", it.get("cap") or "")).strip()[:11],
            ("€%s" % (it.get("total_month") or it.get("rent") or "?"))[:8],
            "；".join(it["flags"])))
    print("\n统计：", {v: sum(1 for x in items if x["verdict"] == v)
                    for v in ("direct", "inquiry", "nearby", "unverified", "excluded")})
    print("\n提醒：只有 direct 档可以直接给租客；其余一律先走问询或剔除。")


def main():
    p = argparse.ArgumentParser(description="房源核验规则引擎")
    p.add_argument("--db"); p.add_argument("--json-in"); p.add_argument("--json-out")
    p.add_argument("--city", default="Trento")
    p.add_argument("--caps", default="38121,38122,38123,38100")
    p.add_argument("--max-vacant", type=float, default=6, help="空置超过几个月的算僵尸房源")
    p.add_argument("--budget", type=float, default=0, help="月总成本上限，0=不限")
    p.add_argument("--explain")
    a = p.parse_args()
    caps = [c.strip() for c in a.caps.split(",") if c.strip()]

    if a.json_in:
        items = json.load(open(a.json_in, encoding="utf-8"))
        if isinstance(items, dict):
            items = items.get("listings", [])
        positive = set()
    else:
        if not a.db or not os.path.exists(a.db):
            print("!! 需要 --db 指向存在的台账，或用 --json-in"); sys.exit(1)
        con = sqlite3.connect(a.db); con.row_factory = sqlite3.Row
        items = [dict(r) for r in con.execute("select * from listings").fetchall()]
        positive = {str(r["listing_id"]) for r in con.execute(
            "select distinct listing_id from contacts where outcome='available'")}

    if a.explain:
        for it in items:
            if str(it.get("id")) == str(a.explain):
                v, fl = verify_one(it, a.city, caps, a.max_vacant, a.budget)
                print("房源 #%s" % a.explain)
                for k, val in it.items():
                    print("   %-16s %s" % (k, val))
                print("--> 判定：%s" % v)
                for f in fl:
                    print("     · %s" % f)
                return
        print("找不到 #%s" % a.explain); return

    res = run(items, a.city, caps, a.max_vacant, a.budget, positive)
    render(res)

    if a.json_out:
        json.dump(res, open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n已写出：%s" % a.json_out)

    if a.db:
        con = sqlite3.connect(a.db)
        for it in res:
            if it.get("id"):
                con.execute("update listings set verdict=?, flags=?, total_month=coalesce(total_month,?) where id=?",
                            (it["verdict"], json.dumps(it["flags"], ensure_ascii=False),
                             (float(it.get("rent") or 0) + float(it.get("extra_fees") or 0)) or None,
                             it["id"]))
        con.commit(); con.close()
        print("已把判定写回台账。")


if __name__ == "__main__":
    main()
