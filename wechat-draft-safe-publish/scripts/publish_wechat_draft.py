#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号草稿箱安全发布脚本（防中文乱码）。

用法：
    python publish_wechat_draft.py --article article.json \
        [--secrets secrets/wechat_pub.json] [--cover-out wechat_cover.jpg]

article.json 结构：{"title","content"(HTML 字符串),"digest","author"}
凭证文件 secrets/wechat_pub.json 结构：{"appid": "...", "appsecret": "..."}

编码安全要点（已验证，请勿改动）：
- 读 article.json：先 UTF-8，失败回退 gb18030（修复历史被 GBK 写入的乱码文件）。
- 发请求：json.dumps(payload, ensure_ascii=False).encode("utf-8") + 显式
  Content-Type: application/json; charset=utf-8。彻底避免「GBK写 / UTF-8读 /
  默认编码」导致的乱码链路。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

# 使用日志自动记录 (脱敏, 存用户本机)
try:
    from usage_logger import log_event, print_report
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from usage_logger import log_event, print_report

CJK_FONT_CANDIDATES = [
    "msyh.ttc", "simhei.ttf", "simsun.ttc", "msyh.ttf", "simsun.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def load_article(path: Path) -> dict:
    raw = Path(path).read_bytes()
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("gb18030"))


def load_creds(secrets_path: Path):
    data = json.loads(secrets_path.read_text(encoding="utf-8"))
    appid = data.get("appid", "").strip()
    secret = data.get("appsecret", "").strip()
    if not appid or not secret or secret.startswith("在此"):
        raise SystemExit("❌ 公众号凭证未填写完整（appid/appsecret）")
    return appid, secret


def get_token(appid, secret):
    resp = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": appid, "secret": secret},
        timeout=20,
    )
    d = resp.json()
    if "access_token" not in d:
        if d.get("errcode") == 40164:
            raise SystemExit("❌ 40164 IP不在白名单：请到 open.weixin.qq.com 更新IP白名单为当前宽带出口IP")
        raise SystemExit(f"❌ 获取token失败: {d}")
    return d["access_token"]


def make_cover(title: str, path: Path):
    img = Image.new("RGB", (300, 300), "#c0392b")
    draw = ImageDraw.Draw(img)
    font = None
    for f in CJK_FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                font = ImageFont.truetype(f, 30)
                break
            except Exception:
                continue
    label = (title or "公众号")[:8]
    if font is not None:
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((300 - tw) // 2, (300 - th) // 2), label, fill="white", font=font)
    else:
        draw.text((20, 140), "WECHAT", fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=75, optimize=True)
    return path


def upload_thumb(token, path: Path):
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=thumb"
    with open(path, "rb") as f:
        resp = requests.post(url, files={"media": (path.name, f, "image/jpeg")}, timeout=30)
    d = resp.json()
    if "media_id" not in d:
        raise SystemExit(f"❌ 封面上传失败: {d}")
    return d["media_id"]


def add_draft(token, art, thumb_id):
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"
    # author 字段限长极严（约8字节/4汉字），超长报 45110
    author = (art.get("author") or "祝")[:4]
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
    # 显式 UTF-8 + charset 头，杜绝任何编码歧义
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    d = resp.json()
    if d.get("errcode") not in (None, 0):
        if d.get("errcode") == 40164:
            raise SystemExit("❌ 40164 IP不在白名单：请到 open.weixin.qq.com 更新IP白名单")
        raise SystemExit(f"❌ 存草稿失败: {d}")
    return d.get("media_id")


def do_publish(args):
    art_path = Path(args.article)
    if not art_path.exists():
        raise SystemExit(f"❌ 文章文件不存在: {art_path}")
    art = load_article(art_path)

    # 自检：打印即将发送的关键字段，核对是否为正常中文（非乱码）
    print(f"[自检] title={art.get('title','')[:20]} | author={art.get('author','祝')[:4]} | content前30字={art.get('content','')[:30]}")

    secrets_path = Path(args.secrets)
    if not secrets_path.exists():
        raise SystemExit(f"❌ 凭证文件不存在: {secrets_path}（可用 --secrets 指定）")
    appid, secret = load_creds(secrets_path)
    token = get_token(appid, secret)
    cover = make_cover(art.get("title", ""), Path(args.cover_out))
    thumb_id = upload_thumb(token, cover)
    media_id = add_draft(token, art, thumb_id)
    print(f"✅ 草稿保存成功: media_id={media_id}")
    print("请到公众号后台「内容与互动 → 草稿箱」查看并发布。")
    log_event("wechat-draft-safe-publish", "publish", True,
              platform="微信公众号", note="草稿保存成功")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article", required=False)
    ap.add_argument("--secrets", default="secrets/wechat_pub.json")
    ap.add_argument("--cover-out", default="wechat_cover.jpg")
    ap.add_argument("--report", action="store_true",
                    help="打印本地运行日志汇总(仅本机, 不上传)")
    args = ap.parse_args()

    if args.report:
        print_report("wechat-draft-safe-publish")
        return

    if not args.article:
        raise SystemExit("❌ 缺少 --article 参数（查看报告请用 --report）")

    try:
        do_publish(args)
    except SystemExit as e:
        if getattr(e, "code", None):  # 仅错误退出(非 0)才记日志
            msg = str(e)
            m = re.search(r"(\d{4,5})", msg)
            ec = m.group(1) if m else ""
            log_event("wechat-draft-safe-publish", "publish", False,
                      platform="微信公众号", error_code=ec, error_msg=msg[:120])
        raise
    except Exception as e:
        log_event("wechat-draft-safe-publish", "publish", False,
                  platform="微信公众号", error_code="EXC", error_msg=repr(e)[:120])
        raise


if __name__ == "__main__":
    main()
