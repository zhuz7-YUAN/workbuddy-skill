# 公众号自动发稿避坑指南（references）

本技能三个脚本的实战经验沉淀。AI 遇到报错先查这里。

## 1. 编码乱码（已根治，但要知道原理）

乱码链路：Windows 上 `open(path,'w')` 默认 GBK 写入 → 另一处按 UTF-8 读 → 全部变成 `æ‰‹æœº` 这种鬼字。

铁律（新写任何脚本必须遵守）：
- 写 JSON：`Path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")`
- 读 JSON：先 UTF-8，`UnicodeDecodeError` 时回退 `gb18030`
- 发 HTTP JSON：`json.dumps(payload, ensure_ascii=False).encode("utf-8")` + 头 `Content-Type: application/json; charset=utf-8`
- 脚本入口加 `sys.stdout.reconfigure(encoding="utf-8")`

## 2. 微信接口错误码表

| 错误码 | 含义 | 修法 |
|---|---|---|
| 40164 | IP 不在白名单 | open.weixin.qq.com（2025年12月起接口管理迁到这里，不再在 mp 后台）→ 开发接口管理 → IP 白名单 → 加上报错里提到的 IP。家庭宽带 IP 会变，变了就再加 |
| 40001/40125 | AppSecret 错 | 复制不完整或重置过，重新复制。重置后旧 Secret 立即失效 |
| 40013 | AppID 错 | 核对 wx 开头整串 |
| 45003 | 标题超长 | 标题 ≤ 64 汉字 |
| 45004 | 摘要超长 | digest ≤ 120 汉字 |
| 45110 | author 超长 | ≤ 4 汉字（脚本已自动截断） |
| 48001 | API 无权限 | 个人未认证订阅号部分接口受限；草稿箱 draft/add 通常可用 |
| 40007 | media_id 无效 | 封面上传失败后旧 id 被复用，重跑整条流程 |
| 45009 | 接口调用次数超限 | access_token 有每日限额，别短时间反复重跑 |

## 3. access_token 注意

- 有效期 7200 秒，**每次发稿现取现用即可**，别缓存（缓存反而易过期踩坑）
- 每天获取次数有限额（约2000次），正常使用碰不到

## 4. 封面图

- 草稿必须带 `thumb_media_id`，所以要先生成封面并上传为永久素材
- 本技能自动生成 300×300 纯色+标题字封面；想换高级封面，改 `make_cover` 或让 AI 用 ImageGen 生成后替换
- 中文字体找不到时自动降级为英文占位（不出现方块乱码）
- 上传的永久素材会累积在公众号素材库，定期去后台清理

## 5. 平台规则

- 草稿箱 ≠ 发表：存草稿无限次；点「发表」才是群发（订阅号每天 1 次群发额度）
- 本技能设计上**永不代替用户点发表**——最后一步必须本人到后台确认
- 个人订阅号（未认证）可以用「设置与开发 → 基本配置」里的 AppID/Secret 调草稿箱接口

## 6. 红狐选题接口

- 端点：`https://redfox.hk/story/api/gzhData/searchArticle`，POST，头 `X-API-KEY`
- code=2000 才是成功；Key 过期/欠费会返回其他 code
- sortType=`_4` 按热度排
- 该功能可选：没有 Key 用 AI 联网搜索热点替代即可

## 7. 定时自动化

用 WorkBuddy「自动化」功能建每日任务：提示词写清「跑 publish_draft.py 存草稿，不发表」。提醒用户草稿箱里攒多了要定期清理。

## 8. 密钥安全

- secrets/wechat_pub.json 只存在本机，**永远不进发布包**
- 打包前安检命令（SKILL.md 文末）必须执行
- 用户把 Secret 发到对话里是本技能的设计流程，但 AI 要提醒他别发去其他群聊
