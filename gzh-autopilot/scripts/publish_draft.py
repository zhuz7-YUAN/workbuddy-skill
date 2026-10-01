#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把文章 JSON 存进公众号草稿箱（自动生成封面）

用法:
  真发:   python publish_draft.py --article article.json
  演练:   python publish_draft.py --article article.json --dry-run
          （--dry-run 只在本地生成封面并自检，不连微信，零风险，建议第一次先用）

article.json 结构: {"title","content"(HTML <p>段落),"digest","author"}

编码安全铁律（防乱码）:
- 读文章 JSON 强制 UTF-8，失败自动回退 gb18030（兼容历史 GBK 文件）
- 发往微信的 JSON 用 ensure_ascii=False + 显式 charset=utf-8 头
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 使用日志自动记录 (脱敏, 存用户本机)
try:
    from usage_logger import log_event, print_report
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from usage_logger import log_event, print_report

SKILL_DIR = Path(__file__).resolve().parent.parent
SECRETS = SKILL_DIR / "secrets" / "wechat_pub.json"
SKILL_NAME = "gzh-autopilot"

CJK_FONT_CANDIDATES = [
    "msyh.ttc", "simhei.ttf", "simsun.ttc", "msyh.ttf", "simsun.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def need(mod, pip_name):
    try:
        import importlib
        return importlib.import_module(mod)
    except ImportError:
        raise SystemExit("[x] 缺少依赖 %s。请先安装: pip install %s" % (mod, pip_name))


def load_article(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gb18030")  # 历史文件曾被 GBK 写入时的自动修复
    art = json.loads(text)
    for k in ("title", "content"):
        if not art.get(k):
            raise SystemExit("[x] 文章缺少字段: %s" % k)
    return art


def load_creds():
    if not SECRETS.exists():
        raise SystemExit(
            "[x] 还没配置公众号凭证。\n"
            "    把 AppID / AppSecret 发给 AI，由 AI 代跑:\n"
            "    python setup_account.py --appid wx... --secret ...")
    d = json.loads(SECRETS.read_text(encoding="utf-8"))
    appid = (d.get("appid") or "").strip()
    secret = (d.get("appsecret") or "").strip()
    if not appid or not secret:
        raise SystemExit("[x] 凭证不完整，请重跑 setup_account.py")
    return appid, secret


def get_token(appid, secret):
    requests = need("requests", "requests")
    resp = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": appid, "secret": secret},
        timeout=20,
    )
    d = resp.json()
    if "access_token" not in d:
        if d.get("errcode") == 40164:
            raise SystemExit(
                "[x] IP 不在白名单(40164): %s\n"
                "    修法: open.weixin.qq.com 扫码登录 → 开发接口管理 → IP 白名单 → "
                "把上面提到的 IP 加进去，等 1 分钟重试" % d.get("errmsg"))
        if d.get("errcode") in (40001, 40125):
            raise SystemExit("[x] AppSecret 不对(%s)，重新复制后再跑 setup_account.py" % d.get("errcode"))
        raise SystemExit("[x] 获取token失败: %s" % d)
    return d["access_token"]


def make_cover(title: str, path: Path, color="#c0392b"):
    PIL_Image = need("PIL.Image", "pillow")
    import os
    from PIL import ImageDraw, ImageFont
    img = PIL_Image.new("RGB", (300, 300), color)
    draw = ImageDraw.Draw(img)
    font = None
    for f in CJK_FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                font = ImageFont.truetype(f, 30)
                break
            except Exception:
                continue
    label = (title or "公众号").replace("《", "").replace("》", "")[:8]
    if font is not None:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((300 - tw) // 2, (300 - th) // 2), label, fill="white", font=font)
    else:
        draw.text((20, 140), "WECHAT", fill="white")  # 无中文字体时的降级，避免方块乱码
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=75, optimize=True)
    return path


def upload_thumb(token, path: Path):
    requests = need("requests", "requests")
    url = ("https://api.weixin.qq.com/cgi-bin/material/add_material"
           "?access_token=%s&type=thumb" % token)
    with open(path, "rb") as f:
        resp = requests.post(url, files={"media": (path.name, f, "image/jpeg")}, timeout=30)
    d = resp.json()
    if "media_id" not in d:
        raise SystemExit("[x] 封面上传失败: %s" % d)
    return d["media_id"]


def add_draft(token, art, thumb_id):
    requests = need("requests", "requests")
    url = "https://api.weixin.qq.com/cgi-bin/draft/add?access_token=%s" % token
    author = (art.get("author") or "佚名")[:4]  # author 限长约4汉字，超长报45110
    payload = {"articles": [{
        "title": art.get("title", "无标题"),
        "author": author,
        "digest": art.get("digest", ""),
        "content": art.get("content", ""),
        "content_source_url": "",
        "thumb_media_id": thumb_id,
        "show_cover_pic": 1,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(url, data=body,
                         headers={"Content-Type": "application/json; charset=utf-8"},
                         timeout=30)
    d = resp.json()
    if d.get("errcode") not in (None, 0):
        table = {
            40164: "IP 不在白名单，去 open.weixin.qq.com 加白名单",
            45003: "标题太长（≤64汉字）",
            45004: "摘要太长（≤120汉字）",
            45110: "作者名太长（≤4汉字）",
            48001: "API 权限不足，可能需要认证",
        }
        tip = table.get(d.get("errcode"), "")
        raise SystemExit("[x] 存草稿失败: %s %s" % (d, ("→ " + tip) if tip else ""))
    return d.get("media_id")


def main():
    ap = argparse.ArgumentParser(description="文章存入公众号草稿箱")
    ap.add_argument("--article", default="article.json", help="文章JSON路径")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="演练模式：本地生成封面+自检，不连微信")
    ap.add_argument("--cover-color", dest="cover_color", default="#c0392b",
                    help="封面底色，如 #1a73e8")
    ap.add_argument("--report", action="store_true",
                    help="打印本地运行日志汇总(仅本机, 不上传)")
    args = ap.parse_args()

    if args.report:
        print_report(SKILL_NAME)
        return

    art_path = Path(args.article)
    if not art_path.exists():
        raise SystemExit("[x] 文章文件不存在: %s（先让 AI 把文章写好存成 JSON）" % art_path)
    art = load_article(art_path)

    import re
    word_count = len(re.sub(r"<[^>]+>", "", art.get("content", "")))
    print("[自检] 标题: %s" % art.get("title", "")[:30])
    print("[自检] 作者: %s | 正文字数≈%d | 摘要字节=%d" % (
        (art.get("author") or "佚名")[:4], word_count, len((art.get("digest") or "").encode("utf-8"))))
    if len(art.get("title", "").encode("utf-8")) > 192:
        print("[!] 警告: 标题超过64汉字，微信会报45003")
    if len((art.get("digest") or "").encode("utf-8")) > 360:
        print("[!] 警告: 摘要超过120汉字，微信会报45004")

    cover = make_cover(art.get("title", ""), SKILL_DIR / "secrets" / "last_cover.jpg",
                       args.cover_color)
    print("[√] 封面已生成: %s" % cover)

    if args.dry_run:
        print("\n[演练模式] 到此为止，未连接微信。确认无误后去掉 --dry-run 真正存草稿。")
        log_event(SKILL_NAME, "dryrun", True, platform="微信公众号",
                  note="演练完成, 未连接微信")
        return

    try:
        appid, secret = load_creds()
        token = get_token(appid, secret)
        thumb_id = upload_thumb(token, cover)
        media_id = add_draft(token, art, thumb_id)
        print("[√] 草稿保存成功: media_id=%s" % media_id)
        print("下一步（必须你本人操作）: mp.weixin.qq.com → 内容与互动 → 草稿箱 → 检查无误后点「发表」")
        log_event(SKILL_NAME, "publish", True, platform="微信公众号",
                  note="草稿保存成功")
    except SystemExit as e:
        if getattr(e, "code", None):
            msg = str(e)
            m = re.search(r"(\d{4,5})", msg)
            ec = m.group(1) if m else ""
            log_event(SKILL_NAME, "publish", False, platform="微信公众号",
                      error_code=ec, error_msg=msg[:120])
        raise
    except Exception as e:
        log_event(SKILL_NAME, "publish", False, platform="微信公众号",
                  error_code="EXC", error_msg=repr(e)[:120])
        raise


if __name__ == "__main__":
    main()
