#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill 本地运行日志（纯标准库，无第三方依赖）

用途: 让每个 Skill 的脚本在运行时，把「跑通/没跑通/原因」记录到用户本机日志文件，
      仅用于使用者自己排查问题。本模块不联网、不向任何外部地址发送数据。

日志位置: ~/.workbuddy/skills/<skill>/logs/usage-YYYY-MM-DD.jsonl
隐私: 任何疑似密钥/凭证的片段在写入前会被自动抹掉，日志不含明文密钥。
"""
import json
import os
import sys
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SKILL_ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")

# 这些关键字后面的内容视为敏感, 写入前抹掉
_SENSITIVE = ["sk-or-v1", "AIzaSy", "appsecret", "appid", "Bearer ",
              "access_token", "password", "token=", "secret="]


def _scrub(text):
    if not text:
        return text
    t = str(text)
    for kw in _SENSITIVE:
        idx = t.find(kw)
        while idx >= 0:
            start = idx
            end = start
            while end < len(t) and t[end] not in " \t\r\n\"'`,;)}]":
                end += 1
            t = t[:start] + "***[已脱敏]***" + t[end:]
            idx = t.find(kw, idx + 1)
    return t


def log_event(skill, action, success, platform="", model="",
              error_code="", error_msg="", note=""):
    """追加一条记录到当日本地日志。仅在用户本机落盘，不发往任何外部。"""
    try:
        d = datetime.datetime.now()
        log_dir = os.path.join(SKILL_ROOT, skill, "logs")
        os.makedirs(log_dir, exist_ok=True)
        rec = {
            "ts": d.strftime("%Y-%m-%d %H:%M:%S"),
            "skill": skill,
            "action": action,
            "success": bool(success),
            "platform": platform,
            "model": model,
            "error_code": error_code,
            "error_msg": _scrub(error_msg)[:200],
            "note": note,
        }
        path = os.path.join(log_dir, "usage-" + d.strftime("%Y-%m-%d") + ".jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def print_report(skill, days=7):
    """打印并落盘本地运行日志汇总，供使用者自己查看问题。"""
    import glob
    from collections import Counter
    log_dir = os.path.join(SKILL_ROOT, skill, "logs")
    lines = []
    if not os.path.isdir(log_dir):
        lines.append("[i] 暂无本地运行日志（这个 Skill 还没被运行过）")
        _emit(lines)
        return
    files = sorted(glob.glob(os.path.join(log_dir, "usage-*.jsonl")))
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).date()
    rows = []
    for fp in files:
        try:
            d0 = datetime.datetime.strptime(
                os.path.basename(fp)[6:16], "%Y-%m-%d").date()
        except Exception:
            d0 = None
        if d0 and d0 < cutoff:
            continue
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    if not rows:
        lines.append("[i] 最近 %d 天没有运行记录" % days)
        _emit(lines)
        return

    ok = sum(1 for r in rows if r.get("success"))
    fail = len(rows) - ok
    lines.append("=" * 52)
    lines.append(" 【%s】本地运行日志汇总 (近 %d 天)" % (skill, days))
    lines.append(" 总事件: %d | 成功: %d | 失败: %d" % (len(rows), ok, fail))
    lines.append("-" * 52)
    fails = [r for r in rows if not r.get("success")]
    if fails:
        lines.append(" 失败原因 TOP:")
        c = Counter("%s %s" % (r.get("error_code", ""),
                               (r.get("error_msg") or "")[:40]) for r in fails)
        for reason, n in c.most_common(5):
            lines.append("   %2d 次  %s" % (n, reason.strip()))
        lines.append("-" * 52)
    lines.append(" 明细(最近 10 条):")
    for r in rows[-10:]:
        flag = "OK " if r.get("success") else "FAIL"
        extra = ""
        if not r.get("success"):
            extra = " [%s %s]" % (r.get("error_code", ""),
                                  (r.get("error_msg") or "")[:30])
        lines.append("  %s %s | %s | %s%s" % (
            flag, r.get("ts"), r.get("platform"), r.get("action"), extra))
    lines.append("=" * 52)
    _emit(lines)

    try:
        home = os.path.expanduser("~")
        out_path = os.path.join(home, "skill_log_%s.txt" % skill)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("[√] 日志已存为文件: %s" % out_path)
    except Exception:
        pass


def _emit(lines):
    print("\n".join(lines))
