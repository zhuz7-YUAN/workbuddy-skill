#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""commute.py — 通勤计算：房源到"工作/学习地"的距离与时间。

为什么需要它：欧洲的房源站（subito / idealista / 学生房源板）**页面本身不给通勤信息**。
而"离学校/上班地点多远"恰恰是选房最关键的参考值之一。本工具用免费、无需 API Key 的
开放数据把这个补上。

数据源（全部免费、无需注册、无 Key）：
  · Photon（komoot）     地址 → 经纬度         直连可用
  · Nominatim（OSM 官方）地址 → 经纬度（备用）  直连常超时，走代理可用
  · OSRM（project-osrm） 两点 → 步行/骑行/驾车耗时
  · Overpass API         坐标 → 最近的公交/地铁/火车站

网络策略：**直连优先，失败才降级走代理**（与 sources.py 同一原则）。

⚠️ 诚实的边界（务必读）：
  1. 本工具给的是 **步行/骑行/驾车** 时间 + **最近公共交通站点的距离**。
  2. 它**不计算真实公交/地铁的乘车耗时**（含等车、转乘、班次间隔）——
     那需要各城市 GTFS 时刻表数据，本地算不准。**不假装能算。**
  3. 结果用于**初筛排序**，不是替代实地测通勤。选定的房源必须实地跑一趟。

用法：
  python commute.py geocode --address "Via Verdi 10, Trento"
  python commute.py route --from "Via Verdi 10, Trento" --to "Via Sommarive 5, Trento"
  python commute.py enrich --db rental/housing.db --to "Via Sommarive 5, Trento" --limit 20
  python commute.py show   --db rental/housing.db [--links]
  python commute.py map    --db rental/housing.db --out commute_map.html
  python commute.py cache  --clear

地图连接器：`show --links` 给每条房源的导航链接；`map` 生成一张自包含 HTML 地图
（目标地 + 所有房源 + 连线，浏览器打开即用）。

只依赖 Python 标准库。
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = "overseas-rental-ops/1.0 (personal student-housing helper; python-urllib)"
CACHE = os.path.join(os.path.expanduser("~"), ".overseas-rental", "geocache.json")
# 免费服务使用政策：Nominatim 要求 ≤1 req/s，这里统一节流
THROTTLE = 1.1
_last_call = [0.0]

GEOCODERS = [
    ("photon", "https://photon.komoot.io/api/?q={q}&limit=5"),
    ("nominatim", "https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=5&addressdetails=1"),
]


def _result_city(name, obj):
    """取出**真正的城市名**用于校验。

    必须只取城市字段，不能把 district/county 拼进来 ——
    否则会出现"Provincia di Trento"里含"Trento"、
    把 Rovereto 误判成 Trento 的致命误配（特伦托省下有 Rovereto 市）。
    """
    if name == "photon":
        p = obj.get("properties", {}) or {}
        for k in ("city", "town", "village", "municipality"):
            if p.get(k):
                return str(p[k]).strip()
        return ""
    a = obj.get("address") or {}
    for k in ("city", "town", "village", "municipality", "hamlet", "county"):
        if a.get(k):
            return str(a[k]).strip()
    return (obj.get("display_name") or "").split(",")[0].strip()


def _norm(s):
    return re.sub(r"[^a-zà-ÿ]", "", (s or "").lower())


def _city_match(city_text, expect):
    """城市匹配：相等，或城市名以预期名开头（Photon 偶尔带区名后缀）。

    刻意**不用子串包含**：省名/大区名里常含城市名（Provincia di Trento 含 Trento），
    包含判断会导致跨城误配。
    """
    if not expect:
        return True
    if not city_text:
        return False
    e, c = _norm(expect), _norm(city_text)
    if not e or not c:
        return False
    return c == e or c.startswith(e)


def _addr_variants(addr):
    """地址变体：原样 → 去掉门牌号 → 补 Italia。
    为什么要去门牌号：地理编码器在目标城市找不到精确门牌号时，
    会**退回匹配同名街道的其它城市**（实测 'Via Verdi 10, Trento' 被解析到
    25 公里外 Rovereto 的 Via Verdi）。去掉门牌号能避免这种"远距离误配"。"""
    out = [addr.strip()]
    head, _, tail = addr.partition(",")
    stripped = re.sub(r"\s+\d+\s*[a-zA-Z]?$", "", head).strip()
    if stripped and stripped != head.strip():
        out.append((stripped + "," + tail).strip().rstrip(","))
    low = addr.lower()
    if "italia" not in low and "italy" not in low:
        out.append(addr.strip() + ", Italia")
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v); uniq.append(v)
    return uniq
OSRM = "https://router.project-osrm.org/route/v1/{prof}/{coords}?overview=false"
OVERPASS = "https://overpass-api.de/api/interpreter"


# ── 网络：直连优先，失败才降级走代理 ─────────────────────────────
def _detect_proxy():
    try:
        p = urllib.request.getproxies()
    except Exception:  # noqa
        return ""
    return p.get("https") or p.get("http") or ""


def http_get(url, timeout=20, proxy=None, data=None, direct_only=False):
    """直连优先；直连失败才降级走代理。返回 (bytes, route_note)。

    重要：**HTTP 4xx/5xx 不降级。** 服务端明确拒绝（参数错、被封、限流）时，
    换出口解决不了问题，降级只是白等一次超时。只有网络类错误
    （超时 / 连接被重置 / SSL 失败）才值得换出口重试。
    """
    wait = THROTTLE - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()

    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode("utf-8")

    routes = [("direct", None)]
    if not direct_only and not proxy:
        p = _detect_proxy()
        if p:
            routes.append(("proxy", p))
    last_err = None
    for name, px in routes:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({} if name == "direct" else {"http": px, "https": px}))
        try:
            req = urllib.request.Request(url, headers=headers, data=body)
            with opener.open(req, timeout=timeout) as r:
                return r.read(), ("直连" if name == "direct" else "降级→代理 %s" % px)
        except urllib.error.HTTPError as e:
            # 服务端明确拒绝 —— 不重试、不降级
            raise RuntimeError("HTTP %s（服务端拒绝，不降级）" % e.code)
        except Exception as e:  # noqa
            last_err = "%s: %s" % (type(e).__name__, e)
    raise RuntimeError(last_err or "请求失败")


# ── 缓存 ────────────────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:  # noqa
            return {}
    return {}


def save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ── 地理编码 ────────────────────────────────────────────────────
def _guess_city(addr):
    """从地址末段猜城市（跳过含数字的段与国家名），用于给城市校验兜底。"""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    countries = {"italia", "italy", "italie", "germania", "germany", "france",
                 "spagna", "spain", "austria", "netherlands", "portogallo",
                 "portugal", "belgio", "belgium", "paesi bassi"}
    for p in reversed(parts):
        if re.search(r"\d", p):
            continue
        if _norm(p) in countries:
            continue
        if len(_norm(p)) >= 3:
            return p
    return ""


def geocode(addr, cache, expect_city=None, verbose=False):
    """地址 → (lat, lon, label, city_ok) 或 None。带缓存。

    三条纪律：
      1. **城市校验**：解析结果的城市必须与 expect_city 一致，否则只当"兜底结果"并标记
         city_ok=False。（实测防住的坑：'Via Verdi 10, Trento' 会被解析到 25 公里外
         Rovereto 的同名街道；且 Rovereto 所属省份叫"Provincia di Trento"，
         用子串包含判断会把它当成 Trento —— 所以只比对真正的城市字段。）
      2. 未显式给 expect_city 时，从地址末段自动推断，默认就带校验。
      3. **失败不缓存**：只有所有 geocoder 都答复过却查不到，才缓存 None。
         网络故障/服务端拒绝不写缓存，否则一次临时故障会被永久记住。
    """
    expect_city = expect_city or _guess_city(addr)
    key = "geo::%s::%s" % (addr.strip().lower(), (expect_city or "").lower())
    if key in cache:
        v = cache[key]
        if not v:
            return None
        return (v["lat"], v["lon"], v.get("label", addr), v.get("city_ok", True))

    answered = 0
    fallback = None          # 城市不匹配时的兜底结果
    for name, tpl in GEOCODERS:
        for variant in _addr_variants(addr):
            url = tpl.format(q=urllib.parse.quote(variant))
            try:
                raw, route = http_get(url)
            except Exception as e:  # 网络失败或服务端拒绝 —— 不写缓存
                if verbose:
                    print("    [地理编码] %s 失败：%s" % (name, str(e)[:70]))
                break            # 这个源不通，换下一个源
            answered += 1
            try:
                j = json.loads(raw.decode("utf-8", "ignore"))
            except Exception:  # noqa
                continue

            items = (j.get("features") or []) if name == "photon" else (j or [])

            for it in items:
                if name == "photon":
                    c = it["geometry"]["coordinates"]
                    lat, lon = c[1], c[0]
                    pr = it.get("properties", {}) or {}
                    label = ", ".join(x for x in [pr.get("name"), pr.get("street"),
                                                  pr.get("city")] if x) or variant
                else:
                    lat, lon = float(it["lat"]), float(it["lon"])
                    label = it.get("display_name", variant)
                city = _result_city(name, it)
                if _city_match(city, expect_city):
                    if verbose:
                        print("    [地理编码] %s 命中（%s）｜城市校验通过：%s"
                              % (name, route, city[:40]))
                    cache[key] = {"lat": lat, "lon": lon, "label": label, "city_ok": True}
                    return (lat, lon, label, True)
                if fallback is None:
                    fallback = (lat, lon, label, city)

    if fallback:
        lat, lon, label, city = fallback
        if verbose:
            print("    [地理编码] ⚠️ 只找到城市不匹配的结果：%s（期望 %s）" % (city[:44], expect_city))
        cache[key] = {"lat": lat, "lon": lon, "label": label, "city_ok": False}
        return (lat, lon, label, False)
    if answered:
        cache[key] = None
    return None


# ── 路线 ───────────────────────────────────────────────────────
PROFILES = {"foot": "步行", "bike": "骑行", "car": "驾车"}

# 公共 OSRM 实例只提供**汽车路网**：foot / bike profile 返回的是同一张图
# （实测 25 km "步行" 23 分钟 = 64 km/h，明显不对）。
# 所以：距离与驾车时长取自 OSRM，步行/骑行时长按标准速度换算，并标记为估算值。
SPEED_KMH = {"foot": 4.5, "bike": 15.0}


def _osrm(a, b, cache):
    """向 OSRM 取路网距离与驾车时长。返回 {"km","min"} 或 None。"""
    key = "osrm::%.5f,%.5f::%.5f,%.5f" % (a[0], a[1], b[0], b[1])
    if key in cache:
        return cache[key]
    coords = "%.5f,%.5f;%.5f,%.5f" % (a[1], a[0], b[1], b[0])  # OSRM 用 lon,lat
    url = OSRM.format(prof="driving", coords=coords)
    try:
        raw, _ = http_get(url)
        j = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:  # 网络失败 —— 不写缓存，下次重试
        return None
    if j.get("code") != "Ok" or not j.get("routes"):
        cache[key] = None          # 服务端明确答复"无路线" → 可以缓存
        return None
    r0 = j["routes"][0]
    val = {"km": r0["distance"] / 1000.0, "min": r0["duration"] / 60.0}
    cache[key] = val
    return val


def route_min(prof, a, b, cache):
    """返回 {"min","km"[,"est"]} 或 None。

    car  → OSRM 真实驾车时长
    foot/bike → 用路网距离按标准速度换算（est=True，表示是估算）
    """
    key = "rt::%s::%.5f,%.5f::%.5f,%.5f" % (prof, a[0], a[1], b[0], b[1])
    if key in cache:
        return cache[key]
    # 房源与目标地重合（同一点）→ 距离与时间都为 0；OSRM 对同点会返回"无路线"
    if abs(a[0] - b[0]) < 1e-5 and abs(a[1] - b[1]) < 1e-5:
        val = {"min": 0.0, "km": 0.0}
        cache[key] = val
        return val
    base = _osrm(a, b, cache)
    if not base:
        return None
    km = base["km"]
    if prof == "car":
        val = {"min": base["min"], "km": km}
    else:
        val = {"min": km / SPEED_KMH.get(prof, 4.5) * 60.0, "km": km, "est": True}
    cache[key] = val
    return val


# ── 最近公共交通站点（Overpass）────────────────────────────────
STOP_Q = ("[out:json][timeout:20];("
          "node(around:%d,%.5f,%.5f)[highway=bus_stop];"
          "node(around:%d,%.5f,%.5f)[railway=tram_stop];"
          "node(around:%d,%.5f,%.5f)[railway=station];"
          "node(around:%d,%.5f,%.5f)[railway=halt];"
          "node(around:%d,%.5f,%.5f)[public_transport=platform];"
          ");out center 40;")


def nearest_stop(lat, lon, cache, radius=900):
    """返回 (name, dist_m, kind)。找不到返回 None。"""
    key = "st::%.5f,%.5f::%d" % (lat, lon, radius)
    if key in cache:
        v = cache[key]
        return tuple(v) if v else None
    q = STOP_Q % ((radius, lat, lon) * 5)
    try:
        raw, _ = http_get(OVERPASS, data={"data": q}, timeout=30)
    except Exception:  # 网络失败 —— 不写缓存，下次重试
        return None
    try:
        j = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:  # noqa
        return None
    best = None
    for el in j.get("elements", []):
        slat = el.get("lat") or (el.get("center") or {}).get("lat")
        slon = el.get("lon") or (el.get("center") or {}).get("lon")
        if slat is None:
            continue
        d = haversine_m(lat, lon, slat, slon)
        if best is None or d < best[1]:
            tags = el.get("tags", {})
            nm = (tags.get("name") or tags.get("ref")
                  or {"bus_stop": "公交站", "tram_stop": "电车站",
                      "station": "火车站", "halt": "小站",
                      "platform": "站台"}.get(tags.get("railway")
                                              or tags.get("highway")
                                              or tags.get("public_transport"), "站点"))
            kind = ("rail" if tags.get("railway") in ("station", "halt", "tram_stop")
                    else "bus")
            best = (nm, d, kind)
    cache[key] = best
    return best


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def score(walk_min, bike_min, stop_dist_m):
    """通勤分（0–100，越高越好）。基于步行时间为主、站点距离为辅。"""
    base = None
    if walk_min is not None:
        w = walk_min
        base = 100 if w <= 15 else 80 if w <= 30 else 60 if w <= 45 else 40 if w <= 60 else 20
    elif bike_min is not None:
        b = bike_min
        base = 100 if b <= 10 else 85 if b <= 20 else 65 if b <= 30 else 45
    if base is None:
        return None
    adj = 0
    if stop_dist_m is not None:
        adj = 10 if stop_dist_m <= 300 else (0 if stop_dist_m <= 700 else -10)
    return max(0, min(100, base + adj))


# ── 子命令 ──────────────────────────────────────────────────────
def cmd_geocode(a):
    cache = load_cache()
    r = geocode(a.address, cache, expect_city=a.city, verbose=True)
    save_cache(cache)
    if not r:
        print("✗ 无法解析该地址：%s" % a.address)
        return 1
    print("✓ %s\n  → 纬度 %.5f  经度 %.5f\n  规范名：%s" % (a.address, r[0], r[1], r[2]))
    if r[3] is False:
        print("  ⚠️ 城市校验未通过 —— 该坐标不确定在「%s」，请人工确认地址写法后再用。" % a.city)
        return 1
    print("  城市校验：通过")
    return 0


def cmd_route(a):
    cache = load_cache()
    p1 = geocode(a.frm, cache, verbose=True)
    p2 = geocode(a.to, cache, verbose=True)
    if not p1 or not p2:
        print("✗ 起点或终点无法解析")
        save_cache(cache); return 1
    print("\n路线：%s → %s\n" % (a.frm, a.to))
    for prof in ("foot", "bike", "car"):
        r = route_min(prof, (p1[0], p1[1]), (p2[0], p2[1]), cache)
        if r:
            print("  %-4s %5.1f 分钟   %5.2f km" % (PROFILES[prof], r["min"], r["km"]))
        else:
            print("  %-4s 无路线" % PROFILES[prof])
    st = nearest_stop(p1[0], p1[1], cache)
    if st:
        print("\n  起点最近站点：%s（%.0f 米，%s）" % (st[0], st[1], "轨道" if st[2] == "rail" else "公交"))
    save_cache(cache)
    return 0


def cmd_enrich(a):
    if not a.to:
        print("!! 需要 --to <工作/学习地地址>"); return 2
    cache = load_cache()
    print("目标地（工作/学习）：%s" % a.to)
    dst = geocode(a.to, cache, expect_city=a.to_city, verbose=True)
    if not dst:
        print("✗ 目标地无法解析，先跑 geocode 确认地址写法")
        save_cache(cache); return 1
    if dst[3] is False:
        print("✗ 目标地城市校验未通过（期望 %s，实际 %s）—— 请改地址写法后重试"
              % (a.to_city, dst[2][:50]))
        save_cache(cache); return 1
    print("  → %.5f, %.5f（%s）｜城市校验通过\n" % (dst[0], dst[1], dst[2]))

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, address, city, cap, total_month FROM listings "
            "WHERE commute_to IS NULL OR commute_to <> ? ORDER BY id LIMIT ?",
            (a.to, a.limit)).fetchall()
    except sqlite3.OperationalError:
        con.close()
        print("!! 台账缺列，先跑一次 housing_db.py init 让它自动迁移"); return 2
    if not rows:
        con.close(); print("没有需要计算的房源。"); return 0

    done = miss = bad = 0
    for r in rows:
        addr = ", ".join(x for x in [r["address"], r["cap"], r["city"]] if x) or (r["title"] or "")
        if not addr:
            miss += 1; continue
        # 用房源自己的城市做校验，防"同名街道跨城误配"
        g = geocode(addr, cache, expect_city=r["city"])
        if not g:
            print("  · #%-4s %s → 地址无法解析，跳过" % (r["id"], addr[:44]))
            miss += 1; continue
        if g[3] is False:
            print("  · #%-4s %s → ⚠️ 解析到别处（%s），**跳过不写**，请人工核对地址"
                  % (r["id"], addr[:40], g[2][:36]))
            bad += 1; continue
        w = route_min("foot", (g[0], g[1]), (dst[0], dst[1]), cache)
        b = route_min("bike", (g[0], g[1]), (dst[0], dst[1]), cache)
        st = nearest_stop(g[0], g[1], cache)
        km = (w or b or {}).get("km")
        wk = w["min"] if w else None
        bk = b["min"] if b else None
        sd = st[1] if st else None
        sc = score(wk, bk, sd)
        con.execute("UPDATE listings SET lat=?,lon=?,commute_km=?,walk_min=?,bike_min=?,"
                    "stop_name=?,stop_dist_m=?,commute_score=?,commute_to=? WHERE id=?",
                    (g[0], g[1], km, wk, bk, (st[0] if st else None), sd, sc, a.to, r["id"]))
        done += 1
        print("  · #%-4s %-28s 步行%5s分 骑行%5s分 站点%5s米 分%5s" % (
            r["id"], (r["address"] or r["title"] or "")[:28],
            ("%.0f" % wk) if wk is not None else "-", ("%.0f" % bk) if bk is not None else "-",
            ("%.0f" % sd) if sd is not None else "-", ("%.0f" % sc) if sc is not None else "-"))
        save_cache(cache)
    con.commit()
    save_cache(cache)
    con.close()
    print("\n[完成] 写入 %d 条，地址解析失败 %d 条，城市校验不通过跳过 %d 条。" % (done, miss, bad))
    if bad:
        print("  ⚠️ 被跳过的那些是「解析到了别的城市」，宁可留空也不写错 —— 请人工核对地址。")
    print("⚠️  以上为 步行/骑行 时间与最近站点距离，**不含公交地铁的实际乘车耗时**。")
    print("    用于初筛排序；选定的房源请实地跑一趟通勤。")
    return 0


def cmd_show(a):
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id,title,address,city,total_month,commute_km,walk_min,bike_min,"
            "stop_name,stop_dist_m,commute_score,commute_to FROM listings "
            "WHERE commute_score IS NOT NULL OR commute_km IS NOT NULL "
            "ORDER BY commute_score DESC, walk_min ASC").fetchall()
    except sqlite3.OperationalError:
        con.close(); print("台账缺通勤列，先跑 commute.py enrich"); return 2
    con.close()
    if not rows:
        print("还没有通勤数据。先跑：commute.py enrich --db ... --to <地址>")
        return 0
    tgt = rows[0]["commute_to"]
    print("通勤排序（目标地：%s）" % tgt)
    print("%-4s %-28s %-7s %-7s %-7s %-6s %s" %
          ("ID", "地址/标题", "月总成本", "步行", "骑行", "分数", "最近站点"))
    print("-" * 96)
    for r in rows:
        print("%-4s %-28s %-7s %-7s %-7s %-6s %s" % (
            r["id"], ((r["address"] or r["title"] or ""))[:28],
            ("%g" % r["total_month"]) if r["total_month"] else "-",
            ("%.0f分" % r["walk_min"]) if r["walk_min"] is not None else "-",
            ("%.0f分" % r["bike_min"]) if r["bike_min"] is not None else "-",
            ("%.0f" % r["commute_score"]) if r["commute_score"] is not None else "-",
            ("%s %.0fm" % (r["stop_name"], r["stop_dist_m"])) if r["stop_name"] else "-"))
    print("\n提示：分数只反映 步行/骑行 便利度 + 站点远近，不含公交实际耗时。")
    if a.links:
        print("\n地图/导航链接（复制到浏览器打开；也可用 commute.py map 生成整张地图）：")
        for r in rows:
            addr = ", ".join(x for x in [r["address"], r["city"]] if x) or (r["title"] or "")
            print("  #%-4s %s" % (r["id"], (r["title"] or addr)[:34]))
            print("        %s" % addr_link(addr, tgt))
    else:
        print("加 --links 可输出每条房源的地图导航链接；用 map 子命令可生成整张地图。")
    return 0


# ── 地图连接器（"页面本身不给地图，我们补一个"）──────────────────
def coord_link(lat1, lon1, lat2, lon2):
    """房源 → 目标地 的**导航链接**（纯 URL 拼装，无需 API Key、不联网）。

    两个都返回：Google 地图（多数人手上就有）与 OpenStreetMap（不依赖商业服务）。
    """
    return {
        "google": ("https://www.google.com/maps/dir/?api=1"
                   "&origin=%s,%s&destination=%s,%s&travelmode=walking"
                   % (lat1, lon1, lat2, lon2)),
        "osm": ("https://www.openstreetmap.org/directions"
                "?engine=fossgis_osrm_foot&route=%s,%s;%s,%s"
                % (lat1, lon1, lat2, lon2)),
    }


def addr_link(addr, to, mode="walking"):
    """按**地址文本**生成导航链接（不需要坐标，适合列表页直接给）。"""
    return ("https://www.google.com/maps/dir/?api=1&origin=%s&destination=%s&travelmode=%s"
            % (urllib.parse.quote(addr or ""), urllib.parse.quote(to or ""), mode))


MAP_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
 body{margin:0;font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1a1a1a}
 #wrap{display:flex;height:100vh}
 #side{width:360px;flex:none;overflow:auto;background:#fff;border-right:1px solid #e5e7eb;padding:14px}
 #map{flex:1;min-width:0;background:#eef1f4}
 h1{font-size:16px;margin:0 0 4px}
 .sub{color:#6b7280;font-size:12px;margin-bottom:8px;word-break:break-all}
 .legend{font-size:12px;color:#6b7280;margin:6px 0 12px}
 .item{border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px;margin-bottom:8px;cursor:pointer}
 .item:hover{background:#f0f6ff;border-color:#bfdbfe}
 .item b{font-size:13px}
 .m{color:#4b5563;font-size:12px;margin-top:2px}
 .badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;color:#fff;margin-left:4px}
 a{color:#2563eb;text-decoration:none}
 .foot{margin-top:14px;font-size:11px;color:#9ca3af}
 .note{padding:18px;font-size:13px;color:#374151}
</style>
</head>
<body>
<div id="wrap">
  <div id="side">
    <h1>通勤地图</h1>
    <div class="sub">目标地（工作/学习）：__TO__<br>共 __N__ 条房源，按通勤便利度排序</div>
    <div class="legend">&#128309; 目标地　&#128994; 步行≤15分　&#128992; 步行≤35分　&#9898; 更远</div>
    <div id="list"></div>
    <div class="foot">时间为步行/骑行估算，不含公交地铁实际乘车耗时。选定的房源请实地跑一趟。</div>
  </div>
  <div id="map"><div class="note" id="boot">正在加载地图…</div></div>
</div>
<script>
var TARGET = __TARGET__;
var ITEMS = __ITEMS__;
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function fmt(v){return (v==null)?'?':Math.round(v)+'分';}
function color(sc,wk){
  if(wk!=null&&wk<=15)return '#16a34a';
  if(wk!=null&&wk<=35)return '#f59e0b';
  return '#9ca3af';
}
function buildList(){
  var list=document.getElementById('list');
  var sorted=ITEMS.slice().sort(function(a,b){
    var d=(b.score==null?-1:b.score)-(a.score==null?-1:a.score);return d;});
  sorted.forEach(function(it){
    var c=color(it.score,it.walk);
    var d=document.createElement('div');d.className='item';
    d.innerHTML='<b>'+esc(it.title)+'</b>'+
      '<span class="badge" style="background:'+c+'">'+fmt(it.walk)+'</span>'+
      '<div class="m">'+esc(it.addr)+'</div>'+
      '<div class="m">月总成本 &euro;'+(it.cost==null?'?':it.cost)+
        '　骑行 '+fmt(it.bike)+(it.stop?'　站点 '+Math.round(it.stopm)+'m':'')+'</div>'+
      (it.gmap?'<div class="m"><a href="'+it.gmap+'" target="_blank">地图导航 &#8594;</a></div>':'');
    d.onclick=function(){ if(window.__mks&&window.__mks[it._i]){
      window.__map.setView([it.lat,it.lon],16);window.__mks[it._i].openPopup();}};
    list.appendChild(d);
  });
}
function init(){
  var boot=document.getElementById('boot'); if(boot)boot.remove();
  var map=L.map('map'); window.__map=map;
  // 瓦片源多路兜底。实测（国内直连）：osm.de / osm.fr-hot / Esri 可用且返回真图；
  // 官方 osm.org 直连常超时；CartoDB 已改为需 API Key（回一张 "API KEY REQUIRED" 水印）——故不采用。
  var TILES=[
    {u:"https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png",a:"&copy; OpenStreetMap",s:"abc"},
    {u:"https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",a:"&copy; OpenStreetMap France",s:"abc"},
    {u:"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",a:"&copy; OpenStreetMap",s:"abc"},
    {u:"https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
     a:"Tiles &copy; Esri",s:null}
  ];
  var ti=0,errs=0,cur=null;
  function addTiles(){
    var t=TILES[ti];
    var opt={maxZoom:19,attribution:t.a};
    if(t.s)opt.subdomains=t.s;
    var ly=L.tileLayer(t.u,opt);
    ly.on('tileerror',function(){
      errs++;
      if(errs>=4&&ti<TILES.length-1){ti++;errs=0;map.removeLayer(ly);cur=addTiles();}
    });
    ly.addTo(map);return ly;
  }
  cur=addTiles();
  var bounds=[],tLL=null,mks=[]; window.__mks=mks;
  if(TARGET&&TARGET.lat!=null){
    tLL=[TARGET.lat,TARGET.lon];bounds.push(tLL);
    L.circleMarker(tLL,{radius:10,color:'#fff',weight:3,fillColor:'#2563eb',fillOpacity:1})
     .addTo(map).bindPopup('<b>目标地（工作/学习）</b><br>'+esc(TARGET.label));
  }
  ITEMS.forEach(function(it,i){
    it._i=i;
    var ll=[it.lat,it.lon],c=color(it.score,it.walk);bounds.push(ll);
    if(tLL)L.polyline([tLL,ll],{color:c,weight:1.5,opacity:.5,dashArray:'5 5'}).addTo(map);
    var mk=L.circleMarker(ll,{radius:7,color:'#fff',weight:2,fillColor:c,fillOpacity:1}).addTo(map);
    mk.bindPopup('<b>'+esc(it.title)+'</b><br>'+esc(it.addr)+
      '<br>月总成本：&euro;'+(it.cost==null?'?':it.cost)+
      '<br>步行 '+fmt(it.walk)+'　骑行 '+fmt(it.bike)+
      (it.stop?'<br>最近站点：'+esc(it.stop)+' '+Math.round(it.stopm)+' m':'')+
      (it.gmap?'<br><a href="'+it.gmap+'" target="_blank">Google 地图导航 &#8594;</a>':'')+
      (it.osm?'　<a href="'+it.osm+'" target="_blank">OSM</a>':''));
    mks.push(mk);
  });
  if(bounds.length>1)map.fitBounds(bounds,{padding:[40,40]});
  else if(bounds.length===1)map.setView(bounds[0],14);
  else map.setView([46.07,11.12],12);
}
buildList();
// Leaflet 多 CDN 兜底：国内外网络都能开（unpkg → jsdelivr → bootcdn）
(function(){
  var BASES=[
    "https://unpkg.com/leaflet@1.9.4/dist/",
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/",
    "https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/"
  ];
  function css(b){var l=document.createElement('link');l.rel='stylesheet';l.href=b+'leaflet.css';document.head.appendChild(l);}
  function js(i){
    if(i>=BASES.length){
      var m=document.getElementById('map');
      m.innerHTML='<div class="note">地图库加载失败（当前网络受限）。<br>'+
        '可以直接把左侧房源地址复制到手机地图 App 里搜 —— 距离与时间在左栏已给出。</div>';
      return;
    }
    var s=document.createElement('script');
    s.src=BASES[i]+'leaflet.js';
    s.onload=function(){css(BASES[i]);try{init();}catch(e){
      var m=document.getElementById('map');m.innerHTML='<div class="note">地图初始化失败：'+esc(e.message)+'</div>';}};
    s.onerror=function(){js(i+1);};
    document.head.appendChild(s);
  }
  js(0);
})();
</script>
</body></html>
"""


def cmd_map(a):
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id,title,address,city,cap,total_month,rent,lat,lon,commute_km,"
            "walk_min,bike_min,stop_name,stop_dist_m,commute_score,commute_to "
            "FROM listings WHERE lat IS NOT NULL AND lon IS NOT NULL "
            "ORDER BY (commute_score IS NULL), commute_score DESC").fetchall()
    except sqlite3.OperationalError:
        con.close()
        print("!! 台账缺通勤列，先跑一次 commute.py enrich 让它写入坐标"); return 2
    con.close()
    if not rows:
        print("没有已算出坐标的房源。先跑：commute.py enrich --db ... --to <地址>")
        return 0

    to_addr = rows[0]["commute_to"] or a.to or ""
    cache = load_cache()
    dst = None
    if to_addr:
        g = geocode(to_addr, cache, expect_city=a.to_city or _guess_city(to_addr), verbose=True)
        if g:
            dst = {"lat": g[0], "lon": g[1], "label": g[2]}
            save_cache(cache)
        else:
            print("!! 目标地无法定位：%s（地图仍会生成，但不画连线）" % to_addr)

    items = []
    for r in rows:
        link = coord_link(r["lat"], r["lon"], dst["lat"], dst["lon"]) if dst else {}
        cost = r["total_month"] if r["total_month"] is not None else r["rent"]
        items.append({
            "title": r["title"] or r["address"] or ("#%s" % r["id"]),
            "addr": ", ".join(x for x in [r["address"], r["cap"], r["city"]] if x) or "",
            "lat": r["lat"], "lon": r["lon"],
            "cost": cost, "walk": r["walk_min"], "bike": r["bike_min"],
            "stop": r["stop_name"], "stopm": r["stop_dist_m"],
            "score": r["commute_score"],
            "gmap": link.get("google", ""), "osm": link.get("osm", ""),
        })

    html = (MAP_HTML
            .replace("__TITLE__", "通勤地图 · %s" % (to_addr or "房源"))
            .replace("__TO__", to_addr or "（未设）")
            .replace("__N__", str(len(items)))
            .replace("__TARGET__", json.dumps(dst, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__ITEMS__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/")))
    out = a.out or "commute_map.html"
    open(out, "w", encoding="utf-8").write(html)
    print("[已生成] %s（%d 条房源）" % (out, len(items)))
    print("用浏览器打开即可：目标地一个蓝点、每条房源一个点，虚线连到目标地；点左侧条目会跳到该房源。")
    print("⚠️  打开时需要联网（地图瓦片与 Leaflet 来自 CDN）。地图数据 © OpenStreetMap 贡献者。")
    return 0


def cmd_cache(a):
    if a.clear:
        if os.path.exists(CACHE):
            os.remove(CACHE)
            print("[已清空] %s" % CACHE)
        else:
            print("缓存本来就不存在")
        return 0
    c = load_cache()
    print("缓存文件：%s" % CACHE)
    print("条目数：%d" % len(c))
    return 0


def main():
    p = argparse.ArgumentParser(description="通勤计算：房源 → 工作/学习地的距离与时间")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("geocode", help="地址 → 经纬度（带城市校验）")
    s1.add_argument("--address", required=True)
    s1.add_argument("--city", default="", help="预期城市，用于校验（强烈建议给，防同名街道跨城误配）")
    s1.set_defaults(func=cmd_geocode)

    s2 = sub.add_parser("route", help="两点之间的步行/骑行/驾车耗时")
    s2.add_argument("--from", dest="frm", required=True)
    s2.add_argument("--to", required=True)
    s2.set_defaults(func=cmd_route)

    s3 = sub.add_parser("enrich", help="给台账里的房源批量算通勤并写回")
    s3.add_argument("--db", default=os.environ.get("RENTAL_DB")
                    or os.path.join(os.path.expanduser("~"), ".overseas-rental", "housing.db"))
    s3.add_argument("--to", required=True, help="工作/学习地地址（越具体越准）")
    s3.add_argument("--to-city", dest="to_city", default="", help="目标地所在城市（用于校验）")
    s3.add_argument("--limit", type=int, default=30)
    s3.set_defaults(func=cmd_enrich)

    s4 = sub.add_parser("show", help="按通勤分排序列出")
    s4.add_argument("--db", default=os.environ.get("RENTAL_DB")
                    or os.path.join(os.path.expanduser("~"), ".overseas-rental", "housing.db"))
    s4.add_argument("--links", action="store_true", help="额外输出每条房源的地图导航链接")
    s4.set_defaults(func=cmd_show)

    s6 = sub.add_parser("map", help="生成整张通勤地图（自包含 HTML，浏览器打开）")
    s6.add_argument("--db", default=os.environ.get("RENTAL_DB")
                    or os.path.join(os.path.expanduser("~"), ".overseas-rental", "housing.db"))
    s6.add_argument("--to", default="", help="目标地地址（不填则用台账里记录的 commute_to）")
    s6.add_argument("--to-city", dest="to_city", default="", help="目标地城市（用于校验）")
    s6.add_argument("--out", default="commute_map.html")
    s6.set_defaults(func=cmd_map)

    s5 = sub.add_parser("cache", help="查看/清空地理编码缓存")
    s5.add_argument("--clear", action="store_true")
    s5.set_defaults(func=cmd_cache)

    a = p.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
