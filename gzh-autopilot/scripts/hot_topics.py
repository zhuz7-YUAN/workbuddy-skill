#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爆款选题：查同领域公众号爆款文章，给写稿当参考（可选功能）

用法: python hot_topics.py --keyword 退休 --limit 10 [--days 90]
输出: 当前目录 hot_topics.json（标题/阅读/点赞/发布时间/链接）

需要红狐数据 Key（redfox.hk 注册 → 控制台 → API Key）。
没有 Key 也不影响本技能其他功能——选题可让 AI 联网搜索代替。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SKILL_DIR = Path(__file__).resolve().parent.parent
SECRETS = SKILL_DIR / "secrets" / "wechat_pub.json"


def load_redfox_key():
    if not SECRETS.exists():
        raise SystemExit(
            "[x] 红狐 Key 未配置。把 Key 发给 AI，由 AI 代跑:\n"
            "    python setup_account.py --redfox-key 你的Key\n"
            "    （获取: redfox.hk 注册 → 控制台 → API Key）")
    d = json.loads(SECRETS.read_text(encoding="utf-8"))
    key = (d.get("redfox_api_key") or "").strip()
    if not key:
        raise SystemExit("[x] 红狐 Key 未配置: python setup_account.py --redfox-key 你的Key")
    return key


def main():
    ap = argparse.ArgumentParser(description="公众号爆款选题")
    ap.add_argument("--keyword", required=True, help="领域关键词，如: 退休 / 育儿 / 理财")
    ap.add_argument("--limit", type=int, default=10, help="取多少条，默认10")
    args = ap.parse_args()

    try:
        import requests
    except ImportError:
        raise SystemExit("[x] 缺少依赖 requests。请先安装: pip install requests")

    key = load_redfox_key()
    url = "https://redfox.hk/story/api/gzhData/searchArticle"
    body = {"keyword": args.keyword, "offset": 0, "limit": args.limit, "sortType": "_4"}
    resp = requests.post(url, json=body,
                         headers={"Content-Type": "application/json", "X-API-KEY": key},
                         timeout=25)
    data = resp.json()
    if data.get("code") != 2000:
        raise SystemExit("[x] 红狐接口失败: code=%s msg=%s（Key 过期或额度不足时常见）"
                         % (data.get("code"), data.get("msg")))

    items = data.get("data", {}).get("list", [])
    result = {
        "keyword": args.keyword,
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(items),
        "items": [
            {
                "title": it.get("title"),
                "author": it.get("author"),
                "readCount": it.get("readCount"),
                "likeCount": it.get("likeCount"),
                "commentCount": it.get("commentCount"),
                "publishTime": it.get("publishTime"),
                "workUrl": it.get("workUrl"),
            }
            for it in items
        ],
    }
    out = Path("hot_topics.json").resolve()
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[√] 已查 %d 条爆款，写入 %s" % (len(items), out))
    print("--- 标题样本（写稿参考） ---")
    for i, it in enumerate(items[:5], 1):
        print("%d. 《%s》 阅读≈%s 点赞=%s" % (
            i, it.get("title"), it.get("readCount"), it.get("likeCount")))


if __name__ == "__main__":
    main()
