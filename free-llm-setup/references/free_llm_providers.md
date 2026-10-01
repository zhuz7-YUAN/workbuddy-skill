# 免费大模型平台参考手册（free-llm-setup v2.1）

更新：2026-09-13。免费额度与模型名单随时变动，**以各平台官网/控制台实时显示为准**。
接入时不要照抄本文件的模型名，脚本会先拉平台实时清单再实测。

---

## 0. 快速结论（2026-09 实测）

**首选路线：只拿一个 Key。** 聚合平台一个 Key 后面挂着几十上百个模型，比逐家注册省事得多。

| 拿几个 Key | 选谁 | 覆盖 | 官方依据 |
|---|---|---|---|
| **1 个（够用）** | **魔搭 ModelScope** | 48 个模型 | 每天 2000 次 API-Inference 免费调用、次日重置（全模型加总），单模型 ≤200~500 次/天；需绑阿里云账号 + 实名 |
| 加境外模型 | **OpenRouter** 或 **OrcaRouter** | 400+ / 195 个 | OpenRouter 带 `:free` 的免费；OrcaRouter `-free` 后缀与 `orcarouter/free` 走 $0 路由 |
| 大额体验旗舰 | **阿里云百炼** | 百余款 | 新用户每模型 100 万 Token、共 7000 万+，90 天有效；仅华北2（北京）地域 |

单家平台只在聚合平台覆盖不到时才需要（比如讯飞 Spark Lite 的"免费不限量"、小米 MiMo 的全模态）：

- **单家里能力最强**：智谱 GLM-4.7-Flash。永久免费、200K 上下文。
- **要长上下文 / 大额度**：美团 LongCat（1M）、小米 MiMo（1M）、火山方舟豆包（每日 200 万 Token）。
- **要快**：Groq（LPU，700+ token/秒）。
- **应急兜底**：讯飞 Spark Lite（免费不限量，但只有 8K 上下文）。

### 0.1 聚合平台实测数据（2026-09-13 本机）

| 平台 | 模型清单接口 | 直连实测 | 在线模型数 |
|---|---|---|---|
| 魔搭 ModelScope | `api-inference.modelscope.cn/v1/models` | **199ms** | 48 |
| OrcaRouter | `api.orcarouter.ai/v1/models` | 1230ms | 195 |
| OpenRouter | `openrouter.ai/api/v1/models` | 1770ms | 445（19 个 `:free`） |
| 阿里云百炼 | `dashscope.aliyuncs.com/compatible-mode/v1/models` | 需 Key（无 Key 返回 401） | 百余款 |

魔搭的 `/v1/models` **不需要 Token 也能拉**（48 个模型），但 `/chat/completions` 必须
Token + 绑定阿里云 + 实名，否则 401 `please bind your alibaba cloud account`。
所以判断魔搭的 Key 有没有配好，**不能只看能不能拉清单，必须发一次真实对话**。

### 0.2 聚合平台自动挑选机制

给聚合平台一个 Key，脚本按这个顺序挑要实测的模型：

1. 拉该平台实时在线清单（魔搭 / OpenRouter / OrcaRouter 免 Key 可拉）
2. 按平台配置里的 `prefer` 关键词顺序，逐个在清单里找命中项，凑够 `max_pick` 个
3. 并发实测（429/503 自动退避重试）
4. 通过的按延迟从快到慢写入 models.json

魔搭默认挑这 5 个：`deepseek-ai/DeepSeek-V4-Flash-0731` → `DeepSeek-V4-Pro` →
`Qwen/Qwen3-235B-A22B` → `ZhipuAI/GLM-5.2` → `Qwen/Qwen3-30B-A3B`。
想调整就在 `PROVIDERS["20"]["prefer"]` 改关键词，改完不用动别的。

---

## 1. 国内直连平台

### 1.0 魔搭 ModelScope（★★ 首推，一个 Token 通吃 48 个模型）

**这是"只拿一个 Key"的最佳答案。**

- 网址：`https://modelscope.cn` → 头像 → **「访问令牌」**创建（Token 形如 `ms-...`）
- OpenAI 兼容端点：`https://api-inference.modelscope.cn/v1/chat/completions`
- 模型清单：`https://api-inference.modelscope.cn/v1/models`（**不需要 Token 也能拉**）
- 额度（官方限流文档口径）：**账号每日总量 2000 次 API-Inference 调用，按自然日刷新**；
  单模型另有上限，最高不超过 500 次/天，部分热门大模型更低（如 200 次/天）。
  长期可用、每日回血，这是它区别于百炼（一次性 90 天）的核心优势。
- 实测（2026-09-13）在线 48 个模型，直连 199ms：
  `deepseek-ai/DeepSeek-V4-Flash-0731`、`deepseek-ai/DeepSeek-V4-Pro`、
  `Qwen/Qwen3-235B-A22B`、`ZhipuAI/GLM-5.2`、`Qwen/Qwen3-30B-A3B`、
  `MiniMax/MiniMax-M3`、`ZhipuAI/GLM-4.7-Flash` 等
- **两个必须知道的前提**
  1. **必须把 ModelScope 账号绑定到阿里云账号，并在阿里云侧完成实名认证**。
     没绑 → 每次都 401 `please bind your alibaba cloud account`；绑了没实名 → 同样不开通额度
  2. **判断 Key 配没配好不能只看 `GET /v1/models`** —— 这个接口即使 Token 无效也返回 200。
     必须发一次真实对话（脚本的实测环节正是这么做的）
- **别写错平台的 Key**：魔搭是 `ms-` 开头，和阿里云百炼的 `sk-` 不是一回事，
  两者是独立凭证，默认不通用

### 1.1 智谱 GLM（★ 首选）
- 官网/控制台：`https://bigmodel.cn`（拿 Key：控制台 → API Keys）
- OpenAI 兼容端点：`https://open.bigmodel.cn/api/paas/v4/chat/completions`
- 永久免费模型（2026-09 在线的）：`glm-4.7-flash`（文本主力，200K，主打编码与 Agent）、
  `glm-4-flash-250414`、`glm-4.6v-flash`（视觉）、`glm-4.1v-thinking-flash`、`CogView-3-Flash`（生图）
- **`glm-4.5-flash` 已下架、`glm-4.5-air` 是付费档** —— 新接代码别再写这两个 id
- 限制：免费档**限 1 并发**；海外直连延迟 200-500ms（服务器在国内）
- 付费升级阶梯：`glm-4.7-flashx`（~3 并发）→ `glm-4.7` → `glm-5.2`（每档输入价是上一档 5-10 倍，别乱升）
- 另提供 Anthropic Messages 兼容端点 `https://open.bigmodel.cn/api/anthropic`，Claude Code 可直切
- 注意：OpenRouter 上挂的 `z-ai/glm-4.7-flash` **不是 $0**（有中间价），要真免费必须走智谱官方端点

### 1.2 美团 LongCat 龙猫（★）
- 控制台：`https://longcat.chat/platform`（注册后自动生成名为 `default` 的 Key，也手动创建，最多 10 个）
- OpenAI 兼容端点：`https://api.longcat.chat/openai/v1/chat/completions`
  Anthropic 格式：`https://api.longcat.chat/anthropic/v1/messages`
- 模型：`LongCat-2.0`（1.6T MoE，激活约 48B，原生 1M 上下文，最大输出 128K，MIT 协议）
- 免费额度：公测期按天给，通用/思考/Omni/Chat-Exp 类约 **50 万 Token/天**，
  `Flash-Lite` 最高 **5000 万/天**；`LongCat-2.0-Preview` 需每天早上 9 点限量申请
- 定位：**Agentic 编程模型**，不是闲聊模型。SWE-bench Pro 59.5 / Terminal-Bench 70.8
- 注意：权重要走 HuggingFace 才能自部署（标注 coming soon），**目前只能用官方 API**
- 429 返回 `retry_after`，客户端应做指数退避

### 1.3 小米 MiMo（★）
- 控制台：`https://platform.xiaomimimo.com`（小米账号登录 → API Keys，Key 形如 `sk-xxx`）
- OpenAI 兼容端点：`https://api.xiaomimimo.com/v1/chat/completions`
  Anthropic 兼容：`https://api.xiaomimimo.com/anthropic`
  （Token Plan 订阅走另一域名 `https://token-plan-cn.xiaomimimo.com/v1`，Key 形如 `tp-xxx`）
- 模型：`mimo-v2.5-pro`（旗舰，1M 上下文，Agent/代码）、`mimo-v2.5`（全模态：文/图/音/视频）、
  `mimo-v2.5-tts`（语音合成，支持音色克隆）
- **`mimo-v2` 系列已于 2026-06-30 下线，旧模型名全部失效**
- 免费权益：新用户注册即送免费体验额度；MiMo Code 客户端限时免费通道；
  MiMo Claw 免费版每日 4 小时
- 付费参考（2026-05-27 永久降价，元/百万 token）：V2.5-Pro 输入 0.02(缓存命中)/5(未命中)、输出 36；
  V2.5 输入 0.02/1、输出 2
- 坑：多轮 Agent 会话若历史含工具调用，assistant 消息必须完整带上 `reasoning_content`，否则 400

### 1.4 火山方舟 豆包（★，额度最大）
- 控制台：`https://console.volcengine.com/ark`
- OpenAI 兼容端点：`https://ark.cn-beijing.volces.com/api/v3/chat/completions`
- 免费额度：个人开发者**每个模型每天约 200 万 Token**（2026-08 起由 50 万提到 200 万），
  新用户另叠加一次性 50 万赠额
- **必做步骤**：控制台 →「开通管理」→ 逐个开通想用的模型，否则鉴权过了也调不通
- 模型名以控制台为准（豆包 Seed 系列带版本后缀）

### 1.5 科大讯飞 星火（★，兜底）
- 控制台：`https://xinghuo.xfyun.cn` → 实名 → 各版本控制台页取 **APIPassword**
- OpenAI 兼容端点：`https://spark-api-open.xf-yun.com/v1/chat/completions`
- 模型名：`lite`（免费）、`generalv3`（Pro）、`generalv3.5`（Max）、`max-32k`、`pro-128k`、`4.0Ultra`
- 免费额度：个人实名后 **Spark Lite 永久免费且不限 Token，限 2 QPS**，上下文只有 8K、最大输出 4K；
  未实名账号可领 20 万临时 Token
- **最容易踩的坑**：填了 AppID/APIKey 而不是 APIPassword → 报 `apikey not found`。
  讯飞旧的 WebSocket 方式要 HMAC 签名，**别用旧方式**，直接用上面的 HTTP OpenAPI
- 注意：`Max` 版本套餐 2026-03-10 已下线（后端服务升级为 Ultra，额度合并）

### 1.6 百度千帆 文心
- 控制台：`https://console.bce.baidu.com/qianfan`；IAM 建 API Key：`https://console.bce.baidu.com/iam`
- OpenAI 兼容端点：`https://qianfan.baidubce.com/v2/chat/completions`
- 免费：**ERNIE-Speed / ERNIE-Lite / ERNIE-Tiny 系列长期免费**（`ernie-speed-8k`、`ernie-speed-128k`、
  `ernie-lite-8k`、`ernie-tiny-8k`）
- 三步必做：① 实名认证 ② IAM 建 API Key ③ 千帆控制台对目标型号点「**免费开通**」
- 免费的本质是**按速率封顶**（不是扣额度），所以上限是 RPM/TPM，不是 Token 总量
- 旗舰型号（ernie-4.0 等）收费，别当免费档

### 1.7 腾讯混元
- 端点：`https://api.hunyuan.cloud.tencent.com/v1/chat/completions`
- 免费：`hunyuan-lite` 长期免费；新用户另有约 500 万 Token 赠送（30 天）
- 混元也支持腾讯云 SDK 方式（SecretId/SecretKey），但 **OpenAI 兼容 + API Key 更简单**，优先用这个
- 中文理解好，微信生态相关开发顺手

### 1.8 阿里云百炼（★ 一个 Key 通吃百余款）

- 控制台：`https://bailian.console.aliyun.com`
- OpenAI 兼容端点：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- 模型清单：`https://dashscope.aliyuncs.com/compatible-mode/v1/models`（需 Key，无 Key 返回 401）
- 额度（官方帮助中心《新人免费额度》）：**首次开通自动发放，每个模型独立 100 万 Token，
  覆盖百余款共 7000 万+，有效期 90 天**，到期作废、不补发、不延期
- 覆盖：通义千问全系 + DeepSeek + Kimi + GLM + MiniMax 等第三方模型，一套接口全调
- **三个必须知道的前提**
  1. **只有华北2（北京）地域有免费额度**，其他地域调用直接计费
  2. 每个模型额度**互相独立、不互通**，某一款用完**不会自动切到别的**，要手动改 model 参数
  3. 带日期后缀的快照版本（如 `qwen-max-2026-05-17`）与不带日期的 `qwen-max` 视为两个模型，各自独立额度
- **2026-10-10 下线名单**：`qwen-turbo`、`qwen-vl-plus`、`qwen-audio-turbo` 等 30+ 老 id
  将停止服务，调用会报错，配置里别再写这些
- 报 401 排查顺序：地域是否切到华北2 → 是否点过「开通百炼」→ 阿里云是否完成实名

### 1.9 硅基流动 SiliconFlow（老牌聚合，一个 Key 94 个模型）
- 控制台：`https://cloud.siliconflow.cn`（**旧版 skill 的主力平台，保留**）
- OpenAI 兼容端点：`https://api.siliconflow.cn/v1/chat/completions`
- 免费区：**9B 及以下开源模型 ¥0 长期免费**，约 8 个，如 `Qwen/Qwen3-8B`、
  `Qwen/Qwen2.5-7B-Instruct`、`THUDM/GLM-4-9B-0414`、`THUDM/GLM-Z1-9B-0414`、
  `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`、`deepseek-ai/DeepSeek-OCR`
- 2026-09 实测在线 94 个模型；**已不存在** `Qwen/Qwen3.5-32B-Instruct`（旧清单里的错名字）
- 大参数模型（DeepSeek-V3.2、GLM-4.5-Air、Qwen2.5-72B 等）**会消耗赠送余额**，不是免费档
  —— 新用户实名送 16 元券，用完即止。**体检时"能调通"≠"免费"**，别把付费模型当免费在用
- 需实名认证后才能用免费模型
- **与魔搭的分工（重要）**：硅基流动免费档限流是**按速率**（约 30 次/分，不累计、无日上限），
  魔搭是**按天**（2000 次/天，耗尽要等次日）。所以**魔搭跑完当日额度后，硅基流动还能继续顶**。
  但硅基流动免费模型只有小模型，能力比魔搭免费池里的大模型差一档。

### 1.9b 魔搭 ModelScope（与硅基流动最易混，对照看）
- 端点：`https://api-inference.modelscope.cn/v1/chat/completions`
- **拿 Token 直达链接：`https://modelscope.cn/my/access/token`** → 「新建访问令牌」→ 复制 `ms-...`
  ⚠️ **别点左侧菜单的「API-Inference 提供方」**：那是配置外部 API Provider（BYOK，绑阿里云百炼 /
  DeepSeek / 可灵 / 美团龙猫 / MiniMax 等别家 Key）的页面，**不产生魔搭 Token**。用户最常卡在这。
  实测：令牌创建后可能只显示一次，当场复制；丢了就重新建一个。
- 一个 Token 覆盖在线 **48 个模型，全部免费**（含 DeepSeek-V4、Qwen3-235B、GLM-5.2、MiniMax-M3）
- 限流：**每天 2000 次**（账号总量），单模型另有约 200 次/天上限，**次日零点重置**（429 = 当日用完）
- 前置：注册 → **绑定阿里云** → 阿里云侧实名，否则一直 401
- ⚠️ **实测重要现象（2026-09-13 把 48 个模型全测了一遍）**：相当一部分模型返回
  **HTTP 200 但 `choices` 为 null、usage 全 0** —— 请求被收下却没有真推理。
  当天统计：**可用 19 / 空响应 22 / 报错 7**。
  - 空响应按"组"出现：**DeepSeek 全系、智谱全系、文心(PaddlePaddle)全系、阶跃全系、美团龙猫**
    当时全空；**Qwen 系可用率最高**（19 个可用里 13 个是 Qwen）。
  - **它会自己恢复**：`ZhipuAI/GLM-5.2` 起初连续 3 次空，几分钟后重测就通过了。属共享池额度的
    瞬时竞争，**不是模型下架，也不是 Key 的问题**——别据此以为账号坏了。
  - 报 400 `has no provider supported` = 该模型当前没有提供方（如 `MiniMax/MiniMax-M3`），换掉即可。
  - **应对**：一次多测几个候选（脚本已默认按目标量 3 倍挑候选），别只测 5 个——否则可能一个都留不下。
- **实测通过、值得优先用（2026-09-13）**：`Qwen/Qwen3-Coder-30B-A3B-Instruct`（579ms，最快）、
  `Qwen/Qwen3-Next-80B-A3B-Instruct`（702ms）、`Qwen/Qwen3-235B-A22B`、`Qwen/Qwen3.5-35B-A3B`、
  `Qwen/Qwen3.8-27B`、`Qwen/Qwen3.5-122B-A10B`、`ZhipuAI/GLM-5.2`
- 选谁：**主力用魔搭**（免费且含大模型），**硅基流动当备胎**（不限日次数的小模型 + 大模型付费兜底）

### 1.10 商汤 SenseNova
- 控制台：`https://platform.sensenova.cn` → 访问令牌
- 免费：多个模型**每 5 小时滚动额度**（不按天重置，用完等一会儿就回来），
  如 `sensenova-6.7-flash-lite` 1500 次/5h、`sensenova-u1-fast` 1500 次/5h（生图）
- 各模型额度独立计算，可错峰跑

### 1.11 阶跃星辰 StepFun
- 控制台：`https://platform.stepfun.com`
- OpenAI 兼容端点：`https://api.stepfun.com/v1/chat/completions`
- 免费：Step Plan 免费体验（15 天起，邀请好友可累计更长，活动口径最高 120 天）
- 模型：`step-3.7-flash`（原生多模态，面向 Agent，速度可达 400+ TPS）

### 1.12 DeepSeek 官方
- 端点：`https://api.deepseek.com/v1/chat/completions`
- 额度：新用户赠体验余额（金额以控制台为准），用完转付费
- **旧模型名 `deepseek-chat` 已于 2026-07-24 前后弃用**，新名 `deepseek-v4-flash`
- 定价极低（V4-Flash 输入 1 元/百万、输出 2 元/百万量级），代码能力公认强

---

## 2. 国外平台（有代理才顺）

### 2.0 OrcaRouter（一个 Key 覆盖 195 个模型，免信用卡）

- 网址：`https://orcarouter.ai` → 注册（**不需要信用卡**）→ 创建 Key（`sk-orca-...`）
- OpenAI 兼容端点：`https://api.orcarouter.ai/v1/chat/completions`
- 模型清单：`https://api.orcarouter.ai/v1/models`（**不需要 Key 也能拉**）
- 实测（2026-09-13）：**直连 1230ms，在线 195 个模型**
- 免费路由：后缀带 `-free` 的模型 ID，以及 `orcarouter/free` 自动路由别名，
  实测可用的有 `deepseek/deepseek-v4-flash-free`、`z-ai/glm-5.3-flash-free`、
  `tencent/hy3-free`；另有自研融合模型 `orcarouter/fusion` / `fusion-flash` / `fusion-mini`
- 限额策略：免费路由**周期性限速，超额返回 429，但不会扣余额**（429 是干净的配额信号）
- **风险提示（必须告诉用户）**：这是**第三方中转平台**，不是上游官方直连。
  稳定性、可用性、合规性都无保障（模型清单里还挂着 GPT / Claude / Gemini 系列，
  这类大概率不是官方通道）。**只适合当境外模型的补充，不要放重要用途**，
  也不要把敏感内容发给它

### 2.1 OpenRouter（★ 一个 Key 打通用境外池）
- 端点：`https://openrouter.ai/api/v1/chat/completions`，模型清单 `GET /api/v1/models`（**不需要 Key**）
- 注册：邮箱（**别点 Continue with Google**，Google 登录链路易卡）→ Keys → Create Key，得 `sk-or-v1-...`
- 免费：**带 `:free` 后缀的模型**。额度未充值 20 次/分、50 次/天；一次性充 $10（支持支付宝）
  累计升级到 1000 次/天，**余额不会被免费模型消耗**
- 免费池 2026-09-13 实测在线（约 19 个，每日变动），当日常用的：
  `nvidia/nemotron-3-ultra-550b-a55b:free`(1M)、`nvidia/nemotron-3.5-lightning:free`(1M)、
  `thinkingmachines/inkling:free`(1M)、`inclusionai/ling-3.0-flash-vl:free`(262K，视觉)、
  `google/gemma-4-31b-it:free`(262K)、`nvidia/nemotron-3-super-120b-a12b:free`(262K)、
  `liquid/lfm-2.5-2.6b:free`(极快小模型)
- **`z-ai/glm-5.2:free` 已退出免费池**（返回 404 "unavailable for free"）——这是很多人配置里烂着的死条目
- 429 = 共享池限流（全球用户挤同一池），与个人频率关系不大，换个免费模型即可
- 网络：API 通常可直连（本机实测直连 2.2s、走系统代理 1.1s → **代理更快**）；
  网页有 Cloudflare 人机验证，国内浏览器可能卡验证页 —— **打不开网页不代表 API 不通**

### 2.2 Groq（★ 最快）
- 控制台：`https://console.groq.com`（可用 Google 账号）→ API Keys，Key 形如 `gsk_...`
- 端点：`https://api.groq.com/openai/v1/chat/completions`
- 免费：永久免费层，**按模型逐个限流**（如小模型 30 次/分、14400 次/天；GPT-OSS 120B 约 1000 次/天）
- LPU 加速，700+ token/秒，低延迟场景首选
- 模型名：`llama-3.3-70b-versatile`、`openai/gpt-oss-120b`、`openai/gpt-oss-20b`、`llama-3.1-8b-instant`

### 2.3 Cerebras
- 控制台：`https://cloud.cerebras.ai` → API Keys，Key 形如 `csk-...`
- 端点：`https://api.cerebras.ai/v1/chat/completions`
- 免费：每天约 100 万 Token（以官网为准），吞吐极高
- 模型：`gpt-oss-120b`、`gpt-oss-20b`、`llama-3.3-70b`、`qwen-3-32b`

### 2.4 Mistral 官方
- 控制台：`https://console.mistral.ai` → API Keys
- 端点：`https://api.mistral.ai/v1/chat/completions`
- 免费：每月约 **10 亿 Token**（1 RPS / 50 万 TPM），**需手机号验证 + 同意数据用于训练**
- 模型：`mistral-small-latest`、`open-mistral-nemo`、`mistral-large-latest`
- 本机实测：**只有走代理才通**（直连超时）

### 2.5 NVIDIA NIM
- 控制台：`https://build.nvidia.com` → 任意模型页 Get API Key，Key 形如 `nvapi-...`
- 端点：`https://integrate.api.nvidia.com/v1/chat/completions`
- 额度：注册送 1000 credits，多数开源模型可免费试

### 2.6 GitHub Models
- 控制台：GitHub → Settings → Developer settings → Fine-grained tokens → 勾 **Models: Read**
- 端点：`https://models.github.ai/inference/chat/completions`
- 免费：GitHub 账号即可调用 GPT-4.1 / GPT-4o / Llama / Mistral 等，限额与账号档位挂钩

### 2.7 Google Gemini（风控高，高级选项）
- AI Studio：`https://aistudio.google.com` → Get API Key，得 `AIzaSy...`
- OpenAI 兼容端点：`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
- 地域：不支持中国大陆；免费层另禁 EU/UK/瑞士。需海外 IP，住宅 IP 通过率远高于机房 IP
- 节点参考：新加坡 ~90% > 日本 ~85% > 美国 ~70-80%；固定一个节点，关智能路由

#### 2.7.1 2026 年 Google 新分层政策（实测结论）
1. "new user" 判定看**项目是否绑结算账户**，不是注册时间。未绑卡项目：旧模型（2.5 系列等）
   一律 404「不再向新用户开放」，新模型（3.x）一律 403「项目被拒」——**免费层实际为零**。
2. AI Studio 项目页显示「受限·不可用 / 设置结算信息」就是此状态，不是用户操作错了。
3. 解锁唯一路径 = 绑结算账户（绑后免费配额照旧，可设 0 元预算提醒防扣费）。
4. 绑不过或不想绑 → 直接走其他平台，别死磕。
5. 另：Gemini 2.5 Pro / 3.1 Pro 自 2026-04-01 起已移除免费层。

---

## 3. 通道与代理（v2.0 的通道竞速机制）

### 3.1 通道怎么选
脚本对每一个服务，让「直连」和「检测到的各代理」**各打一枪**（GET 该平台的 models 端点，
401/403 也算"通了"，因为那只说明没带 Key，网络是通的），取**延迟最低**的那条，结果按 URL 缓存。
所以是「谁快用谁」，不是「有代理就一定走代理」。

### 3.2 代理从哪来（三层，全自动）
1. 环境变量：`HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`（含小写）
2. Windows 系统代理：注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
   的 `ProxyEnable` + `ProxyServer`
3. 扫本机端口：`7890, 7897, 7891, 10809, 10808, 1080, 2080, 8889, 50008, 20171, 8080, 8118`
   （**Clash for Windows 自定义端口常见 50008**）

> 端口开着 ≠ 能代理。脚本会真发一次请求验证，探不通的通道会被自动淘汰
> （本机实测 8080 端口开着但不转发，已被正确剔除）。

### 3.3 2026-09-13 本机实测通道对照（示例，仅供参考）

| 平台 | 直连 | 环境变量代理 | 系统代理 |
|---|---|---|---|
| 硅基流动 | ✓476ms | ✓293ms | ✓307ms |
| OpenRouter | ✓2255ms | ✓1939ms | **✓1082ms** |
| 智谱 GLM | ✓400ms | ✓388ms | ✓346ms |
| 美团 LongCat | ✓386ms | ✓383ms | ✓336ms |
| 小米 MiMo | ✓379ms | ✓371ms | ✓304ms |
| Groq | **✓699ms** | ✓621ms | ✓1270ms |
| Cerebras | ✓1144ms | ✓1045ms | ✓1302ms |
| NVIDIA NIM | ✓1036ms | ✓1537ms | ✓1995ms |
| GitHub Models | ✓1192ms | ✓1089ms | ✓978ms |
| Mistral | ✗ | ✗ | ✓918ms（**只有代理通**） |
| Gemini | ✗ | ✗ | ✗（网络不通） |

结论：多数国外平台在国内**可直连**，但挂了代理可能更快；Mistral 必须走代理；
Gemini 在当前网络下完全不通。**这就是为什么要做通道竞速，而不是让用户自己猜。**

---

## 4. models.json 写入规范（脚本自动处理，手动改时参考）

- 双路径：`~/.codebuddy/models.json` 与 `~/.workbuddy/models.json`（**两份都要写**）
- 条目字段：`id`（模型完整 ID，OpenRouter 的要带 `:free`）、`name`（显示名）、`vendor`、
  `apiKey`、`maxInputTokens`、`maxOutputTokens`、`url`（chat/completions 完整地址）、
  `temperature`、`supportsToolCall`、`supportsImages`
- 改动前先备份为 `.bak-时间戳`；同 `id` 覆盖、其余保留（**合并而非重写**）
- 写入顺序 = **实测延迟从快到慢**，所以模型选择器里排第一的就是最快的
- 同平台已下架的旧条目会在写入时自动清理（只动该平台 url 的条目，不碰其他来源）
- 写入后必须**完整退出并重开 WorkBuddy**，模型选择器才会刷新
- 想复查有没有死条目：`python scripts/setup_free_llm.py --doctor`

---

## 5. 安全提醒

- API Key 等同于账户钥匙：只写进本机 models.json，**不要贴进公开文档、不要随 Skill 打包发布**。
- 免费档的输入/输出**可能被平台用于产品改进**（各平台条款不同），敏感数据慎用免费档。
- 多数平台免费额度**不允许商用**。
- 别在脚本或代码里硬编码 Key，用环境变量或本机配置文件。
