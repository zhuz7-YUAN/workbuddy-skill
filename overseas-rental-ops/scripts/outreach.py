#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
outreach.py —— 按模板生成问询文案，并可经 SMTP 直接发出
核心目的：一封问询问完所有决定性问题（见 references/question_pack.md），
        不发多次、不重复问。

用法：
  # 1) 先看文案（不发送）
  outreach.py --profile renter.json --stage first_contact --lang it
  outreach.py --profile renter.json --stage dm --lang it

  # 2) 确认后发送（--send 必须显式指定；只发邮件，站内信/私信请人工粘贴）
  outreach.py --profile renter.json --stage first_contact --lang it \
              --send --to landlord@example.com --smtp smtp.json

  # 3) 发出后记进台账（防重复问）
  python housing_db.py contact --listing 12 --channel email --target landlord@example.com \
         --questions "1,2,3,4,5,6,7"

profile 文件（renter.json）示例：
  { "name": "<委托人>", "school": "Trento", "faculty": "Facolta di Economia",
    "start": "subito", "end_date": "31 gennaio 2027",
    "budget": "250-450 euro", "phone": "+39 ...", "email": "reply@example.com" }
"""
import argparse, json, os, smtplib, sys, ssl
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "..", "assets", "templates", "messages.json")


def load_templates():
    with open(TEMPLATES, encoding="utf-8") as f:
        return json.load(f)


def render(text, profile):
    out = text
    for k, v in profile.items():
        if k.startswith("_") or isinstance(v, (dict, list)):
            continue
        out = out.replace("{%s}" % k, str(v))
    return out


# 这些阶段的收件人是平台/群组，不是房东邮箱 —— 抄送不适用，也不该自动发
NON_EMAIL_STAGES = {"board_form", "dm", "group_apply", "group_post"}


def build_cc(profile, override=None, confirmed=False):
    """决定抄送谁。返回 (cc_list, note)

    抄送策略（关键设计）：抄送不能无脑抄 —— 未核实的房源直接抄给家人，
    就是把假消息/僵尸房源转嫁给收件人，正是"浪费女儿时间"那个坑。
    所以 confirmed_only 必须由调用方用 --confirmed 明确"这条已核实"，才放行。
    """
    mail = profile.get("_mail") or {}
    mode = mail.get("cc_mode", "confirmed_only")

    if override is not None:
        return [x.strip() for x in override.split(",") if x.strip()], "命令行 --cc 指定"
    if mode == "none":
        return [], "cc_mode=none（不抄送）"

    raw = mail.get("cc") or []
    addrs = []
    for c in raw:
        if isinstance(c, dict):
            em = c.get("email")
            scope = c.get("scope") or "all"
            if em and (scope == "all" or confirmed):
                addrs.append(em)
        elif c:
            addrs.append(str(c))

    if not addrs:
        return [], "cc_mode=%s 但无抄送对象" % mode
    if mode == "all":
        return addrs, "cc_mode=all（未核实也抄送，慎用）"
    if mode == "confirmed_only":
        if confirmed:
            return addrs, "cc_mode=confirmed_only + --confirmed（已核实，放行抄送）"
        return [], "cc_mode=confirmed_only，但未加 --confirmed → 本封不抄送第三人"
    return addrs, "cc_mode=%s" % mode


def send_mail(cfg, to, subject, body, cc=None):
    host = cfg["smtp_host"]; port = int(cfg.get("smtp_port", 465))
    sender = cfg["sender"]; code = cfg["auth_code"]
    name = cfg.get("sender_name", "")
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject or "(senza oggetto)", "utf-8")
    msg["From"] = formataddr((str(Header(name or sender, "utf-8")), sender))
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if cfg.get("reply_to"):
        msg["Reply-To"] = cfg["reply_to"]
    ctx = ssl.create_default_context()
    if cfg.get("use_ssl", True):
        s = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30); s.starttls(context=ctx)
    s.login(sender, code)
    rcpt = [x.strip() for x in to.split(",")] + list(cc or [])
    s.sendmail(sender, rcpt, msg.as_string())
    s.quit()


def main():
    p = argparse.ArgumentParser(description="问询文案生成与发送")
    p.add_argument("--profile", required=True, help="租客/委托资料 JSON（见 onboard.py）")
    p.add_argument("--stage", default="first_contact",
                   choices=["first_contact", "board_form", "dm", "followup", "confirm_viewing",
                            "group_apply", "group_post"])
    p.add_argument("--lang", default="it", choices=["it", "en", "zh"])
    p.add_argument("--send", action="store_true", help="真的发出去（不加只打印）")
    p.add_argument("--to", help="收件邮箱（--send 时必填，多个用逗号分隔）")
    p.add_argument("--smtp", help="SMTP 配置 JSON")
    p.add_argument("--out", help="把文案写到文件")
    p.add_argument("--cc", default=None, help="抄送覆盖（逗号分隔）；不给则按 profile 的 _mail.cc 策略")
    p.add_argument("--confirmed", action="store_true",
                   help="声明这条房源已核实可租。cc_mode=confirmed_only 时必须加它才会抄送第三人")
    a = p.parse_args()

    tpl = load_templates().get(a.lang, {})
    if a.stage not in tpl:
        print("!! 模板缺失：%s / %s" % (a.lang, a.stage))
        print("   现有：", ", ".join(tpl.keys()))
        sys.exit(1)
    profile = json.load(open(a.profile, encoding="utf-8"))
    # 署名回退：代租没填 sender_name 时，用租客名（但会提示）
    if not profile.get("sender_name"):
        profile["sender_name"] = profile.get("name", "")
    t = tpl[a.stage]
    subject = render(t.get("subject", ""), profile)
    body = render(t["body"], profile)

    is_email = a.stage not in NON_EMAIL_STAGES
    cc_list, cc_note = build_cc(profile, override=a.cc, confirmed=a.confirmed)
    if not is_email:
        cc_list, cc_note = [], "该阶段发给平台/群组，抄送不适用"

    print("=" * 70)
    print("语言/阶段：%s / %s" % (a.lang, a.stage))
    print("署名：%s" % (profile.get("sender_name") or "(空)"))
    if subject:
        print("主题：%s" % subject)
    if is_email:
        print("抄送：%s" % ("、".join(cc_list) if cc_list else "（无）"))
        print("      └ %s" % cc_note)
    print("-" * 70)
    print(body)
    print("=" * 70)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            if subject:
                f.write("Oggetto: %s\n\n" % subject)
            if cc_list:
                f.write("[Cc] %s\n\n" % ", ".join(cc_list))
            f.write(body)
        print("已写出：%s" % a.out)

    if not a.send:
        print("\n（未发送。确认无误后加 --send --to <邮箱> --smtp <配置> 发出；")
        print("  站内信 / 私信请手动粘贴，不要用脚本自动发——有封号风险。）")
        if a.stage in NON_EMAIL_STAGES:
            print("  该阶段本就不该经邮件发送：内容是给学生本人贴到平台/群里的。")
        return

    if a.stage in NON_EMAIL_STAGES:
        print("!! 该阶段（%s）不发邮件：这是给学生本人贴到平台/群组的文案。" % a.stage)
        sys.exit(1)
    if not a.to or not a.smtp:
        print("!! --send 需要 --to 和 --smtp"); sys.exit(1)
    cfg = json.load(open(a.smtp, encoding="utf-8"))
    cfg.setdefault("reply_to", cfg["sender"])
    send_mail(cfg, a.to, subject, body, cc=cc_list)
    print("\n[OK] 已发送至 %s%s" % (a.to, ("，抄送 " + "、".join(cc_list)) if cc_list else ""))
    print("别忘了记台账：python housing_db.py contact --listing <ID> --channel email "
          "--target %s --questions \"1,2,3,4,5,6,7\"" % a.to.split(",")[0])


if __name__ == "__main__":
    main()
