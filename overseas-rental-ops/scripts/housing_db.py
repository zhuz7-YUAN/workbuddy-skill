#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
housing_db.py —— 找房台账（SQLite 单文件）
解决的核心问题：同一条房源不要重复问、重复谈；每一轮的进度有据可查。

用法（--db 省略时用 ./rental/housing.db）：
  housing_db.py init
  housing_db.py import listings.json          # 从核验产出的 JSON 批量导入/更新
  housing_db.py list [--verdict direct|inquiry|excluded|unverified]
  housing_db.py contact --listing 12 --channel email --target a@b.com \
                        --questions "1,2,3,4,5,6,7" [--note "..."]
  housing_db.py reply --contact 3 --outcome available --summary "可租，接受4.5个月" \
                      [--next-action "约看房" --next-due 2026-10-01]
  housing_db.py due [--hours 48]              # 该追的（发过问询、超时未回）
  housing_db.py asked                         # 已经问过的房源（防止重复问）
  housing_db.py fresh                         # 还没问过的候选（该去问的）
  housing_db.py report                        # 汇总
"""
import argparse, json, os, sqlite3, sys, datetime


def resolve_db(explicit=None):
    """决定台账位置，避免"换个目录跑就换了台账"。

    优先级：--db 显式指定 > 环境变量 RENTAL_DB > 当前目录 ./rental/housing.db（若已存在）
           > ~/.overseas-rental/housing.db（稳定默认，不随当前目录漂移）
    脚本每次都会打印实际使用的路径。
    """
    if explicit:
        return explicit
    env = os.environ.get("RENTAL_DB")
    if env:
        return env
    local = os.path.join(os.getcwd(), "rental", "housing.db")
    if os.path.exists(local):
        return local
    return os.path.join(os.path.expanduser("~"), ".overseas-rental", "housing.db")


DEFAULT_DB = resolve_db()   # 仅为兼容旧引用保留；实际以 resolve_db() 为准

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,          -- operauni / subito / facebook / agency / ...
  external_id   TEXT NOT NULL,
  url           TEXT,
  title         TEXT,
  city          TEXT,
  cap           TEXT,
  address       TEXT,
  rent          REAL,
  extra_fees    REAL,
  total_month   REAL,
  room_type     TEXT,
  gender        TEXT,                   -- female / male / any
  status        TEXT,                   -- libera / occupata / unknown
  free_from     TEXT,                   -- YYYY-MM-DD
  vacant_months REAL,
  min_stay_months REAL,
  deposit       TEXT,
  contract_type TEXT,
  posted_at     TEXT,                   -- YYYY-MM-DD HH:MM  (C2C 帖子发布时间)
  hot_comments  INTEGER DEFAULT 0,      -- 评论区"已私信"条数
  first_seen    TEXT,
  last_verified TEXT,
  verdict       TEXT,                   -- direct / inquiry / excluded / unverified
  flags         TEXT,                   -- JSON 数组
  notes         TEXT,
  UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS contacts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  channel     TEXT,                     -- email / board_form / site_msg / phone / dm
  target      TEXT,                     -- 邮箱 / 电话 / 链接
  sent_at     TEXT,
  questions   TEXT,                     -- 这一轮问了哪几项
  reply_at    TEXT,
  outcome     TEXT,                     -- pending / available / unavailable / declined / no_response / negotiating
  summary     TEXT,
  next_action TEXT,
  next_due    TEXT
);
CREATE TABLE IF NOT EXISTS prep (
  key        TEXT PRIMARY KEY,
  done       INTEGER DEFAULT 0,
  value      TEXT,
  updated_at TEXT
);
"""


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def connect(db):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


# 后加的列（老台账自动补列，不丢数据）
MIGRATIONS = [
    ("listings", "lat", "REAL"),
    ("listings", "lon", "REAL"),
    ("listings", "commute_km", "REAL"),
    ("listings", "walk_min", "REAL"),
    ("listings", "bike_min", "REAL"),
    ("listings", "stop_name", "TEXT"),
    ("listings", "stop_dist_m", "REAL"),
    ("listings", "commute_score", "REAL"),
    ("listings", "commute_to", "TEXT"),
]


def _migrate(con):
    """给已存在的表补列。CREATE TABLE IF NOT EXISTS 不会改老表结构，所以必须显式迁移。"""
    for table, col, typ in MIGRATIONS:
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
            if cols and col not in cols:
                con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
        except sqlite3.OperationalError:
            pass
    con.commit()


def cmd_init(a):
    con = connect(a.db); con.close()
    print("[OK] 台账已就绪：%s" % a.db)


def cmd_import(a):
    data = json.load(open(a.file, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("listings", [])
    con = connect(a.db)
    ins = upd = 0
    for it in data:
        src = it.get("source") or "unknown"
        ext = str(it.get("external_id") or it.get("id") or it.get("url") or "")
        if not ext:
            continue
        cols = ["source", "external_id", "url", "title", "city", "cap", "address",
                "rent", "extra_fees", "total_month", "room_type", "gender", "status",
                "free_from", "min_stay_months", "deposit", "contract_type",
                "posted_at", "hot_comments", "notes"]
        row = con.execute("select id from listings where source=? and external_id=?", (src, ext)).fetchone()
        vals = [it.get(c) for c in cols]
        vals[0] = src   # source 兜底 "unknown"
        vals[1] = ext   # external_id 兜底 url/id（缺字段不应 NOT NULL 崩溃）
        if row:
            con.execute("update listings set " + ",".join(c + "=?" for c in cols[2:]) + " where id=?",
                        vals[2:] + [row["id"]])
            upd += 1
        else:
            con.execute("insert into listings (%s, first_seen, last_verified) values (%s,?,?)"
                        % (",".join(cols), ",".join("?" * len(cols))),
                        vals + [now(), now()])
            ins += 1
    con.commit(); con.close()
    print("[OK] 新增 %d 条，更新 %d 条" % (ins, upd))


def _fmt(it):
    return "#%-4s %-9s %-26s %-10s %-9s %s" % (
        it["id"], it["verdict"] or "-", (it["title"] or it["url"] or "")[:25],
        ("%s %s" % (it["city"] or "?", it["cap"] or "")).strip()[:9] or "-",
        ("€%s" % (it["total_month"] or it["rent"] or "?"))[:8],
        it["flags"] or "")


def cmd_list(a):
    con = connect(a.db)
    q = "select * from listings"
    p = []
    if a.verdict:
        q += " where verdict=?"; p.append(a.verdict)
    q += " order by case verdict when 'direct' then 0 when 'inquiry' then 1 when 'unverified' then 2 else 3 end, id desc"
    rows = con.execute(q, p).fetchall()
    if not rows:
        print("(无记录)"); return
    for r in rows:
        print(_fmt(r))
    print("\n共 %d 条" % len(rows))


def cmd_contact(a):
    con = connect(a.db)
    r = con.execute("select id, verdict from listings where id=?", (a.listing,)).fetchone()
    if not r:
        print("!! 找不到房源 #%s" % a.listing); sys.exit(1)
    con.execute("insert into contacts (listing_id,channel,target,sent_at,questions,outcome) "
                "values (?,?,?,?,?,'pending')",
                (a.listing, a.channel, a.target, now(), a.questions))
    cid = con.execute("select last_insert_rowid() as i").fetchone()["i"]
    if a.note:
        con.execute("update listings set notes=coalesce(notes,'')||? where id=?", (a.note, a.listing))
    con.commit(); con.close()
    print("[OK] 已记一笔问询 #%s：房源 #%s via %s -> %s" % (cid, a.listing, a.channel, a.target))


def cmd_reply(a):
    con = connect(a.db)
    con.execute("update contacts set reply_at=?, outcome=?, summary=?, "
                "next_action=coalesce(?,next_action), next_due=coalesce(?,next_due) where id=?",
                (now(), a.outcome, a.summary, a.next_action, a.next_due, a.contact))
    c = con.execute("select listing_id from contacts where id=?", (a.contact,)).fetchone()
    if c:
        v = {"available": "direct", "negotiating": "inquiry",
             "unavailable": "excluded", "declined": "excluded",
             "no_response": "excluded"}.get(a.outcome)
        if v:
            con.execute("update listings set verdict=? where id=?", (v, c["listing_id"]))
    con.commit(); con.close()
    print("[OK] 已记录回复 #%s：%s" % (a.contact, a.outcome))


def cmd_due(a):
    con = connect(a.db)
    cut = (datetime.datetime.now() - datetime.timedelta(hours=a.hours)).strftime("%Y-%m-%d %H:%M")
    rows = con.execute(
        "select c.*, l.title, l.url from contacts c join listings l on l.id=c.listing_id "
        "where c.outcome='pending' and c.sent_at < ? order by c.sent_at", (cut,)).fetchall()
    if not rows:
        print("(没有该追的)"); return
    for r in rows:
        print("#%s 房源#%s  %s 发信于 %s  <%s>" % (r["id"], r["listing_id"],
              (r["title"] or r["url"] or "")[:30], r["sent_at"], r["target"]))
    print("\n共 %d 条待追（超过 %d 小时未回）" % (len(rows), a.hours))


def cmd_asked(a):
    con = connect(a.db)
    rows = con.execute(
        "select l.id, l.title, l.url, count(c.id) n, max(c.sent_at) last "
        "from listings l join contacts c on c.listing_id=l.id group by l.id order by last desc").fetchall()
    if not rows:
        print("(还没问过任何房源)"); return
    for r in rows:
        print("房源#%s  问过 %s 轮，最近 %s  %s" % (r["id"], r["n"], r["last"], (r["title"] or r["url"] or "")[:32]))


def cmd_fresh(a):
    con = connect(a.db)
    rows = con.execute(
        "select * from listings where verdict in ('direct','inquiry') and id not in "
        "(select listing_id from contacts) order by id").fetchall()
    if not rows:
        print("(没有待问的)"); return
    for r in rows:
        print(_fmt(r))
    print("\n共 %d 条待问" % len(rows))


def cmd_report(a):
    con = connect(a.db)
    def one(sql, *p):
        return con.execute(sql, p).fetchone()[0]
    print("=== 找房台账汇总 ===")
    print("房源总数        : %d" % one("select count(*) from listings"))
    for v in ("direct", "inquiry", "unverified", "excluded"):
        print("  %-12s: %d" % (v, one("select count(*) from listings where verdict=?", v)))
    print("问询记录        : %d" % one("select count(*) from contacts"))
    for o in ("pending", "available", "negotiating", "unavailable", "declined", "no_response"):
        n = one("select count(*) from contacts where outcome=?", o)
        if n:
            print("  %-12s: %d" % (o, n))
    print("待跟进（>48h）  : %d" % one(
        "select count(*) from contacts where outcome='pending' and sent_at < ?",
        (datetime.datetime.now() - datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")))
    d = one("select count(*) from prep where done=1")
    t = one("select count(*) from prep")
    print("前置准备完成    : %d/%d" % (d, t))
    con.close()


def main():
    p = argparse.ArgumentParser(description="找房台账")
    p.add_argument("--db", default=None,
                   help="SQLite 路径。不给则：环境变量 RENTAL_DB > ./rental/housing.db（若存在）> ~/.overseas-rental/housing.db")
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("init").set_defaults(f=cmd_init)

    s = sp.add_parser("import"); s.add_argument("file"); s.set_defaults(f=cmd_import)

    s = sp.add_parser("list"); s.add_argument("--verdict"); s.set_defaults(f=cmd_list)

    s = sp.add_parser("contact")
    s.add_argument("--listing", required=True); s.add_argument("--channel", required=True)
    s.add_argument("--target", required=True); s.add_argument("--questions", default="")
    s.add_argument("--note"); s.set_defaults(f=cmd_contact)

    s = sp.add_parser("reply")
    s.add_argument("--contact", required=True)
    s.add_argument("--outcome", required=True,
                   choices=["pending", "available", "negotiating", "unavailable", "declined", "no_response"])
    s.add_argument("--summary", default=""); s.add_argument("--next-action"); s.add_argument("--next-due")
    s.set_defaults(f=cmd_reply)

    s = sp.add_parser("due"); s.add_argument("--hours", type=int, default=48); s.set_defaults(f=cmd_due)
    sp.add_parser("asked").set_defaults(f=cmd_asked)
    sp.add_parser("fresh").set_defaults(f=cmd_fresh)
    sp.add_parser("report").set_defaults(f=cmd_report)

    a = p.parse_args()
    a.db = resolve_db(a.db)
    a.f(a)


if __name__ == "__main__":
    main()
