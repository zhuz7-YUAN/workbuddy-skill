#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sources.py — 房源平台登记表：扩充（add）→ 探测（probe）→ 自我学习（learn）。

三个真实需求对应三个子命令：
  1. 平台怎么扩充？        add      —— 每发现一个新渠道，登记进去，记清可达性
  2. 平台是死是活？        probe    —— 实测可达性（直连/登录墙/被墙），把结果写回登记表
  3. 什么叫"自我学习"？    learn    —— 抓回来的房源字段名与标准字段对不上时，记下新字段，
                                      下次遇到同一个平台就不用再猜。学的对象是
                                      「平台 × 字段模式」，不是玄学。

用法：
    python sources.py init                      # 首次生成 assets/sources.json（含种子平台）
    python sources.py list [--country IT]       # 列出已登记平台
    python sources.py add --id x --country IT --city Trento --type classified \\
                          --url https://... --access direct|login|blocked|proxy --notes "..."
    python sources.py probe [--id x | --all]            # 实测可达性并写回
        # 默认策略：直连优先，直连失败才自动降级走代理（--direct 禁用降级；
        #          --proxy 强制只用代理）。会打印实际走的路由。
    python sources.py learn --file listings.json  # 扫字段，未知字段记进 learned_fields
    python sources.py report                    # 汇总：各国平台数 / 待验证 / 待归一的字段

只依赖 Python 标准库。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "..", "assets", "sources.json")

# 标准字段（抓取层统一输出这套键；learn 用它做对照）
CANONICAL_FIELDS = [
    "title", "url", "price", "spese_extra", "city", "cap", "address",
    "libera_da", "permanenza_min", "cauzione", "tipo_contratto", "gender",
    "size", "notes", "source",
]

# 已知字段别名（不同平台叫法 → 标准字段）。learn 会往里补。
DEFAULT_ALIASES = {
    "Libera da": "libera_da", "Disponibile da": "libera_da", "Verfuegbar ab": "libera_da",
    "Disponible a partir de": "libera_da", "Disponible desde": "libera_da",
    "Permanenza minima": "permanenza_min", "Soggiorno minimo": "permanenza_min",
    "Mindestmietdauer": "permanenza_min", "Duree minimale": "permanenza_min",
    "Spese extra": "spese_extra", "Spese incluse": "spese_extra",
    "Nebenkosten": "spese_extra", "Charges comprises": "spese_extra",
    "Cauzione": "cauzione", "Deposito": "cauzione", "Kaution": "cauzione",
    "Garantie": "cauzione", "Deposit": "cauzione", "Fianza": "cauzione",
    "Tipo contratto": "tipo_contratto", "Contratto": "tipo_contratto",
    "Stato": "notes", "Zona": "city", "Localita": "city", "Affitto": "price",
    "Canone": "price", "Prezzo": "price", "Miete": "price", "Rent": "price",
}

SEED = {
    "_note": "平台登记表。sources.py 读写。access: direct=可直连 / login=登录墙 / proxy=需代理 / blocked=被墙 / unknown=未实测。",
    "canonical_fields": CANONICAL_FIELDS,
    "aliases": DEFAULT_ALIASES,
    "sources": [
        {
            "id": "operauni_trento", "country": "IT", "city": "Trento",
            "type": "official_board", "name": "Opera Universitaria Trento 房源板",
            "url": "https://trent.operauni.tn.it/", "access": "login",
            "contact_via": "board_form", "extractor": "extract_example_operauni.py",
            "note": "需在校生身份注册；本机 Edge 曾 ERR_CONNECTION_RESET，curl 可通 → 用代理或换网络",
            "status": "active", "last_probe": None,
        },
        {
            "id": "subito_it", "country": "IT", "city": "*",
            "type": "classified", "name": "Subito.it",
            "url": "https://www.subito.it/", "access": "unknown",
            "contact_via": "form_or_phone", "extractor": "",
            "note": "详情页才有电话；无公开邮箱", "status": "active", "last_probe": None,
        },
        {
            "id": "idealista_it", "country": "IT", "city": "*",
            "type": "classified", "name": "Idealista.it",
            "url": "https://www.idealista.it/", "access": "unknown",
            "contact_via": "form", "extractor": "",
            "note": "中介为主，回复率取决于中介", "status": "active", "last_probe": None,
        },
        {
            "id": "immobiliare_it", "country": "IT", "city": "*",
            "type": "classified", "name": "Immobiliare.it",
            "url": "https://www.immobiliare.it/", "access": "unknown",
            "contact_via": "form", "extractor": "",
            "note": "中介主导", "status": "active", "last_probe": None,
        },
        {
            "id": "fb_groups_it", "country": "IT", "city": "*",
            "type": "social_group", "name": "Facebook 租房群",
            "url": "https://www.facebook.com/groups/", "access": "login",
            "contact_via": "dm", "extractor": "edge-cdp-scrape",
            "note": "只草拟文案由人粘贴，不自动发送", "status": "active", "last_probe": None,
        },
        {
            "id": "wg_gesucht", "country": "DE", "city": "*",
            "type": "classified", "name": "WG-Gesucht",
            "url": "https://www.wg-gesucht.de/", "access": "unknown",
            "contact_via": "form", "extractor": "",
            "note": "德国合租主力站", "status": "active", "last_probe": None,
        },
        {
            "id": "studapart_fr", "country": "FR", "city": "*",
            "type": "student_platform", "name": "Studapart",
            "url": "https://www.studapart.com/", "access": "unknown",
            "contact_via": "form", "extractor": "",
            "note": "法国学生租房平台，支持 Visale 担保", "status": "active", "last_probe": None,
        },
        {
            "id": "housinganywhere", "country": "EU", "city": "*",
            "type": "student_platform", "name": "HousingAnywhere",
            "url": "https://housinganywhere.com/", "access": "unknown",
            "contact_via": "platform", "extractor": "",
            "note": "泛欧短租平台，适合 4–6 个月交换生，但服务费高", "status": "active", "last_probe": None,
        },
    ],
    "candidates": [],
    "learned_fields": {},
}


def _load(path, create=False):
    if not os.path.exists(path):
        if not create:
            print("[错误] 找不到 %s。先跑： python sources.py init" % path)
            sys.exit(2)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(SEED, f, ensure_ascii=False, indent=2)
        print("[已生成] %s（含 %d 个种子平台）" % (path, len(SEED["sources"])))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_init(args):
    p = args.file or DEFAULT_DB
    if os.path.exists(p) and not args.force:
        print("[跳过] %s 已存在。要覆盖加 --force" % p)
        return 0
    if os.path.exists(p) and args.force:
        os.remove(p)
    _load(p, create=True)
    return 0


def cmd_list(args):
    d = _load(args.file or DEFAULT_DB)
    rows = d["sources"]
    if args.country:
        rows = [r for r in rows if r.get("country") == args.country]
    if not rows:
        print("（无记录）")
        return 0
    print("%-18s %-4s %-9s %-12s %-9s %s" % ("id", "国家", "城市", "类型", "可达性", "最近探测"))
    print("-" * 92)
    for r in rows:
        lp = r.get("last_probe") or {}
        lp_s = ("%s %s" % (lp.get("status", ""), lp.get("at", "")[:10])) if lp else "未探测"
        print("%-18s %-4s %-9s %-12s %-9s %s" %
              (r.get("id", "")[:18], r.get("country", ""), r.get("city", "")[:9],
               r.get("type", "")[:12], r.get("access", ""), lp_s))
    print("\n共 %d 条。" % len(rows))
    return 0


def cmd_add(args):
    p = args.file or DEFAULT_DB
    d = _load(p, create=True)
    if any(s.get("id") == args.id for s in d["sources"]):
        print("[已存在] id=%s，未重复添加。要改请直接编辑 JSON 或先删除。" % args.id)
        return 1
    d["sources"].append({
        "id": args.id, "country": args.country, "city": args.city or "*",
        "type": args.type or "unknown", "name": args.name or args.id,
        "url": args.url, "access": args.access or "unknown",
        "contact_via": args.contact_via or "unknown", "extractor": "",
        "note": args.notes or "", "status": "active", "last_probe": None,
    })
    _save(p, d)
    print("[已添加] %s → %s（%d 条）" % (args.id, p, len(d["sources"])))
    print("下一步： python sources.py probe --id %s  —— 实测可达性" % args.id)
    return 0


def _detect_system_proxy():
    """读环境变量/系统设置里配置的代理（有则返回 URL，无则空串）。"""
    try:
        env = urllib.request.getproxies()
    except Exception:  # noqa
        return ""
    return env.get("https") or env.get("http") or ""


def _probe_once(url, timeout=12, proxy=None, force_direct=False):
    """单次探测。force_direct=True 时强制不走代理。

    返回 (status, detail, via)。status: ok / auth / blocked / error / bad_url
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    })
    if force_direct:
        # 空 ProxyHandler = 显式禁用一切代理
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        via = "直连"
    elif proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        via = "代理 %s" % proxy
    else:
        opener = urllib.request.build_opener()
        p = _detect_system_proxy()
        via = ("系统代理 %s" % p) if p else "直连"
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(4000)
            code = r.getcode()
            final = r.geturl()
            low = body.decode("utf-8", "ignore").lower()
            if "login" in low or "accedi" in low or "password" in low or "sign in" in low:
                return "auth", "HTTP %s，页面含登录字样（疑似登录墙）final=%s" % (code, final), via
            return "ok", "HTTP %s，可访问，final=%s" % (code, final), via
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "auth", "HTTP %s（拒绝访问 / 需登录或反爬）" % e.code, via
        return "error", "HTTP %s" % e.code, via
    except urllib.error.URLError as e:
        return "blocked", "连接失败：%s（被墙/需代理/域名失效）" % e.reason, via
    except Exception as e:  # noqa
        return "error", "%s: %s" % (type(e).__name__, e), via


def _probe_auto(url, timeout=12, proxy=None, direct_only=False):
    """默认策略：**直连优先；直连失败才降级走代理。**

    为什么这样设计：国内用户直连通常更快、不消耗代理流量、不受节点质量拖累；
    只有直连不通（被墙/超时/被重置）时才回退到代理。
    代理只作为"兜底通道"，不作为默认通道。

    返回 (status, detail, route_note)
    """
    st, detail, via = _probe_once(url, timeout=timeout, force_direct=True)
    if st in ("ok", "auth"):
        return st, detail, "直连"

    # 直连失败 —— 开始降级
    if direct_only:
        return st, detail + "（--direct：只用直连，不降级）", "直连（未降级）"

    p = proxy or _detect_system_proxy()
    if not p:
        return st, detail + "；且未检测到可用代理，无法降级", "直连（无代理可降级）"

    st2, detail2, _ = _probe_once(url, timeout=timeout, proxy=p)
    if st2 in ("ok", "auth"):
        return st2, detail2 + " ｜直连失败（%s），已自动降级走代理" % detail, "降级→代理 %s" % p
    return st, detail + "；代理 %s 亦失败（%s）" % (p, detail2), "直连与代理均失败"


def cmd_probe(args):
    p = args.file or DEFAULT_DB
    d = _load(p, create=True)
    targets = d["sources"] if args.all else [s for s in d["sources"] if s.get("id") == args.id]
    if not targets:
        print("[错误] 没找到要探测的平台。用 --id <id> 或 --all")
        return 2
    now = datetime.now().isoformat(timespec="seconds")
    if args.proxy:
        mode = "强制走代理 %s" % args.proxy
    elif args.direct:
        mode = "只用直连"
    else:
        mode = "直连优先，失败才降级走代理"
    print("探测 %d 个平台（超时 %ss，模式：%s）" % (len(targets), args.timeout, mode))
    print("说明：只向目标站发一次只读 GET。目标站必然看到访问者的出口 IP（浏览器同理），")
    print("      本工具会把实际走的路线打印出来，便于确认走的是直连还是代理。\n")
    for s in targets:
        status, detail, route = _probe_auto(s["url"], timeout=args.timeout,
                                           proxy=args.proxy or None,
                                           direct_only=args.direct)
        s["last_probe"] = {"at": now, "status": status, "detail": detail, "route": route}
        # 实测为被墙/需登录时，把 access 同步过来（探测结果优先于人工标注）
        if status == "blocked":
            s["access"] = "proxy"
        elif status == "auth" and s.get("access") in ("unknown", "direct"):
            s["access"] = "login"
        elif status == "ok" and s.get("access") == "unknown":
            s["access"] = "direct"
        flag = {"ok": "✓", "auth": "🔒", "blocked": "⛔", "error": "!", "bad_url": "!"}.get(status, "?")
        print("%s %-18s %s" % (flag, s["id"], detail))
        print("    路由：%s" % route)
    _save(p, d)
    print("\n[已写回] %s" % p)
    print("提示：路由显示「直连」= 没走代理；显示「降级→代理」= 直连不通才挂代理；")
    print("      被墙的平台抓取时也要走代理，登录墙的先登录再抓（edge-cdp-scrape）。")
    return 0


def cmd_learn(args):
    p = args.file or DEFAULT_DB
    d = _load(p, create=True)
    if not os.path.exists(args.scrape):
        print("[错误] 找不到 %s" % args.scrape)
        return 2
    with open(args.scrape, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("listings", [])
    if not items:
        print("[错误] %s 里没有房源记录（期望 list 或 {'listings': [...]}）" % args.scrape)
        return 2

    canon = set(d.get("canonical_fields", CANONICAL_FIELDS))
    aliases = d.setdefault("aliases", dict(DEFAULT_ALIASES))
    lf = d.setdefault("learned_fields", {})

    seen = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        for k, v in it.items():
            if k in canon:
                continue
            if k in seen:
                seen[k]["count"] += 1
            else:
                seen[k] = {"count": 1, "example": str(v)[:60]}

    new_keys = [k for k in seen if k not in aliases and k not in lf]
    print("=== 自我学习：比对字段（标准字段 %d 个）===" % len(canon))
    if not new_keys:
        print("✓ 本次没有出现未知字段。已知别名映射已覆盖：%d 条。" % len(aliases))
        return 0

    src_id = args.source or "(未指定)"
    print("\n发现 %d 个未知字段，已记入 learned_fields：\n" % len(new_keys))
    print("%-26s %-6s %s" % ("字段名", "出现", "样例值"))
    print("-" * 80)
    for k in new_keys:
        lf[k] = {"count": seen[k]["count"], "example": seen[k]["example"],
                 "seen_in": src_id, "at": datetime.now().isoformat(timespec="seconds")}
        print("%-26s %-6s %s" % (k[:26], seen[k]["count"], seen[k]["example"]))
        aliases.setdefault(k, "")
    _save(p, d)
    print("\n[已写回] %s" % p)
    print("\n要把它归类到标准字段，编辑 JSON 的 aliases，把值从 \"\" 改成对应标准字段，例如：")
    print('    "Zona": "city"    ← 其中 city 必须是 canonical_fields 里的一个')
    return 0


def cmd_report(args):
    d = _load(args.file or DEFAULT_DB)
    srcs = d["sources"]
    by_country = {}
    for s in srcs:
        by_country.setdefault(s.get("country", "?"), 0)
        by_country[s["country"]] += 1
    unprobed = [s["id"] for s in srcs if not s.get("last_probe")]
    proxy = [s["id"] for s in srcs if s.get("access") == "proxy"]
    login = [s["id"] for s in srcs if s.get("access") == "login"]
    unmapped = [k for k, v in (d.get("aliases") or {}).items() if not v]
    print("=== 平台登记表汇总 ===")
    print("平台总数：%d" % len(srcs))
    print("按国家：" + "、".join("%s=%d" % (k, v) for k, v in sorted(by_country.items())))
    print("待探测：%d%s" % (len(unprobed), (" → " + ", ".join(unprobed[:6])) if unprobed else ""))
    print("需代理：%d%s" % (len(proxy), (" → " + ", ".join(proxy)) if proxy else ""))
    print("需登录：%d%s" % (len(login), (" → " + ", ".join(login)) if login else ""))
    print("候选（待评估入表）：%d" % len(d.get("candidates") or []))
    print("待归一的字段：%d%s" % (len(unmapped), (" → " + ", ".join(unmapped[:8])) if unmapped else ""))
    print("\n健康度建议：待探测 > 0 先跑 probe；待归一字段时间多再清。")
    return 0


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--file", default="", help="登记表路径（默认 assets/sources.json，可放在子命令之后）")

    p = argparse.ArgumentParser(description="房源平台登记表：add / probe / learn / list / report")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("init", help="生成登记表（含种子平台）", parents=[common])
    s1.add_argument("--force", action="store_true")
    s1.set_defaults(func=cmd_init)

    s2 = sub.add_parser("list", help="列出平台", parents=[common])
    s2.add_argument("--country", default="")
    s2.set_defaults(func=cmd_list)

    s3 = sub.add_parser("add", help="登记一个新平台", parents=[common])
    s3.add_argument("--id", required=True)
    s3.add_argument("--country", required=True)
    s3.add_argument("--city", default="*")
    s3.add_argument("--type", default="unknown",
                    help="official_board/classified/student_platform/social_group/agency/other")
    s3.add_argument("--name", default="")
    s3.add_argument("--url", required=True)
    s3.add_argument("--access", default="unknown", choices=["unknown", "direct", "login", "proxy", "blocked"])
    s3.add_argument("--contact-via", dest="contact_via", default="unknown")
    s3.add_argument("--notes", default="")
    s3.set_defaults(func=cmd_add)

    s4 = sub.add_parser("probe", help="实测可达性并写回（默认直连优先，失败才降级走代理）", parents=[common])
    s4.add_argument("--id", default="")
    s4.add_argument("--all", action="store_true")
    s4.add_argument("--timeout", type=int, default=12)
    s4.add_argument("--direct", action="store_true",
                    help="只用直连，直连失败也不降级走代理")
    s4.add_argument("--proxy", default="",
                    help="强制走该代理（如 http://127.0.0.1:7890），不做直连尝试")
    s4.set_defaults(func=cmd_probe)

    s5 = sub.add_parser("learn", help="扫抓取结果，记录未知字段", parents=[common])
    s5.add_argument("--scrape", required=True, help="listings.json 路径")
    s5.add_argument("--source", default="", help="这批数据来自哪个 source id")
    s5.set_defaults(func=cmd_learn)

    s6 = sub.add_parser("report", help="汇总", parents=[common])
    s6.set_defaults(func=cmd_report)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
