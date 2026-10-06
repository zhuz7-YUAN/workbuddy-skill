#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
official_sources_scan.py —— 直抓「只在官网公布」的招聘信息（静态通道）

读同目录 sources.default.json（或用 --sources 指定的 sources.json）里的源清单，
只处理 channel == "curl" 的条目（其余通道交给 portal / spa_job_scrape 两个脚本）。

零依赖：仅 Python 3 标准库。

用法：
  python official_sources_scan.py                          # 抓全部 curl 源，打印
  python official_sources_scan.py --md 官网原始清单.md       # 同时写文件
  python official_sources_scan.py --region wuhan           # 只抓某地区
  python official_sources_scan.py --days 14                # 只看最近 14 天的公告
"""
import argparse, datetime, io, json, os, re, ssl, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122 Safari/537.36")

KW = re.compile(r"(招聘|招募|招录|公开招|事业单位|国企|央企|校招|校园招聘|人才引进|选调|"
                r"宣讲|双选|报名|岗位|拟聘|引进|补充公告|资格审查|笔试|面试|20\d{2})")
NOISE = re.compile(r"(首页|上一页|下一页|尾页|更多|登录|注册|网站地图|联系我们|版权|"
                   r"无障碍|繁體|English|设为首页|加入收藏|政策法规|友情链接)")


def load_sources(path=None):
    cands = [path] if path else [
        os.path.join(HERE, "sources.json"),
        os.path.join(HERE, "sources.default.json"),
    ]
    for p in cands:
        if p and os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                return json.load(f).get("sources", []), p
    sys.exit("找不到源清单（sources.json / sources.default.json）")


def fetch(url, enc="utf-8", timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            return _once(url, enc, timeout)
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(2.5 * (i + 1))     # 退避，避免被判定为洪水请求
    raise last


def _once(url, enc, timeout):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": url,
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        raw = r.read()
    for e in (enc, "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(e)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def extract(html):
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"&nbsp;|&#160;|\s+", " ", text).strip()
        if not (6 <= len(text) <= 90) or NOISE.search(text) or not KW.search(text):
            continue
        if text[:40] in seen:
            continue
        seen.add(text[:40])
        out.append((text, href))
    return out


def near_date(html, anchor):
    i = html.find(anchor[:20])
    if i < 0:
        return ""
    seg = html[max(0, i - 400): i + 400]
    for m in re.finditer(r"(20\d{2})[-/年\.](\d{1,2})[-/月\.](\d{1,2})", seg):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    return ""


def main():
    from urllib.parse import urljoin
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="")
    ap.add_argument("--md", default="")
    ap.add_argument("--region", default="")
    ap.add_argument("--days", type=int, default=0, help="只保留最近 N 天的公告（0=不限）")
    ap.add_argument("--max", type=int, default=20, help="每个源最多输出条数")
    a = ap.parse_args()

    srcs, used = load_sources(a.sources or None)
    todo = [s for s in srcs if s.get("channel") == "curl"
            and (not a.region or s.get("region") == a.region)]
    skipped = [s for s in srcs if s.get("channel") != "curl"]

    today = datetime.date.today()
    L = [f"# 官网原始清单（静态直抓）· {today.isoformat()}", "",
         f"源清单：`{os.path.basename(used)}` ｜ 直抓 {len(todo)} 个源，"
         f"另有 {len(skipped)} 个源走别的通道（见 portal / spa_job_scrape）", ""]
    total = 0
    for s in todo:
        L.append(f"## 【{s.get('type','')}】{s['name']}")
        L.append(f"源: {s['url']}")
        if s.get("note"):
            L.append(f"备注: {s['note']}")
        try:
            html = fetch(s["url"], s.get("encoding", "utf-8"))
            items = extract(html)
            kept = []
            for t, h in items:
                d = near_date(html, t)
                if a.days and d:
                    try:
                        dt = datetime.date(*map(int, d.split("-")))
                        if (today - dt).days > a.days:
                            continue
                    except Exception:
                        pass
                kept.append((t, urljoin(s["url"], h), d))
            if not kept:
                L.append("- ⚠️ 未解析出条目（页面结构可能变了，或该源应改用 browser 通道）")
            for t, h, d in kept[:a.max]:
                L.append(f"- {t}" + (f"  ({d})" if d else "") + f"\n  {h}")
                total += 1
            L.append(f"- 小计: {len(kept)} 条")
            print(f"[OK ] {s['name']}: {len(kept)} 条", file=sys.stderr)
        except Exception as e:
            L.append(f"- ❌ 抓取失败: {type(e).__name__}: {e}")
            print(f"[ERR] {s['name']}: {type(e).__name__}", file=sys.stderr)
        L.append("")

    if skipped:
        L.append("## 走其他通道的源（本脚本不处理）")
        for s in skipped:
            L.append(f"- [{s.get('channel')}] {s['name']}  {s.get('url','')}  ← {s.get('note','')}")
        L.append("")

    L.insert(3, f"**合计解析条目：{total}**\n")
    text = "\n".join(L)
    if a.md:
        with io.open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n[写入] {a.md}", file=sys.stderr)
    else:
        print(text)
    print(f"[合计] {total} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
