#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
extract_example_operauni.py —— 参考提取器：把已保存的详情页 HTML 转成标准 listings.json
（这是"抓取层"的样板。别的站点照这个套路写一个 extract_<site>.py 即可。）

用法：
  extract_example_operauni.py --html-dir ./_raw_html --source operauni --out listings.json

输出 JSON 每条形如：
  { "source":"operauni", "external_id":"chizzola", "url":"...",
    "title":"...", "address":"...", "cap":"38123", "city":"Trento",
    "rent":240, "extra_fees":60, "room_type":"Stanza singola",
    "gender":"female", "status":"libera", "free_from":"2026-09-01",
    "min_stay_months":12, "deposit":"240 per stanza", "contract_type":"annuale" }

注意：一个公寓页面可能有多间房。本脚本按"每间空着的房"各出一条记录，
      external_id 用 <slug>#<房间序号>，避免互相覆盖。
"""
import argparse, json, os, re, sys

GENDER_MAP = {"femminile": "female", "maschile": "male", "misto": "any"}


def clean_html(t):
    t = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = re.sub(r"&nbsp;|&#\d+;", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def it_num(s):
    """解析意大利格式数字：'120,00'->120.0  '1.020'->1020.0  '80'->80.0"""
    if s is None:
        return None
    s = str(s).strip()
    m = re.search(r"[\d.,]+", s)
    if not m:
        return None
    t = m.group(0)
    if "." in t and "," in t:           # 1.020,50 -> 1020.50
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                      # 120,00 -> 120.00
        t = t.replace(",", ".")
    elif "." in t:
        parts = t.split(".")
        # 点后正好 3 位且没有别的点 -> 千分位
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def field(txt, label, n=40):
    m = re.search(re.escape(label) + r":\s*\n\s*([^\n]{0,80})", txt)
    return m.group(1).strip()[:n] if m else None


def to_months(s):
    if not s:
        return None
    s = s.lower()
    m = re.search(r"(\d+)\s*mes", s)
    if m:
        return float(m.group(1))
    if "anno" in s or "annual" in s:
        return 12.0
    m = re.search(r"(\d+)\s*ann", s)
    if m:
        return float(m.group(1)) * 12
    return None


def parse(path, source):
    raw = open(path, encoding="utf-8", errors="replace").read()
    txt = clean_html(raw)
    slug = re.sub(r"\.html?$", "", os.path.basename(path))
    url = None
    m = re.search(r"https?://trent\.operauni\.tn\.it/appartamenti/[^\s\"'<>]+", raw)
    if m:
        url = m.group(0)

    addr = re.search(r"((?:Via|Viale|Piazza|Corso|Localita|Località|Loc\.)[^\n]{2,60}?-\s*(\d{5})\s*-\s*([A-Za-zÀ-ÿ]{2,20}))", txt)
    address = addr.group(1).strip() if addr else None
    cap = addr.group(2) if addr else None
    city = addr.group(3).strip() if addr else None

    extra = field(txt, "Spese extra", 20)
    extra_fees = it_num(extra)
    min_stay = field(txt, "Permanenza minima", 30)
    deposit = field(txt, "Cauzione", 20)
    contract = field(txt, "Tipo contratto", 80)

    # 房间块：房间名 -> Stato -> Libera da -> 价格
    out = []
    blocks = re.split(r"\n\s*Camere\s*\n", txt)[-1]
    pat = re.compile(
        r"\n\s*(?P<name>[A-Z][^\n]{3,50})\s*\n"
        r"\s*Stato:\s*\n\s*(?P<stato>Libera|Occupata)\s*\n"
        r"\s*Libera da:\s*\n\s*(?P<from>[^\n]{0,12})\s*\n"
        r"\s*(?P<price>\d{2,4})\s*€")
    for i, m in enumerate(pat.finditer(blocks)):
        name = m.group("name").strip()
        st = m.group("stato").strip().lower()
        gender = "any"
        for k, v in GENDER_MAP.items():
            if k in name.lower():
                gender = v
        out.append(dict(
            source=source,
            external_id="%s#%d" % (slug, i + 1),
            url=url or path,
            title="%s - %s" % (slug, name),
            address=address, cap=cap, city=city,
            room_type=name,
            gender=gender,
            status="libera" if st == "libera" else "occupata",
            free_from=(m.group("from").strip() or None),
            rent=float(m.group("price")),
            extra_fees=extra_fees,
            total_month=(float(m.group("price")) + (extra_fees or 0)),
            min_stay_months=to_months(min_stay),
            deposit=deposit,
            contract_type=contract,
        ))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--html-dir", required=True)
    p.add_argument("--source", default="operauni")
    p.add_argument("--out", default="listings.json")
    p.add_argument("--only-libera", action="store_true", help="只输出标 Libera 的房间")
    a = p.parse_args()

    files = [os.path.join(a.html_dir, f) for f in sorted(os.listdir(a.html_dir))
             if f.lower().endswith((".html", ".htm"))]
    if not files:
        print("!! %s 里没有 html 文件" % a.html_dir); sys.exit(1)

    all_rows = []
    for f in files:
        try:
            all_rows += parse(f, a.source)
        except Exception as e:
            print("  跳过 %s：%s" % (os.path.basename(f), e))
    if a.only_libera:
        all_rows = [r for r in all_rows if r["status"] == "libera"]

    json.dump({"listings": all_rows}, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("解析 %d 个页面 -> %d 条房间记录 -> %s" % (len(files), len(all_rows), a.out))
    for r in all_rows:
        print("  %-22s %-13s %-10s %-6s %s" % (
            r["external_id"], r["title"][:12], r["free_from"] or "?",
            r["status"], "%s %s / €%s" % (r["city"] or "?", r["cap"] or "", r["rent"])))


if __name__ == "__main__":
    main()
