#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
official_sources_portal.py —— 生成「官网直读清单」网页（给抓不到的源留一条路）

对每个源生成三样东西：
  ① 栏目直达链接（点开就是招聘列表，自己读）
  ② 一键搜索链接（百度 / 必应，site: 限定 + 关键词）—— 像百度一样用
  ③ 通道标记（能不能自动抓 / 只能人工点）

读同目录 sources.default.json（或 sources.json），可选读上两级的 config.json
取「城市」「方向」来生成个性化检索词。

零依赖：仅 Python 3 标准库。

用法：
  python official_sources_portal.py                 # 生成 官网直读清单.html
  python official_sources_portal.py --probe         # 先在线探测各源状态再生成
  python official_sources_portal.py --out x.html
  python official_sources_portal.py --manual-only   # 只列"抓不到、必须人工点"的源
"""
import argparse, datetime, html as htmlmod, io, json, os, re, ssl, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122 Safari/537.36")

CH_LABEL = {
    "curl":     ("可自动抓", "t-ok"),
    "webfetch": ("需 AI 网页读取", "t-ok"),
    "browser":  ("需浏览器渲染后自动抓", "t-warn"),
    "manual":   ("★抓不到 · 只能你点开看", "t-bad"),
    "search":   ("仅关键词检索", "t-warn"),
}


def load_json(path):
    if path and os.path.exists(path):
        try:
            with io.open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def load_sources(path=None):
    for p in ([path] if path else [os.path.join(HERE, "sources.json"),
                                   os.path.join(HERE, "sources.default.json")]):
        if p and os.path.exists(p):
            return load_json(p).get("sources", [])
    sys.exit("找不到源清单")


def load_config():
    for p in (os.path.join(HERE, "config.json"),
              os.path.join(HERE, "..", "config.json"),
              os.path.join(HERE, "..", "..", "config.json")):
        d = load_json(os.path.normpath(p))
        if d:
            return d
    return {}


def probe(url, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read(300000)
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}
    txt = ""
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            txt = raw.decode(enc); break
        except Exception:
            continue
    if not txt:
        txt = raw.decode("utf-8", "ignore")
    t = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S | re.I)
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", txt)
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
    spa = len(body) < 400 or bool(re.search(r'id=["\'](app|root)["\']', txt))
    return {"ok": True, "title": re.sub(r"\s+", " ", t.group(1)).strip() if t else "",
            "chars": len(body), "spa": spa,
            "has_job": bool(re.search(r"招聘|招募|岗位|校园招聘", body + " " + txt[:4000]))}


def search_links(domain, kw):
    q = urllib.parse.quote(f"site:{domain} {kw}")
    return [("百度", f"https://www.baidu.com/s?wd={q}"),
            ("必应", f"https://cn.bing.com/search?q={q}")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="")
    ap.add_argument("--out", default="官网直读清单.html")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--manual-only", action="store_true")
    a = ap.parse_args()

    srcs = load_sources(a.sources or None)
    cfg = load_config()
    prof = cfg.get("profile", {}) if isinstance(cfg, dict) else {}
    city = prof.get("city", "") or "本地"
    dirs = prof.get("directions", "") or ""
    kws = [x.strip() for x in re.split(r"[、,，/|]+", dirs) if x.strip()][:3] or ["校园招聘", "应届生", "校招补录"]
    extra = [city, f"{city} 国企", f"{city} 事业单位"]
    all_kw = kws + extra

    if a.manual_only:
        srcs = [s for s in srcs if s.get("channel") == "manual"]

    today = datetime.date.today().isoformat()
    P = []
    P.append("<!doctype html><html lang=zh-CN><head><meta charset=utf-8>")
    P.append("<meta name=viewport content='width=device-width,initial-scale=1'>")
    P.append(f"<title>官网直读清单 · {today}</title>")
    P.append("""<style>
:root{color-scheme:light}
body{margin:0;background:#f5f6f8;color:#181a1c;font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:26px 16px 70px}
h1{font-size:23px;margin:0 0 6px}
.sub{color:#6b7280;font-size:13px;margin-bottom:14px}
.note{background:#fff8e6;border-left:4px solid #e8b100;padding:12px 15px;border-radius:5px;font-size:13.5px;color:#54430a;margin:14px 0 22px}
h2{font-size:16.5px;margin:28px 0 10px;padding-left:9px;border-left:4px solid #2563eb}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:9px;padding:15px 17px;margin:0 0 12px}
.nm{font-weight:600;font-size:15.5px}
.tag{display:inline-block;font-size:11.5px;padding:1.5px 8px;border-radius:10px;margin-left:8px;vertical-align:2px;white-space:nowrap}
.t-ok{background:#e7f6ec;color:#166534}
.t-warn{background:#fff3e0;color:#9a5600}
.t-bad{background:#fdecec;color:#b91c1c}
.meta{color:#5f6672;font-size:12.5px;margin:6px 0 2px}
.lnk{display:inline-block;margin:8px 8px 0 0;padding:6px 13px;border-radius:6px;text-decoration:none;font-size:13.5px}
.p{background:#2563eb;color:#fff}
.s{background:#eef2f7;color:#274060;border:1px solid #d6dee8}
.g{background:#eaf7ee;color:#166534;border:1px solid #cee8d7}
.url{font-family:Consolas,monospace;font-size:11.5px;color:#8a9099;word-break:break-all;margin-top:7px}
.dir{margin-top:11px;padding-top:9px;border-top:1px dashed #e5e7eb}
.dir b{font-size:12.5px;color:#4b5563}
footer{color:#9aa0a8;font-size:12px;margin-top:36px;text-align:center}
</style></head><body><div class="wrap">""")
    P.append("<h1>官网直读清单</h1>")
    P.append(f"<div class='sub'>生成 {today} ｜ 城市：{htmlmod.escape(str(city))} ｜ "
             f"共 {len(srcs)} 个源 ｜ 用途：抓不到的官网，点开自己读</div>")
    P.append("""<div class='note'><b>怎么用：</b>
蓝色＝直接打开该站招聘栏（你自己读）；灰色＝百度/必应站内搜索（像百度一样输关键词）。<br>
<b>为什么要有这一页：</b>国企/事业单位的岗位很多只挂自己官网，而这些站多为 JS 动态加载（SPA）
或带反爬，程序读不到正文。<b>但链接是真的、地址是准的</b> —— 给你地址，你几分钟就看完了。</div>""")

    seen_cat, results = [], {}
    for s in srcs:
        if s.get("type") not in seen_cat:
            seen_cat.append(s.get("type"))

    if a.probe:
        print("[探测]", file=sys.stderr)
        for s in srcs:
            if s.get("channel") in ("curl", "webfetch", "browser") and s.get("url"):
                m = probe(s["url"])
                results[s["url"]] = m
                flag = "打不开" if not m["ok"] else ("SPA" if m["spa"] else
                                                    ("有招聘字样" if m["has_job"] else "未见招聘字样"))
                print(f"  {s['name'][:28]:30s} {flag}", file=sys.stderr)

    for cat in seen_cat:
        P.append(f"<h2>{htmlmod.escape(str(cat))}</h2>")
        for s in [x for x in srcs if x.get("type") == cat]:
            ch = s.get("channel", "")
            lab, cls = CH_LABEL.get(ch, (ch, "t-warn"))
            m = results.get(s.get("url", ""), {})
            if m and not m.get("ok"):
                lab, cls = f"打不开（{m.get('err','')}）", "t-bad"
            P.append("<div class='card'>")
            P.append(f"<div class='nm'>{htmlmod.escape(str(s.get('name','')))}"
                     f"<span class='tag {cls}'>{htmlmod.escape(lab)}</span></div>")
            if s.get("note"):
                P.append(f"<div class='meta'>{htmlmod.escape(str(s['note']))}</div>")
            if m and m.get("ok"):
                P.append(f"<div class='meta'>实测：标题「{htmlmod.escape(m.get('title','')[:50]) or '（空）'}」"
                         f" ｜ 正文约 {m.get('chars',0)} 字</div>")
            url = s.get("url") or ""
            if url:
                P.append(f"<a class='lnk p' href='{htmlmod.escape(url)}' target='_blank' rel='noopener'>"
                         f"打开该站招聘栏 →</a>")
                P.append(f"<div class='url'>{htmlmod.escape(url)}</div>")
            dom = ""
            if url:
                dom = urllib.parse.urlparse(url).netloc.replace("www.", "")
            if dom:
                P.append("<div class='dir'><b>一键搜索（替你把关，你自己看）</b>")
                for kw in all_kw:
                    P.append(f"<div style='margin:7px 0 2px;font-size:12.5px;color:#3f4650'>【{htmlmod.escape(kw)}】</div>")
                    for lb, lu in search_links(dom, kw):
                        P.append(f"<a class='lnk s' href='{htmlmod.escape(lu)}' target='_blank' "
                                 f"rel='noopener'>{lb}</a>")
                for kw in all_kw[:2]:
                    lu = "https://www.baidu.com/s?wd=" + urllib.parse.quote(kw)
                    P.append(f"<a class='lnk g' href='{htmlmod.escape(lu)}' target='_blank' "
                             f"rel='noopener'>不限站·{htmlmod.escape(kw)}</a>")
                P.append("</div>")
            P.append("</div>")

    P.append("<footer>由 job-brief-generator 的 official_sources_portal.py 生成，可随时重跑刷新。</footer>")
    P.append("</div></body></html>")
    out = "".join(P)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[生成] {a.out}  ({len(out)} 字符, {len(srcs)} 个源)", file=sys.stderr)


if __name__ == "__main__":
    main()
