#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号凭证配置器（第一次使用必跑，之后不用再跑）

用法:
  看状态:     python setup_account.py --status
  交互模式:   python setup_account.py
  参数模式:   python setup_account.py --appid wx开头 --secret 32位 [--redfox-key KEY]
  只存不验证: 加 --skip-check

凭证只保存在你自己电脑的本技能目录 secrets/ 下，不上传任何地方。
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # 防 Windows GBK 控制台中文乱码

# 使用日志自动记录 (脱敏, 存用户本机)
try:
    from usage_logger import log_event, print_report
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from usage_logger import log_event, print_report

SKILL_DIR = Path(__file__).resolve().parent.parent
SECRETS = SKILL_DIR / "secrets" / "wechat_pub.json"
SKILL_NAME = "gzh-autopilot"


def load_all():
    if SECRETS.exists():
        try:
            return json.loads(SECRETS.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_all(d):
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def mask(s):
    if not s:
        return "(空)"
    return s[:4] + "*" * (len(s) - 6) + s[-2:] if len(s) > 8 else "*" * len(s)


def check_token(appid, secret):
    """向微信官方接口验证凭证。返回 (是否成功, 大白话消息)。"""
    import urllib.request
    import urllib.parse
    q = urllib.parse.urlencode({
        "grant_type": "client_credential", "appid": appid, "secret": secret})
    url = "https://api.weixin.qq.com/cgi-bin/token?" + q
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, "网络连不上微信接口（%r）。检查电脑能否上网后重试。" % e
    if "access_token" in d:
        return True, "验证通过！AppID/AppSecret 正确，IP 白名单已放行。配置完成。"
    err = d.get("errcode")
    msg = d.get("errmsg", "")
    if err == 40164:
        return False, (
            "还差最后一步——IP 白名单没放行你的电脑（错误码 40164）。\n"
            "微信的原话: %s\n"
            "解决办法（照做，1 分钟）:\n"
            "  1. 浏览器打开 open.weixin.qq.com，用公众号扫码登录\n"
            "  2. 左侧「开发接口管理」→「IP 白名单」\n"
            "  3. 把上面微信原话里提到的那个 IP 地址加进去（每行一个）\n"
            "  4. 保存后等 1 分钟，重跑一遍本命令即可" % msg)
    if err in (40001, 40125):
        return False, ("AppSecret 不对（错误码 %s）。多半是复制时少了字符，"
                       "或之前点过「重置」生成了新密码。\n"
                       "回 mp.weixin.qq.com → 设置与开发 → 基本配置 → 重新复制 AppSecret 再试。" % err)
    if err == 40013:
        return False, "AppID 不对（错误码 40013）。请核对是否复制完整、是否复制错了公众号的。"
    return False, "验证失败：错误码 %s，消息 %s" % (err, msg)


GUIDE = """
========== 公众号凭证获取指引 ==========
1. 电脑浏览器打开  mp.weixin.qq.com  扫码登录
2. 左下角「设置与开发」→「基本配置」
3. 「开发者ID(AppID)」→ 复制（wx 开头）
4. 「开发者密码(AppSecret)」→ 点「启用/重置」→ 手机验证码 → 生成后立刻复制
   （只显示一次，关掉窗口就看不到了）
=======================================
"""


def main():
    ap = argparse.ArgumentParser(description="公众号凭证配置器")
    ap.add_argument("--appid")
    ap.add_argument("--secret")
    ap.add_argument("--redfox-key", dest="redfox_key")
    ap.add_argument("--status", action="store_true", help="只看配置状态")
    ap.add_argument("--skip-check", dest="skip_check", action="store_true",
                    help="只保存，不向微信验证（网络不好时用）")
    ap.add_argument("--report", action="store_true",
                    help="打印本地运行日志汇总(仅本机, 不上传)")
    args = ap.parse_args()

    if args.report:
        print_report(SKILL_NAME)
        return

    if args.status:
        d = load_all()
        print("=" * 46)
        print(" 当前配置状态")
        print("=" * 46)
        print("  AppID:     %s" % (d.get("appid") or "(未配置)"))
        print("  AppSecret: %s" % mask(d.get("appsecret", "")))
        print("  红狐 Key:  %s" % mask(d.get("redfox_api_key", "")))
        ok = bool(d.get("appid") and d.get("appsecret"))
        print("-" * 46)
        if ok:
            print(" 结论: 微信凭证已配置，可直接发稿")
            if not d.get("redfox_api_key"):
                print(" 提示: 红狐 Key 未配（可选，只影响爆款选题功能）")
        else:
            print(" 结论: 未配置。把 AppID 和 AppSecret 发给 AI，由 AI 代跑：")
            print("   python setup_account.py --appid wx... --secret ...")
        return

    # ---- 参数模式 ----
    if args.appid or args.secret or args.redfox_key:
        d = load_all()
        if args.appid:
            d["appid"] = args.appid.strip()
        if args.secret:
            d["appsecret"] = args.secret.strip()
        if args.redfox_key:
            d["redfox_api_key"] = args.redfox_key.strip()
        save_all(d)
        print("[√] 已保存到本机: %s" % SECRETS)
        if args.appid and args.secret and not args.skip_check:
            print("[*] 正在向微信验证凭证（顺便测 IP 白名单）...")
            ok, msg = check_token(d["appid"], d["appsecret"])
            print(("[√] " if ok else "[!] ") + msg)
            ec = ""
            import re as _re
            m = _re.search(r"(\d{4,5})", msg)
            if m:
                ec = m.group(1)
            log_event(SKILL_NAME, "config", ok, platform="微信公众号",
                      error_code=ec, error_msg=msg[:120])
            if not ok:
                print("    （凭证已保存，修好上面的问题后不用重填，重跑本命令即可验证）")
            return

    # ---- 交互模式 ----
    print("=" * 46)
    print(" 公众号凭证配置（只需做一次）")
    print("=" * 46)
    print(GUIDE)
    d = load_all()
    appid = input("粘贴 AppID (wx开头，直接回车=保留原值): ").strip()
    if appid:
        d["appid"] = appid
    secret = input("粘贴 AppSecret (直接回车=保留原值): ").strip()
    if secret:
        d["appsecret"] = secret
    redfox = input("红狐数据 Key（可选，直接回车跳过）: ").strip()
    if redfox:
        d["redfox_api_key"] = redfox
    if not d.get("appid") or not d.get("appsecret"):
        print("[x] AppID/AppSecret 不能为空，未保存。"); return
    save_all(d)
    print("\n[√] 已保存到本机: %s" % SECRETS)
    print("[*] 正在向微信验证凭证（顺便测 IP 白名单）...")
    ok, msg = check_token(d["appid"], d["appsecret"])
    print(("[√] " if ok else "[!] ") + msg)
    ec = ""
    import re as _re
    m = _re.search(r"(\d{4,5})", msg)
    if m:
        ec = m.group(1)
    log_event(SKILL_NAME, "config", ok, platform="微信公众号",
              error_code=ec, error_msg=msg[:120])


if __name__ == "__main__":
    main()
