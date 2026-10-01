#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日招聘简报生成器 - 简报拼装器 (纯本地, 不联网)

用法 (AI 在整理完当日岗位后调用):
  python gen_brief.py --date 2026-08-24 --data brief.json --out 招聘简报_2026-08-24.md
  python gen_brief.py --date 2026-08-24 --raw-file 草稿.md --out 招聘简报_2026-08-24.md

设计原则:
  - 本脚本只做"拼装 + 落盘", 不联网、不爬数据。
  - 联网抓取岗位 (WebSearch/WebFetch) 由调用方 (AI) 完成, 保证口径与时效可控。
  - 用户画像 / 收件邮箱等敏感配置从本机配置文件读取, 绝不上传到 SkillHub。

数据来源 (--data 的 JSON 字段, 全部可空):
  profile         dict  用户画像 (name/city/degree/major/salary/strategy...)
  sections        list  8 段结构, 每段 {title, body} ; body 支持多行文本
  raw             str   若 AI 已写好完整简报正文, 直接包进文件 (最省事)
  email           str   收件邮箱 (覆盖配置文件)
  email_subject   str   邮件主题

本机配置文件 (可选, 放置于技能目录同级的 config.json 或用户主目录):
  {
    "name": "张三",
    "email": "zhangsan@example.com",
    "profile": { ... }
  }
  找不到则用内置中性默认画像 (示例: 2026届离校未就业, 武汉, 嵌入式/FPGA方向)。
"""

import argparse
import json
import os
import sys
from datetime import datetime, date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SKILL_DIR)
HOME = os.path.expanduser("~")

# 中性默认画像 (不含任何真实个人身份信息)
DEFAULT_PROFILE = {
    "name": "同学",
    "city": "武汉",
    "degree": "2026届本科",
    "major": "电子与计算机工程(ECE)",
    "salary": "13-22K",
    "status": "离校未就业, 处于2年择业期(央国企按应届对待)",
    "directions": "嵌入式 / FPGA / 芯片半导体 / 硬件 / 机器人 / 央国企科技岗",
    "strategy": "央国企秋招主攻 + 中型上市公司社招补录 + 内推 + 外包兜底",
    "local_priority": "本地(光谷)优先, 标注 ✅",
    "special_requirements": "",
    "resume_notes": "",
}

DEFAULT_EMAIL = ""  # 留空 = 不发邮件, 仅本地交付


def load_config():
    """读取本机配置 (优先技能目录 config.json, 其次主目录)。"""
    cfg = {}
    for p in (os.path.join(SKILL_ROOT, "config.json"),
              os.path.join(HOME, "job_brief_config.json")):
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
                break
            except Exception:
                pass
    return cfg


def build_markdown(date_str, profile, sections, raw, email, subject):
    name = profile.get("name", "同学")
    city = profile.get("city", "武汉")
    lines = []
    lines.append("# 每日求职简报（%s）" % date_str)
    lines.append("")
    lines.append("> **收件人**：%s同学  ｜  **城市**：%s  ｜  **基调**：有温度、有干货、可执行"
                 % (name, city))
    lines.append("")
    lines.append("---")
    lines.append("")

    if raw and raw.strip():
        # AI 已写好完整正文, 直接采用
        lines.append(raw.strip())
        lines.append("")
    elif sections:
        for i, sec in enumerate(sections, 1):
            title = sec.get("title", "第%d段" % i)
            body = sec.get("body", "")
            lines.append("## %d. %s" % (i, title))
            lines.append("")
            lines.append(body.strip() if isinstance(body, str) else str(body))
            lines.append("")
    else:
        lines.append("_（本日暂无岗位数据，请检查数据源或重试）_")
        lines.append("")

    # 画像卡 (帮助使用者/本人看清定位)
    lines.append("---")
    lines.append("")
    lines.append("## 附：用户画像与筛选口径")
    lines.append("")
    lines.append("- **姓名**：%s" % profile.get("name", "—"))
    lines.append("- **城市**：%s" % profile.get("city", "—"))
    lines.append("- **学历/专业**：%s / %s" % (profile.get("degree", "—"),
                                           profile.get("major", "—")))
    lines.append("- **现状**：%s" % profile.get("status", "—"))
    lines.append("- **方向**：%s" % profile.get("directions", "—"))
    lines.append("- **策略**：%s" % profile.get("strategy", "—"))
    lines.append("- **地域**：%s" % profile.get("local_priority", "—"))
    sr = profile.get("special_requirements", "")
    if sr:
        lines.append("- **特殊要求**：%s（已按此过滤）" % sr)
    rn = profile.get("resume_notes", "")
    if rn:
        lines.append("- **简历要点**：%s（岗位匹配依据）" % rn)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_本报告由「每日招聘简报生成器」skill 本地生成。岗位信息来自公开招聘渠道，"
                 "请以来源官网最终发布为准，本简报不构成就业承诺。_")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                    help="简报日期 YYYY-MM-DD")
    ap.add_argument("--data", help="JSON 数据文件 (含 profile/sections/raw/email)")
    ap.add_argument("--raw-file", help="AI 已写好的简报正文 md 文件, 直接包入")
    ap.add_argument("--out", default=None, help="输出 md 路径, 默认 招聘简报_YYYY-MM-DD.md")
    ap.add_argument("--email", help="收件邮箱 (覆盖配置)")
    ap.add_argument("--emit-email-hint", action="store_true",
                    help="在 stdout 打印如何用 Agent Mail 发信的提示 (不实际发送)")
    a = ap.parse_args()

    cfg = load_config()
    profile = dict(DEFAULT_PROFILE)
    profile.update(cfg.get("profile", {}))
    email = a.email or cfg.get("email", "") or DEFAULT_EMAIL
    subject = "【每日求职推荐】%s - %s" % (profile.get("city", "武汉"), a.date)

    raw = ""
    sections = []
    if a.raw_file and os.path.isfile(a.raw_file):
        with open(a.raw_file, encoding="utf-8") as f:
            raw = f.read()
    if a.data and os.path.isfile(a.data):
        with open(a.data, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            if d.get("profile"):
                profile.update(d["profile"])
            if d.get("email"):
                email = d["email"]
            if d.get("email_subject"):
                subject = d["email_subject"]
            sections = d.get("sections", [])
            if d.get("raw"):
                raw = d["raw"]

    md = build_markdown(a.date, profile, sections, raw, email, subject)

    out = a.out or ("招聘简报_%s.md" % a.date)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print("OK|out=%s|bytes=%d" % (out, len(md.encode("utf-8"))))

    if email:
        print("[i] 收件邮箱已配置: %s" % email)
        if a.emit_email_hint:
            print("[发信提示] 用 Agent Mail connector 的 SendMessage:")
            print('  to=[{"email":"%s","name":"%s"}]' % (email, profile.get("name", "同学")))
            print('  subject="%s"' % subject)
            print('  body_format=MARKDOWN, body=简报正文')
            print("  注: 实际发送由 AI 调用 Agent Mail 完成, 本脚本不联网。")
    else:
        print("[i] 未配置收件邮箱, 仅本地交付 markdown。")


if __name__ == "__main__":
    main()
