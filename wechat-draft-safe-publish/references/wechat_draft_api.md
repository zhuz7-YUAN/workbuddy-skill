# 微信公众号草稿箱（draft/add）接口避坑清单

微信公众平台「草稿箱」接口：`POST https://api.weixin.qq.com/cgi-bin/draft/add?access_token=ACCESS_TOKEN`

未认证的个人订阅号也能调用 draft/add 与 freepublish；只有「群发 API」对未认证号不可用。故无需花 300 元认证即可实现「生成 → 存草稿箱 → 自己点发布」。

## 一、编码（最容易踩、且表现为"全文乱码"）

**根因（真实发生过的事故）**：
- Python 在 Windows 上 `open(path,'w')` 默认编码是 **GBK/cp936**。若用这种方式写中文 JSON，文件里是 GBK 字节。
- 若读取端用 `encoding="utf-8"` 去读 GBK 字节，会把字节错当成 UTF-8 解码 → 字符串在加载时就已经是乱码 → 再原样发给微信，草稿箱全文乱码。
- 「先 GBK 写、再 UTF-8 读」这一对组合，是乱码的最常见来源。

**铁律**（任何环节都适用）：
1. 写 JSON：`open(path,'w',encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))`。禁止 `open(path,'w')` 默认编码；`ensure_ascii=False` 保留中文原文。
2. 读 JSON：先 `utf-8`，失败回退 `gb18030`（用于修复历史被 GBK 写入的文件）。
3. 发 HTTP：用 `json.dumps(payload, ensure_ascii=False).encode('utf-8')` 作为请求体，并带显式 `Content-Type: application/json; charset=utf-8`。
   - 说明：`requests.post(url, json=payload)` 会发纯 ASCII 的 `\uXXXX` 转义，本身也是安全的（已实测）；但显式 `ensure_ascii=False` + `charset=utf-8` 最稳妥、最不易被中间层误判。两者均可，关键是**不要**出现「原始 UTF-8 字节 + 无 charset 头」的组合。

## 二、字段限制（触发特定 errcode）

| errcode | 含义 | 处理 |
|---|---|---|
| 45003 | 标题超长（>64 字节，注意是字节不是字符） | 标题改短；中文按 3 字节计 |
| 45004 | 摘要(digest)超长（>120 字节） | 摘要改短 |
| 45110 | author 字段超长（限约 8 字节 / 4 汉字） | author 截断到 4 个汉字以内 |
| 40007 | invalid media_id | draft/add 必须带 `thumb_media_id`（封面），且须先上传为永久素材 type=thumb |
| 40164 | IP 不在白名单 | 到 open.weixin.qq.com → 管理中心 → 公众号 → 开发配置 → IP白名单，填当前宽带出口 IP。家庭动态 IP 需常改；缓存/同步可能延迟，改完稍等重试 |

## 三、最小必填 articles 字段

```
{
  "articles": [{
    "title": "...",
    "author": "祝",            # 务必 ≤4 汉字
    "digest": "...",           # ≤120 字节
    "content": "<p>HTML 正文</p>",
    "content_source_url": "",
    "thumb_media_id": "<上传封面拿到的 media_id>",
    "show_cover_pic": 1,
    "need_open_comment": 0,
    "only_fans_can_comment": 0
  }]
}
```

- `content` 支持 HTML 标签（`<p>`、`<br/>`、`<img>` 等），直接给 HTML 字符串即可，不要再做 HTML 转义。
- 封面必须先在 `material/add_material?type=thumb` 上传为**永久**素材，拿到 `media_id` 再填入 `thumb_media_id`。

## 四、凭证与入口（2025-12 起已迁移）

- AppID 公开；AppSecret 在「开发接口管理」内点「查看」扫码后显示一次，需妥善保存。
- 微信已于 **2025-12-01** 将「开发接口管理」从公众号后台迁移至 **微信开发者平台 open.weixin.qq.com**（公众号后台仅留迁移提示）。AppSecret / IP 白名单等现在在 open.weixin.qq.com 的「管理中心 → 公众号 → 开发配置」中查看。

## 五、日常排错顺序

1. 先核对 title/author/digest 字节长度（45003/45004/45110）。
2. 再核对封面 thumb_media_id 是否上传成功（40007）。
3. 最后查 IP 白名单（40164）——动态宽带 IP 最常见。
4. 若草稿正文乱码：几乎必定是「写文件编码」或「发请求编码」问题，回到第一节铁律。
