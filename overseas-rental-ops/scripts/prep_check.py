#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
prep_check.py —— 前置准备门禁
把"到了那一步才发现没做的准备工作"提前暴露出来。

用法：
  prep_check.py                       # 看当前进度 + 下一步该补什么
  prep_check.py --stage before_signing   # 列出该阶段必办项（含此前所有阶段）
  prep_check.py --mark codice_fiscale done
  prep_check.py --due                 # 只列"现在就该办、还没办"的项
  prep_check.py --db /path/rental/housing.db

退出码：0 = 本阶段无阻塞项未完成；1 = 有 blocking 项没做完（会卡住下一步）
"""
import argparse, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKLIST = os.path.join(HERE, "..", "assets", "checklist.json")
STAGE_ORDER = ["now", "before_search", "before_viewing", "before_signing", "after_moving"]


def load():
    with open(CHECKLIST, encoding="utf-8") as f:
        return json.load(f)


def resolve_db(explicit=None):
    """与 housing_db.py 保持同一套规则，确保两个脚本永远指向同一个台账。

    优先级：--db > 环境变量 RENTAL_DB > ./rental/housing.db（若存在）> ~/.overseas-rental/housing.db
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


def db_path(a):
    return resolve_db(a.db)


def load_prep(db):
    if not os.path.exists(db):
        return {}
    con = sqlite3.connect(db)
    try:
        return {r[0]: r[1] for r in con.execute("select key, done from prep")}
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def mark(db, key, done):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS prep (key TEXT PRIMARY KEY, done INTEGER DEFAULT 0, value TEXT, updated_at TEXT)")
    con.execute("insert into prep (key,done,updated_at) values (?,?,datetime('now')) "
                "on conflict(key) do update set done=excluded.done, updated_at=excluded.updated_at",
                (key, 1 if done else 0))
    con.commit(); con.close()


def show(items, stages, done_map, only_stage=None, only_due=False):
    st_name = {s["id"]: s["name"] for s in stages}
    blocking_open = []
    for sid in STAGE_ORDER:
        if only_stage and STAGE_ORDER.index(sid) > STAGE_ORDER.index(only_stage):
            continue
        rows = [i for i in items if i["stage"] == sid]
        if not rows:
            continue
        pend = [r for r in rows if not done_map.get(r["id"])]
        if only_due and not pend:
            continue
        print("\n" + "=" * 76)
        print("%s   [%d/%d 已完成]" % (st_name.get(sid, sid), len(rows) - len(pend), len(rows)))
        print("=" * 76)
        for r in rows:
            ok = done_map.get(r["id"])
            if only_due and ok:
                continue
            mark_ = "✅" if ok else ("⛔" if r.get("blocking") else "⬜")
            print("\n%s %s  (%s%s)" % (mark_, r["title"], sid,
                  "，耗时约 %s" % r["lead_time"] if r.get("lead_time") else ""))
            print("    为什么：%s" % r["why"])
            print("    怎么做：%s" % r["how"])
            if not ok and r.get("blocking"):
                blocking_open.append(r)
    return blocking_open


def main():
    p = argparse.ArgumentParser(description="前置准备门禁")
    p.add_argument("--db")
    p.add_argument("--stage", choices=STAGE_ORDER)
    p.add_argument("--mark")
    p.add_argument("--undo", action="store_true")
    p.add_argument("--due", action="store_true", help="只列现在就该办、还没办的")
    a = p.parse_args()

    data = load(); items = data["items"]; stages = data["stages"]
    db = db_path(a)

    if a.mark:
        if a.mark not in {i["id"] for i in items}:
            print("!! 没有这一项：%s" % a.mark)
            print("   可选：" + ", ".join(i["id"] for i in items)); sys.exit(1)
        mark(db, a.mark, not a.undo)
        print("[OK] %s -> %s" % (a.mark, "未完成" if a.undo else "已完成"))
        return

    done_map = load_prep(db)
    print("台账：%s" % db)
    print("总进度：%d/%d 项已完成" % (sum(1 for i in items if done_map.get(i["id"])), len(items)))

    if a.due:
        blk = show(items, stages, done_map, only_stage=None, only_due=True)
    else:
        blk = show(items, stages, done_map, only_stage=a.stage)

    print("\n" + "-" * 76)
    if blk:
        print("⛔ 还有 %d 个'阻塞项'没做完 —— 做到这些之前，下一步会卡死：" % len(blk))
        for r in blk:
            print("   · %s（%s）" % (r["title"], r["stage"]))
        sys.exit(1)
    print("✅ 当前阶段没有未完成的阻塞项，可以往下走。")


if __name__ == "__main__":
    main()
