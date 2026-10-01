---
name: wechat-draft-safe-publish
description: "通用中文 JSON 防乱码 Skill，专注杜绝因 GBK/UTF-8 不匹配导致的中文乱码。适用于任何需要写入、读取或通过 HTTP 发送中文 JSON 的场景（如公众号草稿箱、文档系统、API 调用等）。"
agent_created: true
author: 用户
title: 通用中文 JSON 防乱码
---

# 通用中文 JSON 防乱码（编码铁律）

## 目的

把中文内容安全地写入 JSON、读取 JSON 或通过 HTTP 发送 JSON，**保证中文绝不变乱码**，并规避常见的编码陷阱。适用于任何需要处理中文 JSON 的工作流。

## 何时使用

- 需要将中文数据写入 JSON 文件（如配置、文章草稿、日志）。
- 读取可能被错误编码写入的旧 JSON 文件。
- 通过 HTTP 接口发送中文 JSON 负载（如 API 调用、 webhook）。
- 遇到乱码症状：中文显示为方块、问号或乱字符。

## 核心：编码铁律（乱码根因在此）

乱码几乎总是「**GBK 写 / UTF-8 读**」这一对在 Windows 上造成的：
Python `open(path,'w')` 默认编码是 GBK/cp936；若用默认编码写中文 JSON，文件存的是 GBK 字节；
读取端若用 `encoding="utf-8"` 去读，字节被错当成 UTF-8 解码，字符串在加载时就已经乱码。

三条铁律（任何环节都遵守）：

1. **写 JSON**：`open(path,'w',encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))`。
   禁止默认编码 `open(path,'w')`；`ensure_ascii=False` 保留中文原文。使用 Write 工具写 JSON 亦安全（默认 UTF-8）。

2. **读 JSON**：先尝试 `utf-8`，失败回退 `gb18030`（修复历史被 GBK 写入的文件）。

3. **发 HTTP**：`json.dumps(payload, ensure_ascii=False).encode('utf-8')` 作为请求体，带显式
   `Content-Type: application/json; charset=utf-8`。不要出现「原始 UTF-8 字节 + 无 charset 头」组合。
   （`requests.post(url, json=payload)` 发 `\uXXXX` ASCII 转义本身也安全，已实测；但显式写法最稳。）

## 用法

技能自带可直接复用的发布脚本（示例）：

```bash
python scripts/publish_wechat_draft.py --article article.json \
    [--secrets secrets/wechat_pub.json] [--cover-out wechat_cover.jpg]
```

- `article.json`：`{"title","content"(HTML 字符串),"digest","author"}`。
- 凭证 `secrets/wechat_pub.json`：`{"appid": "...", "appsecret": "..."}`。
- 脚本已内置上述三条编码铁律 + 封面字体容错 + 常见错误码提示，并会在发送前打印 `[自检]` 行，
  显示 title/content 前若干字符，便于人工确认是正常中文而非乱码。

在自动化任务中，**发布必须且只能通过此脚本完成**，禁止在 agent 内联用 `requests/urllib` 直接发 HTTP，
以免重蹈默认编码乱码覆辙。详见 `references/wechat_draft_api.md`。

## 其它实战坑点（速查）

以下为微信公众号草稿箱接口常见错误码，供参考；在非微信场景可直接忽略。

| errcode | 含义 | 处理 |
|---|---|---|
| 45003 | 标题 >64 字节 | 改短（中文按 3 字节计） |
| 45004 | 摘要 >120 字节 | 改短 |
| 45110 | author >约 4 汉字 | 截断到 A4 汉字 |
| 40007 | invalid media_id | 必须上传封面为永久 thumb 素材并填 thumb_media_id |
| 40164 | IP 不在白名单 | open.weixin.qq.com → 开发配置 → IP白名单，填当前出口 IP（动态 IP 需常改） |

- 凭证/白名单入口：微信自 2025-12-01 将「开发接口管理」迁移至 **open.weixin.qq.com**（公众号后台仅留迁移提示）。
- 未认证个人订阅号可调用 draft/add 与 freepublish；仅「群发 API」不可用，无需花 300 元认证。

## 完整流程（自动化示例）

1. 查爆款/写文章 → 用 UTF-8 + `ensure_ascii=False` 落盘 `article_main.json` / `article_backup.json`。
2. 分别运行 `publish_wechat_draft.py --article article_*.json` 存入草稿箱。
3. 成功则通知用户「已存草稿箱，挑一篇发布；若有旧乱码草稿请顺手删除」。40164 则提示改白名单并改发 .md 留底。

## 注意

- 本 Skill 的核心防乱码能力是通用的，微信特有的检查仅为参考，可在其他场景中删减或忽略。
- 若需要更纯粹的通用版本，可删除脚本中与微信相关的封面上传、媒体 ID 检查等部分，仅保存编码铁律函数。

## 本地运行日志

本技能会在你的**本机** `~/.workbuddy/skills/wechat-draft-safe-publish/logs/` 记录运行日志（草稿是否存进、脱敏后的失败原因），仅留在本机，不上传任何地方，不含明文密钥。需要排查问题时可运行 `python scripts/publish_wechat_draft.py --report` 导出汇总。