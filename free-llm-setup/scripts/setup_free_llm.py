#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免费大模型一键接入 WorkBuddy  v2.0

用法:
  交互模式(自己跑):   python setup_free_llm.py
  单平台(AI 代跑):    python setup_free_llm.py --provider 1 --key sk-xxxx
  多平台(AI 代跑):    python setup_free_llm.py --batch "1=sk-xx,8=xxx,15=xxx"
  网络体检(不写配置): python setup_free_llm.py --probe
  看某平台模型清单:   python setup_free_llm.py --list 3 --key xxx
  体检已写入的模型:   python setup_free_llm.py --doctor
  本地运行日志:       python setup_free_llm.py --report

可选参数:
  --proxy auto            自动探测本机代理(默认; 扫端口 + 读系统/环境变量)
  --proxy http://127.0.0.1:50008   指定代理
  --no-proxy              强制直连, 不探测代理
  --deep                  额外做一次流式(stream)实测, 与 WorkBuddy 实际用法一致
  --no-prune              写入时不清理该平台已下架的旧条目
  --only 14,15            probe/doctor 时只处理指定平台

仅用 Python 标准库, 无第三方依赖, 不联网上传任何数据。
"""
import concurrent.futures
import datetime
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # 防 Windows GBK 控制台中文乱码

# 使用日志自动记录 (脱敏, 存用户本机)
try:
    from usage_logger import log_event, print_report
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from usage_logger import log_event, print_report

SKILL_NAME = "free-llm-setup"

MODELS_JSON_PATHS = [
    os.path.join(os.path.expanduser("~"), ".codebuddy", "models.json"),
    os.path.join(os.path.expanduser("~"), ".workbuddy", "models.json"),
]

# ---------- 全局运行态 ----------

MODE = "interactive"     # interactive | param
PROXIES = {}             # 当前生效代理(空字典=直连)
PROXY_MODE = "auto"      # auto | off | manual
PROXY_CANDIDATES = []    # [(label, proxies_dict), ...]
CHANNEL_CACHE = {}       # url -> (proxies, label, ms)
DEEP = False
PRUNE = True

# 本机常见代理端口(Clash / v2ray / SS / 系统代理)。Clash for Windows 自定义端口常见 50008
COMMON_PROXY_PORTS = [7890, 7897, 7891, 10809, 10808, 1080, 2080, 8889, 50008, 20171, 8080, 8118]


# ================= HTTP 基础 =================

def http_json(method, url, key=None, payload=None, timeout=30, proxies=None,
              extra_headers=None):
    """发请求, 返回 (status, dict_or_None, raw_text, 耗时毫秒)。连接层异常抛出。"""
    px = PROXIES if proxies is None else proxies
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("User-Agent", "free-llm-setup/2.0")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    t0 = time.time()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(px or None))
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            ms = int((time.time() - t0) * 1000)
            try:
                return resp.status, json.loads(text), text, ms
            except ValueError:
                return resp.status, None, text, ms
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        ms = int((time.time() - t0) * 1000)
        try:
            return e.code, json.loads(text), text, ms
        except ValueError:
            return e.code, None, text, ms


def err_text(status, j, raw):
    """从响应里抽一句人话错误。注意 j 可能是 list/str, 不一定 dict。"""
    if isinstance(j, dict):
        if isinstance(j.get("error"), dict):
            return str(j["error"].get("message", ""))[:70]
        if j.get("error"):
            return str(j["error"])[:70]
        if j.get("message"):
            return str(j["message"])[:70]
    if raw:
        return re.sub(r"\s+", " ", raw)[:70]
    return ""


# ================= 代理探测 / 通道竞速 =================

def _norm_proxy(p):
    p = (p or "").strip()
    if not p:
        return ""
    if "://" not in p:
        p = "http://" + p
    return p


def env_proxies():
    out = []
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
              "ALL_PROXY", "all_proxy"):
        v = os.environ.get(k)
        if v:
            out.append(_norm_proxy(v))
    return out


def system_proxy():
    """读 Windows 系统代理设置(注册表)。非 Windows 或没开则返回 []。"""
    if not sys.platform.startswith("win"):
        return []
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
        if not enable:
            return []
        server, _ = winreg.QueryValueEx(k, "ProxyServer")
    except Exception:
        return []
    out = []
    if server and "=" in server:
        for part in server.split(";"):
            if "=" in part:
                out.append(_norm_proxy(part.split("=", 1)[1]))
    elif server:
        out.append(_norm_proxy(server))
    return out


def scan_local_proxy_ports(timeout=0.35):
    """并发扫本机常见代理端口, 返回开放端口列表。"""
    def probe(port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return port
        except Exception:
            return None

    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for r in ex.map(probe, COMMON_PROXY_PORTS):
            if r:
                found.append(r)
    return found


def build_proxy_candidates(verbose=True):
    """构建通道候选: 直连 + 各类代理。只做端口/配置层面的筛选, 不做慢速网络验证。"""
    global PROXY_CANDIDATES
    cands = [("直连", {})]
    seen = set()

    def add(label, proxy):
        p = _norm_proxy(proxy)
        if not p or p in seen:
            return
        seen.add(p)
        cands.append((label, {"http": p, "https": p}))

    if PROXY_MODE == "off":
        PROXY_CANDIDATES = [("直连", {})]
        return PROXY_CANDIDATES

    if PROXY_MODE == "manual":
        add("指定代理", list(PROXIES.values())[0] if PROXIES else "")
        PROXY_CANDIDATES = cands
        return PROXY_CANDIDATES

    # auto: 环境变量 -> 系统代理 -> 扫端口
    for p in env_proxies():
        add("环境变量代理", p)
    for p in system_proxy():
        add("系统代理", p)
    ports = scan_local_proxy_ports()
    for port in ports:
        add("本机代理:%d" % port, "http://127.0.0.1:%d" % port)
    if verbose and len(cands) > 1:
        print("[i] 检测到 %d 条可用通道: %s" % (
            len(cands), ", ".join(c[0] for c in cands)))
    elif verbose:
        print("[i] 未检测到本机代理, 走直连(有代理可在启动前打开, 或加 --proxy)")

    PROXY_CANDIDATES = cands
    return PROXY_CANDIDATES


def ping_url(url, proxies, key=None, timeout=6):
    """只判断「这个通道能不能到达这个服务」并测延迟。
    返回 (reachable, ms, status)。注意: 401/403 也算可达(说明网络通了, 只是没带 Key)。"""
    t0 = time.time()
    try:
        status, _j, _raw, _ms = http_json("GET", url, key, None, timeout,
                                         proxies, {"Accept": "application/json"})
        return True, int((time.time() - t0) * 1000), status
    except Exception:
        return False, 0, 0


def resolve_channel(url, key=None, timeout=6, verbose=True):
    """为一个服务挑最快通道: 直连 vs 各代理, 各打一枪, 取延迟最低且可达的。
    结果按 url 缓存, 避免每个模型都重测一遍。"""
    global PROXIES
    if url in CHANNEL_CACHE:
        PROXIES = CHANNEL_CACHE[url][0]
        return CHANNEL_CACHE[url]

    if PROXY_MODE == "off" or len(PROXY_CANDIDATES) <= 1:
        px, label, ms = PROXIES, ("指定代理" if PROXY_MODE == "manual" else "直连"), 0
        CHANNEL_CACHE[url] = (px, label, ms)
        return CHANNEL_CACHE[url]

    results = []
    def one(item):
        label, px = item
        ok, ms, status = ping_url(url, px, key, timeout)
        return (ok, ms, status, label, px)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROXY_CANDIDATES)) as ex:
        for ok, ms, status, label, px in ex.map(one, PROXY_CANDIDATES):
            if ok:
                results.append((ms, label, px, status))

    if not results:
        if verbose:
            print("[!] 所有通道都连不上该服务, 仍按直连重试")
        CHANNEL_CACHE[url] = (PROXIES, "直连(未通)", 0)
        return CHANNEL_CACHE[url]

    results.sort(key=lambda x: x[0])
    ms, label, px, status = results[0]
    PROXIES = px
    if verbose:
        detail = " | ".join("%s:%dms" % (r[1], r[0]) for r in results)
        print("[i] 通道竞速 -> 选中【%s】%dms   (%s)" % (label, ms, detail))
    CHANNEL_CACHE[url] = (px, label, ms)
    return CHANNEL_CACHE[url]


# ================= 模型实测 =================

def test_model(base_url, key, model, timeout=30, retries=2):
    """发一条最小对话。返回 (ok, 说明, 毫秒)。
    429/503 属于免费池常态, 按 retry_after 退避重试。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "说两个字:成功"}],
        "max_tokens": 16,
    }
    last = (False, "未执行", 0)
    for attempt in range(retries + 1):
        try:
            status, j, raw, ms = http_json("POST", base_url, key, payload, timeout)
        except Exception as e:
            last = (False, "连接失败(%s)" % repr(e)[:50], 0)
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            return last
        if status == 200 and isinstance(j, dict) and j.get("choices"):
            txt = ""
            try:
                txt = (j["choices"][0]["message"].get("content") or "")[:12]
            except Exception:
                pass
            return True, txt or "OK", ms
        # 魔搭等平台会返回 200 但 choices 为空 —— 请求被收下却没有真推理
        # (usage 也全是 0)。重试无用, 直接判为"该模型当前不可用"。
        if status == 200 and isinstance(j, dict) and "choices" in j and not j.get("choices"):
            return False, ("空响应(choices 为空): 该模型当前不可用 —— 多半是它今日的"
                           "免费额度已满, 或服务未就绪; 稍后重试或换同平台别的模型"), ms
        msg = err_text(status, j, raw)
        last = (False, "HTTP %s %s" % (status, msg), ms)
        if status in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        return last
    return last


def test_model_stream(base_url, key, model, timeout=25):
    """--deep 时用: 发一次 stream=true 的请求(WorkBuddy 真实用法)。返回 (ok, 说明)。"""
    payload = {"model": model, "messages": [{"role": "user", "content": "hi"}],
               "max_tokens": 1, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("Authorization", "Bearer " + key)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(PROXIES or None))
        with opener.open(req, timeout=timeout) as resp:
            chunk = resp.read(256)
            if b"data:" in chunk or b'"choices"' in chunk:
                return True, "流式OK"
            return False, "无流式数据"
    except Exception as e:
        return False, "流式失败(%s)" % repr(e)[:40]


def fetch_model_list(list_url, key=None, timeout=20):
    """拉平台在线模型清单, 返回 {model_id: meta} 或 None。"""
    try:
        status, j, _raw, _ms = http_json("GET", list_url, key, None, timeout)
    except Exception:
        return None
    if status != 200 or not isinstance(j, dict):
        return None
    data = j.get("data")
    if not isinstance(data, list):
        return None
    out = {}
    for m in data:
        if isinstance(m, dict) and m.get("id"):
            out[m["id"]] = m
    return out or None


# ================= 平台清单 =================
# 字段: title/home/base/list/key_hint/howto/quota/ctx_in/ctx_out/tools/vision
#      needs_key_for_list / candidates(可 str 或 dict)
# candidates 里的 dict 支持: id / ctx / out / vision / tools

VISION_HINTS = ("-vl", "vl-", "vision", "omni", "gemini", "gemma", "gpt-4o",
                "gpt-5", "claude", "glm-4.6v", "glm-4.1v", "glm-4v",
                "qwen-vl", "doubao", "seed", "step-3.7", "sensenova-6.7",
                "mimo-v2.5", "internvl", "llava")

PROVIDERS = {
    # ---------------- 国内: 直连, 无需代理 ----------------
    "1": {
        "title": "硅基流动 SiliconFlow",
        "base": "https://api.siliconflow.cn/v1/chat/completions",
        "list": "https://api.siliconflow.cn/v1/models",
        "key_hint": "sk-...",
        "howto": "siliconflow.cn 手机号注册 -> 实名 -> 控制台「API 密钥」新建",
        "quota": "9B 及以下开源模型 ¥0 长期免费(大参数模型会用赠送余额)",
        "ctx_in": 128000, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "Qwen/Qwen3.5-9B", "ctx": 128000},
            {"id": "Qwen/Qwen3-8B", "ctx": 32768},
            {"id": "Qwen/Qwen2.5-7B-Instruct", "ctx": 32768},
            {"id": "THUDM/GLM-4-9B-0414", "ctx": 32768},
            {"id": "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", "ctx": 131072},
        ],
        "note": "这里只列 ¥0 免费档小模型; 想要 DeepSeek-V3.2 等大模型，"
                "会消耗注册赠送余额，可在 --list 1 里查到名字后手工加",
    },
    "4": {
        "title": "智谱 GLM",
        "base": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "list": "https://open.bigmodel.cn/api/paas/v4/models",
        "key_hint": "...  (形如 xxxx.xxxx)",
        "howto": "bigmodel.cn 手机号注册 -> 控制台「API Keys」-> 新建",
        "quota": "GLM-4.7-Flash 永久免费(200K上下文, 限 1 并发); 新用户另送大额 Token",
        "ctx_in": 200000, "ctx_out": 16384, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "glm-4.7-flash", "ctx": 200000},
            {"id": "glm-4-flash-250414", "ctx": 128000},
            {"id": "glm-4.6v-flash", "ctx": 128000, "vision": True},
        ],
    },
    "5": {
        "title": "百度千帆 文心",
        "base": "https://qianfan.baidubce.com/v2/chat/completions",
        "list": "https://qianfan.baidubce.com/v2/models",
        "key_hint": "bce-v3/ALTAK-.../...",
        "howto": ("console.bce.baidu.com 实名 -> IAM 创建 API Key -> 千帆控制台"
                  "对 ERNIE-Speed/Lite/Tiny 点「免费开通」"),
        "quota": "ERNIE-Speed/Lite/Tiny 系列长期免费(按速率封顶, 不是按额度扣)",
        "ctx_in": 128000, "ctx_out": 4096, "tools": False, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "ernie-speed-128k", "ctx": 128000, "tools": False},
            {"id": "ernie-speed-8k", "ctx": 8192, "tools": False},
            {"id": "ernie-lite-8k", "ctx": 8192, "tools": False},
        ],
    },
    "6": {
        "title": "腾讯混元",
        "base": "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",
        "list": "https://api.hunyuan.cloud.tencent.com/v1/models",
        "key_hint": "sk-...",
        "howto": "腾讯云控制台搜「混元大模型」-> 开通 -> API Key 管理 -> 新建",
        "quota": "hunyuan-lite 长期免费; 新用户另有赠额",
        "ctx_in": 32768, "ctx_out": 4096, "tools": False, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "hunyuan-lite", "tools": False},
            {"id": "hunyuan-turbos-latest", "tools": False},
        ],
    },
    "7": {
        "title": "美团 LongCat 龙猫",
        "base": "https://api.longcat.chat/openai/v1/chat/completions",
        "list": "https://api.longcat.chat/openai/v1/models",
        "key_hint": "...  (控制台 API Keys 页创建)",
        "howto": "longcat.chat/platform 注册 -> API Keys -> 创建(Key 只显示一次)",
        "quota": "公测期每日免费 Token(通用/思考类约 50 万, Flash-Lite 最高 5000 万)",
        "ctx_in": 1000000, "ctx_out": 65536, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "LongCat-2.0", "ctx": 1000000},
        ],
    },
    "8": {
        "title": "科大讯飞 星火",
        "base": "https://spark-api-open.xf-yun.com/v1/chat/completions",
        "list": "https://spark-api-open.xf-yun.com/v1/models",
        "key_hint": "...  (控制台里的 APIPassword)",
        "howto": ("xinghuo.xfyun.cn 注册 -> 实名 -> 各版本控制台页拿 HTTP 服务的 "
                  "APIPassword(注意: 不是 AppID/APIKey)"),
        "quota": "Spark Lite 永久免费且不限 Token(限 2 QPS); 新用户另有 X 系列额度",
        "ctx_in": 8000, "ctx_out": 4096, "tools": False, "vision": False,
        "needs_key_for_list": False,
        "geo": "cn",
        "candidates": [
            {"id": "lite", "ctx": 8000, "tools": False},
            {"id": "generalv3.5", "ctx": 8192, "tools": True},
        ],
        "check_ok": True,   # 该平台响应体是 {code:0,...}, 不以 choices 为唯一判据
    },
    "9": {
        "title": "阿里云百炼【一个Key通吃】",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "list": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "key_hint": "sk-...",
        "howto": ("bailian.console.aliyun.com 开通(选华北2北京地域才有免费额度) "
                  "-> API-KEY 管理 -> 创建"),
        "quota": ("一个 Key 覆盖百余款模型(通义千问全系 + DeepSeek + Kimi + GLM + "
                  "MiniMax); 新用户每模型 100 万 Token、共 7000 万+, 90 天有效"),
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "agg": True,
        "max_pick": 5,
        "candidates": [
            {"id": "qwen3.7-max", "ctx": 131072},
            {"id": "qwen3.6-flash", "ctx": 131072},
            {"id": "qwen3-max", "ctx": 131072},
            {"id": "deepseek-v4-pro", "ctx": 131072},
            {"id": "kimi-k2.5", "ctx": 131072},
        ],
        "note": ("免费额度只在华北2(北京)地域生效; 每个模型额度独立、不互通, "
                 "某一款用完不会自动切到别的; qwen-turbo 等老 id 将在 2026-10-10 下线"),
        "err_hint_401": ("百炼报 401: 确认三点 —— ①控制台左上角地域切到「华北2(北京)」; "
                         "②已点过「开通百炼」; ③阿里云账号已完成实名认证。"),
    },
    "10": {
        "title": "火山方舟 豆包",
        "base": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "list": "https://ark.cn-beijing.volces.com/api/v3/models",
        "key_hint": "...  (方舟控制台 API Key)",
        "howto": ("console.volcengine.com/ark 开通 -> 先在「开通管理」把想用的模型"
                  "开通 -> API Key 管理新建"),
        "quota": "每模型每天约 200 万 Token 循环免费; 新用户另有一次赠送",
        "ctx_in": 262144, "ctx_out": 16384, "tools": True, "vision": True,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "doubao-seed-2-0-pro", "ctx": 262144, "vision": True},
            {"id": "doubao-seed-2-0-lite", "ctx": 262144, "vision": True},
        ],
        "note": "火山方舟必须在控制台逐个「开通」模型后才能调; 模型名以控制台为准",
    },
    "11": {
        "title": "小米 MiMo",
        "base": "https://api.xiaomimimo.com/v1/chat/completions",
        "list": "https://api.xiaomimimo.com/v1/models",
        "key_hint": "sk-...",
        "howto": "platform.xiaomimimo.com 小米账号登录 -> API Keys -> 新建",
        "quota": "新用户注册即送免费体验额度; 另有 Token Plan 订阅档",
        "ctx_in": 1000000, "ctx_out": 32768, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "mimo-v2.5-pro", "ctx": 1000000, "tools": True},
            {"id": "mimo-v2.5", "ctx": 1000000, "vision": True},
        ],
        "note": "V2 系列已于 2026-06-30 下线, 只能用 V2.5",
    },
    "12": {
        "title": "商汤 SenseNova",
        "base": "https://api.sensenova.cn/compatible-mode/v1/chat/completions",
        "list": "https://api.sensenova.cn/compatible-mode/v1/models",
        "key_hint": "...",
        "howto": "platform.sensenova.cn 注册 -> 实名 -> 访问令牌 -> 新建",
        "quota": "多个模型每 5 小时滚动免费额度(如 6.7-Flash-Lite 1500 次/5h)",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "sensenova-6.7-flash-lite", "ctx": 131072, "vision": True},
            {"id": "sensenova-6.7-flash"},
        ],
    },
    "13": {
        "title": "阶跃星辰 StepFun",
        "base": "https://api.stepfun.com/v1/chat/completions",
        "list": "https://api.stepfun.com/v1/models",
        "key_hint": "sk-...",
        "howto": "platform.stepfun.com 注册 -> 实名 -> API Keys 新建",
        "quota": "Step Plan 免费体验(15 天起, 邀请好友可最长累计 120 天)",
        "ctx_in": 262144, "ctx_out": 8192, "tools": True, "vision": True,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "step-3.7-flash", "ctx": 262144, "vision": True},
            {"id": "step-2-16k", "ctx": 16384, "vision": False},
        ],
    },
    "14": {
        "title": "DeepSeek 官方",
        "base": "https://api.deepseek.com/v1/chat/completions",
        "list": "https://api.deepseek.com/v1/models",
        "key_hint": "sk-...",
        "howto": "platform.deepseek.com 注册 -> API Keys",
        "quota": "新用户赠体验余额(用完转付费, 单价业内最低档之一)",
        "ctx_in": 1000000, "ctx_out": 65536, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "cn",
        "candidates": [
            {"id": "deepseek-v4-flash", "ctx": 1000000},
            {"id": "deepseek-reasoner", "ctx": 131072},
        ],
        "note": "旧模型名 deepseek-chat 已弃用",
    },

    # ---------------- 国外: 有代理的用户的福利 ----------------
    "2": {
        "title": "OpenRouter 聚合池",
        "base": "https://openrouter.ai/api/v1/chat/completions",
        "list": "https://openrouter.ai/api/v1/models",
        "key_hint": "sk-or-v1-...",
        "howto": "openrouter.ai 邮箱注册(别点 Continue with Google) -> Keys -> Create Key",
        "quota": "带 :free 的模型免费; 未充值 20次/分、50次/天, 充 $10 升 1000 次/天",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": True,
        "needs_key_for_list": False,
        "geo": "intl",
        "agg": True,
        "free_suffix": ":free",
        "max_pick": 5,
        "candidates": [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "thinkingmachines/inkling:free",
            "inclusionai/ling-3.0-flash-vl:free",
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "liquid/lfm-2.5-2.6b:free",
        ],
    },
    "15": {
        "title": "Groq (LPU 极速推理)",
        "base": "https://api.groq.com/openai/v1/chat/completions",
        "list": "https://api.groq.com/openai/v1/models",
        "key_hint": "gsk_...",
        "howto": "console.groq.com 注册(可用 Google 账号) -> API Keys -> Create",
        "quota": "永久免费层, 按模型限流(如 8B 类 30次/分、14400次/天); 速度 700+ token/秒",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "intl",
        "candidates": [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
        ],
    },
    "16": {
        "title": "Cerebras (免费额度最慷慨)",
        "base": "https://api.cerebras.ai/v1/chat/completions",
        "list": "https://api.cerebras.ai/v1/models",
        "key_hint": "csk-...",
        "howto": "cloud.cerebras.ai 注册 -> API Keys -> Create",
        "quota": "免费层每天约 100 万 Token(以官网为准); 吞吐极高",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "intl",
        "candidates": [
            "gpt-oss-120b",
            "gpt-oss-20b",
            "llama-3.3-70b",
            "qwen-3-32b",
        ],
    },
    "17": {
        "title": "Mistral 官方",
        "base": "https://api.mistral.ai/v1/chat/completions",
        "list": "https://api.mistral.ai/v1/models",
        "key_hint": "...",
        "howto": "console.mistral.ai 注册(需手机号验证) -> API Keys -> Create",
        "quota": "免费层每月约 10 亿 Token(1 RPS / 50 万 TPM); 需同意数据用于训练",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "intl",
        "candidates": [
            "mistral-small-latest",
            "open-mistral-nemo",
            "mistral-large-latest",
        ],
    },
    "18": {
        "title": "NVIDIA NIM",
        "base": "https://integrate.api.nvidia.com/v1/chat/completions",
        "list": "https://integrate.api.nvidia.com/v1/models",
        "key_hint": "nvapi-...",
        "howto": "build.nvidia.com 注册 -> 任意模型页 Get API Key",
        "quota": "注册送 1000 credits; 多数开源模型可免费试用",
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": True,
        "geo": "intl",
        "candidates": [
            "meta/llama-3.3-70b-instruct",
            "deepseek-ai/deepseek-r1",
            "qwen/qwen2.5-72b-instruct",
        ],
    },
    "19": {
        "title": "GitHub Models",
        "base": "https://models.github.ai/inference/chat/completions",
        "list": "https://models.github.ai/catalog/models",
        "key_hint": "github_pat_...  (需勾 models:read 权限)",
        "howto": ("github.com Settings -> Developer settings -> Fine-grained tokens "
                  "-> 勾 Models: Read -> 生成"),
        "quota": "GitHub 账号即可免费调用 GPT/Llama 等; 按账号档位限流",
        "ctx_in": 128000, "ctx_out": 8192, "tools": False, "vision": True,
        "needs_key_for_list": True,
        "geo": "intl",
        "candidates": [
            "openai/gpt-4.1-mini",
            "openai/gpt-4o-mini",
            "meta/Llama-4-Scout-17B-16E-Instruct",
            "mistral-ai/Mistral-Small-3.1",
        ],
    },
    "3": {
        "title": "Google Gemini (风控高, 高级选项)",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "list": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "key_hint": "AIzaSy...",
        "howto": "aistudio.google.com -> Get API Key (需海外 IP; 建议新加坡/日本节点)",
        "quota": "Flash 系免费(约 20 次/天起, Flash-Lite 更高); 未绑结算账户的项目大概率 403",
        "ctx_in": 1000000, "ctx_out": 8192, "tools": True, "vision": True,
        "needs_key_for_list": False,
        "geo": "intl",
        "candidates": [
            "gemini-3.5-flash",
            "gemini-flash-latest",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
        ],
    },
    # ---------- 聚合平台: 一个 Key 通吃多家模型(首推) ----------
    "20": {
        "title": "魔搭 ModelScope【一个Key通吃】",
        "base": "https://api-inference.modelscope.cn/v1/chat/completions",
        "list": "https://api-inference.modelscope.cn/v1/models",
        "key_hint": "ms-...  (modelscope.cn 头像 -> 访问令牌 创建)",
        "howto": ("modelscope.cn 注册 -> 绑定阿里云账号 -> 阿里云侧完成实名认证 "
                  "-> 头像「访问令牌」新建。不绑阿里云会一直报 401 "
                  "please bind your alibaba cloud account"),
        "quota": ("一个 Token 通吃平台上全部 48 个模型(DeepSeek-V4 / Qwen3-235B / "
                  "GLM-5.2 / MiniMax-M3); 每天 2000 次免费、次日重置、长期可用"),
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": False,
        "geo": "cn",
        "agg": True,
        "max_pick": 5,
        # 2026-09-13 实测(48 个模型全测): 魔搭常有整组模型返回"200 但内容为空"
        # —— DeepSeek 全系、智谱全系、文心全系、阶跃全系、美团龙猫当时都跑不出,
        # 而 Qwen 系可用率最高(19 个可用里 13 个是 Qwen)。所以 Qwen 排前面。
        "prefer": ["Qwen3-235B-A22B-Thinking", "Qwen3.5-122B", "Qwen3-235B",
                   "Qwen3-Next-80B", "Qwen3.5-35B-A3B", "Qwen3-Coder-30B",
                   "Qwen3.5-27B", "Qwen3.8-27B", "GLM-5.2", "DeepSeek-V4-Flash",
                   "DeepSeek-V4-Pro"],
        "candidates": [
            {"id": "Qwen/Qwen3-235B-A22B", "ctx": 131072},
            {"id": "Qwen/Qwen3.5-122B-A10B", "ctx": 131072},
            {"id": "Qwen/Qwen3-Next-80B-A3B-Instruct", "ctx": 131072},
            {"id": "Qwen/Qwen3.5-35B-A3B", "ctx": 131072},
            {"id": "Qwen/Qwen3-Coder-30B-A3B-Instruct", "ctx": 131072},
            {"id": "deepseek-ai/DeepSeek-V4-Flash-0731", "ctx": 131072},
            {"id": "ZhipuAI/GLM-5.2", "ctx": 131072},
        ],
        "note": ("免费额度和模型清单由平台每日调整; 每日 2000 次是账号总量, "
                 "单模型另有上限(通常 200 次/天)。实测: 魔搭常有一批模型返回 "
                 "HTTP 200 但内容是空的(共享池额度被瞬时吃满), 换个模型即可 —— "
                 "过一阵这些模型多半会自己恢复, 不是坏了"),
        "err_hint_401": ("魔搭报 401 十有八九不是 Key 的问题, 而是这个账号没绑定阿里云, "
                         "或者阿里云侧还没做实名认证。去 modelscope.cn 头像 -> "
                         "账号设置 -> 绑定阿里云, 再回阿里云完成实名, 然后重新复制 Token。"),
    },
    "21": {
        "title": "OrcaRouter 免费池【境外聚合】",
        "base": "https://api.orcarouter.ai/v1/chat/completions",
        "list": "https://api.orcarouter.ai/v1/models",
        "key_hint": "sk-orca-...",
        "howto": "orcarouter.ai 注册(免信用卡) -> 控制台创建 API Key",
        "quota": ("一个 Key 覆盖 195 个模型; 后缀 -free 的模型与 orcarouter/free "
                  "走 $0 免费路由(限速, 超额返回 429 但不扣费)"),
        "ctx_in": 131072, "ctx_out": 8192, "tools": True, "vision": False,
        "needs_key_for_list": False,
        "geo": "intl",
        "agg": True,
        "max_pick": 3,
        "prefer": ["deepseek-v4-flash-free", "glm-5.3-flash-free", "hy3-free",
                   "orcarouter/free"],
        "candidates": [
            "deepseek/deepseek-v4-flash-free",
            "z-ai/glm-5.3-flash-free",
            "tencent/hy3-free",
            "orcarouter/free",
        ],
        "note": ("第三方中转, 非官方直连, 稳定性与合规性无保障; "
                 "建议只当境外模型的补充, 别放重要用途"),
    },
}

# 按 key 前缀猜平台(用户只给 Key 没给编号时用)
KEY_PREFIX_HINTS = [
    ("sk-or-v1-", "2"),
    ("sk-orca-", "21"),
    ("AIzaSy", "3"),
    ("gsk_", "15"),
    ("csk-", "16"),
    ("nvapi-", "18"),
    ("github_pat_", "19"),
    ("bce-v3/", "5"),
    ("ms-", "20"),
    ("ms_", "20"),
    ("sk-", "1"),
]

CN_IDS = [k for k, v in PROVIDERS.items() if v["geo"] == "cn"]
INTL_IDS = [k for k, v in PROVIDERS.items() if v["geo"] == "intl"]

# 聚合平台(一个 Key 能接多家模型)的展示顺序, 按推荐度排
AGG_ORDER = ["20", "9", "2", "21"]

# 最值得先接的几个(★)。选平台时优先推荐这些。
STAR = {
    "20": "【首推】只有它一个也够用: 一个 Token 通吃 48 个模型, 每天 2000 次、次日重置",
    "9": "一个 Key 覆盖百余款模型, 新用户 7000 万 Token 额度(90 天)",
    "2": "一个 Key 覆盖境外 400+ 模型, 含免费池",
    "21": "免信用卡, 一个 Key 覆盖 195 个模型(第三方中转, 只作补充)",
    "4": "单家里能力最强: GLM-4.7-Flash 永久免费、200K 上下文",
    "8": "永久免费不限量, 但上下文只有 8K(应急够用)",
    "11": "1M 上下文 + 全模态(小米自研)",
}


def guess_provider_by_key(key):
    for prefix, pid in KEY_PREFIX_HINTS:
        if key.startswith(prefix):
            return pid
    return None


# ================= 选模型 =================

def _norm_cand(c, prov):
    """候选统一成 dict。"""
    if isinstance(c, dict):
        d = {"id": c["id"]}
        d["ctx"] = c.get("ctx", prov["ctx_in"])
        d["out"] = c.get("out", prov["ctx_out"])
        d["tools"] = c.get("tools", prov["tools"])
        d["vision"] = c.get("vision", prov["vision"])
        return d
    return {"id": c, "ctx": prov["ctx_in"], "out": prov["ctx_out"],
            "tools": prov["tools"], "vision": prov["vision"]}


def _guess_vision(mid, prov):
    low = mid.lower()
    return any(h in low for h in VISION_HINTS)


def pick_models(prov, key, verbose=True):
    """确定要实测的模型清单。返回 (候选[dict], 在线全量id集合 或 None)。"""
    cands = [_norm_cand(c, prov) for c in prov["candidates"]]
    live = None
    list_url = prov.get("list")
    if list_url:
        for attempt in range(2):
            try:
                live = fetch_model_list(
                    list_url, key if prov["needs_key_for_list"] else None)
                break
            except Exception as e:
                if attempt == 0 and verbose:
                    print("[!] 拉取实时模型列表失败:", repr(e)[:70])
                live = None
    if live:
        live_ids = set(live)
        prefer = prov.get("prefer")
        if prefer:
            want = prov.get("max_pick", 5)
            # 多挑候选做替补: 免费聚合池常有"能列出来但跑不出内容"的模型
            # (HTTP 200 但 choices 为空), 实测会淘汰一批, 多测几个才凑得齐 want 个可用的。
            top = want * prov.get("probe_factor", 3)
            picked = []
            for pat in prefer:
                for mid in sorted(live_ids):
                    if mid not in picked and pat.lower() in mid.lower():
                        picked.append(mid)
                        break
                if len(picked) >= top:
                    break
            if picked:
                res = []
                for mid in picked[:top]:
                    meta = live.get(mid) or {}
                    res.append({"id": mid,
                                "ctx": meta.get("context_length") or prov["ctx_in"],
                                "out": prov["ctx_out"], "tools": prov["tools"],
                                "vision": _guess_vision(mid, prov)})
                if verbose:
                    print("[i] 聚合模式: 平台在线 %d 个模型, 挑 %d 个候选实测"
                          "(留替补, 最终取最快可用的 %d 个)"
                          % (len(live_ids), len(res), want))
                return res, live_ids
        if prov.get("free_suffix"):
            suf = prov["free_suffix"]
            frees = [m for m in live_ids if m.endswith(suf)]
            ordered = [c["id"] for c in cands if c["id"] in frees]
            ordered += [m for m in sorted(frees) if m not in ordered]
            top = prov.get("max_pick", 5)
            res = []
            for mid in ordered[:top]:
                meta = live.get(mid) or {}
                ctx = meta.get("context_length") or prov["ctx_in"]
                d = {"id": mid, "ctx": ctx, "out": prov["ctx_out"],
                     "tools": prov["tools"],
                     "vision": _guess_vision(mid, prov)}
                res.append(d)
            if verbose:
                print("[i] 实时免费池 %d 个模型, 选中 %d 个实测" % (len(frees), len(res)))
            return res, live_ids
        known = [c for c in cands if c["id"] in live_ids]
        if known:
            for c in known:
                meta = live.get(c["id"]) or {}
                if meta.get("context_length"):
                    c["ctx"] = meta["context_length"]
            return known, live_ids
        # 候选名都不在线上: 用线上前几个(可能是新模型)
        extra = []
        for mid in sorted(live_ids)[:3]:
            meta = live.get(mid) or {}
            extra.append({"id": mid, "ctx": meta.get("context_length") or prov["ctx_in"],
                          "out": prov["ctx_out"], "tools": prov["tools"],
                          "vision": _guess_vision(mid, prov)})
        if verbose:
            print("[i] 内置候选不在线上清单, 改用平台实时前 3 个模型")
        return extra, live_ids
    if verbose:
        print("[i] 实时清单不可用, 用内置候选继续")
    return cands, None


def vendor_of(model_id, prov):
    if prov["geo"] == "intl" and "/" in model_id:
        return model_id.split("/")[0]
    if "/" in model_id:
        return model_id.split("/")[0]
    return prov["title"].split()[0]


# ================= 写入 models.json =================

def build_entry(prov, key, model):
    mid = model["id"]
    short = mid.split("/")[-1]
    tag = prov["title"].split()[0]
    return {
        "id": mid,
        "name": "%s · %s" % (short, tag),
        "vendor": vendor_of(mid, prov),
        "apiKey": key,
        "maxInputTokens": int(model.get("ctx") or prov["ctx_in"]),
        "maxOutputTokens": int(model.get("out") or prov["ctx_out"]),
        "url": prov["base"],
        "temperature": 0.7,
        "supportsToolCall": bool(model.get("tools", prov["tools"])),
        "supportsImages": bool(model.get("vision", prov["vision"])),
    }


def write_models_json(entries, prov=None, live_ids=None, prune=True):
    """合并写入双路径, 自动备份, 同 id 覆盖。
    prov+live_ids 给定时, 清理本平台已下架的旧条目(只动本平台, 不碰别家)。"""
    written = []
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in MODELS_JSON_PATHS:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            models = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {"models": []}
                models = data.get("models") or []
                bak = path + ".bak-" + stamp
                with open(bak, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print("[+] 已备份:", bak)
            pruned = []
            if prune and prov and live_ids is not None:
                kept = []
                for m in models:
                    if (m.get("url") == prov["base"] and m.get("id") not in live_ids):
                        pruned.append(m.get("id"))
                    else:
                        kept.append(m)
                models = kept
                if pruned:
                    print("[i] 已清理本平台下架的旧模型:", ", ".join(pruned))
            ids = {e["id"] for e in entries}
            merged = [m for m in models if m.get("id") not in ids] + entries
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"models": merged}, f, ensure_ascii=False, indent=2)
            written.append(path)
            print("[+] 已写入:", path)
        except Exception as e:
            print("[!] 写入失败 %s: %s" % (path, repr(e)[:90]))
    return written


# ================= 输入 =================

def _input(prompt=""):
    try:
        return input(prompt)
    except EOFError:
        print("\n[x] 检测不到键盘输入(非交互环境)。AI 代跑请用参数模式:")
        print("    python setup_free_llm.py --provider 4 --key xxxx")
        print("    多平台: python setup_free_llm.py --batch \"4=xxx,7=yyy\"")
        sys.exit(1)


# ================= 单平台流程 =================

def run_provider(pid, key, label=""):
    prov = PROVIDERS[pid]
    print("\n" + "-" * 56)
    print("[*] 平台 %s: %s" % (pid, prov["title"]))
    if prov.get("note"):
        print("[!] 注意: %s" % prov["note"])

    px, chan, ms0 = resolve_channel(prov["list"] or prov["base"], key)
    print("[i] 通道: %s" % chan)

    model_list, live_ids = pick_models(prov, key)
    if not model_list:
        print("[x] 没有可测模型")
        log_event(SKILL_NAME, "setup", False, platform=prov["title"],
                  error_code="NO_MODELS", note="无候选模型")
        return []

    print("[*] 并发实测 %d 个模型 (429/503 会自动退避重试):" % len(model_list))

    def worker(m):
        ok, note, ms = test_model(prov["base"], key, m["id"])
        if ok and DEEP:
            ok2, note2 = test_model_stream(prov["base"], key, m["id"])
            if not ok2:
                return m, False, "非流式OK但%s" % note2, ms
        return m, ok, note, ms

    results = []
    workers = min(4, max(1, len(model_list)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for m, ok, note, ms in ex.map(worker, model_list):
            results.append((m, ok, note, ms))
            print("    [%s] %-46s %s" % ("OK  " if ok else "FAIL",
                                         m["id"][:46], note))
            log_event(SKILL_NAME, "test", ok, platform=prov["title"],
                      model=m["id"],
                      error_code=(note.split(" ")[1] if (not ok and note.startswith("HTTP")) else ""),
                      error_msg="" if ok else note)

    passed = [(m, ms) for m, ok, _n, ms in results if ok]
    if not passed:
        print("[x] 该平台所有候选都没通过。")
        print("    401=Key 不对或复制不全 | 403=地域/未开通该模型 | 429=共享池限流(稍后重试)")
        if prov.get("err_hint_401"):
            print("    [特别提醒] %s" % prov["err_hint_401"])
        log_event(SKILL_NAME, "setup", False, platform=prov["title"],
                  error_code="ALL_FAIL", note="全部实测未通过")
        return []

    passed.sort(key=lambda x: x[1])  # 最快的排前面 -> 写入后模型选择器第一个最好用
    cap = prov.get("max_pick") or len(passed)
    keep = passed[:cap]
    if len(passed) > cap:
        print("[i] 实测通过 %d 个, 按延迟只保留最快的 %d 个" % (len(passed), cap))
    entries = [build_entry(prov, key, m) for m, _ms in keep]
    print("[*] 实测 %d 个, 通过 %d 个, 按延迟从快到慢写入(挑第一个用最顺):"
          % (len(results), len(passed)))
    for e, (m, ms) in zip(entries, keep):
        print("    %-46s %5dms" % (m["id"][:46], ms))
    write_models_json(entries, prov=prov, live_ids=live_ids, prune=PRUNE)
    log_event(SKILL_NAME, "setup", True, platform=prov["title"],
              model=",".join(m["id"] for m, _ in keep),
              note="写入 %d 个模型, 通道=%s" % (len(entries), chan))
    return entries


# ================= 体检 / 探测 =================

def mode_probe(only=None):
    """打印各平台「直连 vs 各代理通道」的可达性与延迟, 让用户看清楚该不该开代理。"""
    print("\n" + "=" * 68)
    print(" 网络体检: 各平台接入通道实测 (不写任何配置)")
    print("=" * 68)
    build_proxy_candidates()
    cands = PROXY_CANDIDATES
    header = "%-26s" % "平台" + "".join("%-14s" % c[0][:12] for c in cands)
    print(header)
    print("-" * len(header))
    ids = [i for i in sorted(PROVIDERS, key=lambda x: int(x)) if not only or i in only]
    for pid in ids:
        prov = PROVIDERS[pid]
        cells = []
        for _label, px in cands:
            ok, ms, _st = ping_url(prov["list"] or prov["base"], px, None, 6)
            cells.append("✓%dms" % ms if ok else "✗")
        print("%-26s" % ("%s %s" % (pid, prov["title"][:22]))
              + "".join("%-14s" % c for c in cells))


def _failure_kind(note):
    """区分「确定失效」与「暂时测不通」。
    免费池里 429 / 空响应 / 超时都是常态波动, 不该当死条目让用户删掉。"""
    n = note or ""
    if n.startswith("HTTP 404") or n.startswith("HTTP 403") or n.startswith("HTTP 400"):
        return "dead"       # 已下架 / 被禁用 / 模型名失效
    return "flaky"          # 空响应 / 429 / 超时 / 连接失败 —— 过一阵会自己好


def mode_doctor(only=None):
    """体检已写入 models.json 的自定义模型: 哪些还活着、哪些已是死条目。"""
    base2pid = {v["base"]: k for k, v in PROVIDERS.items()}
    print("\n" + "=" * 68)
    print(" 已接入自定义模型体检")
    print("=" * 68)
    seen, rows = set(), []
    for path in MODELS_JSON_PATHS:
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print("[!] 读取失败 %s: %s" % (path, repr(e)[:60]))
            continue
        for m in data.get("models") or []:
            url = m.get("url", "")
            if url not in base2pid:
                continue                 # 不是本 Skill 写入的, 不碰
            pid = base2pid[url]
            if only and pid not in only:
                continue
            kk = (m.get("id"), url)
            if kk in seen:
                continue
            seen.add(kk)
            rows.append((pid, m))
    if not rows:
        print("[i] 没找到本 Skill 写入的自定义模型")
        return
    dead, flaky = [], []
    for pid, m in rows:
        key = m.get("apiKey") or ""
        try:
            resolve_channel(PROVIDERS[pid]["base"], key)   # 按 url 缓存, 只真测一次
            ok, note, ms = test_model(PROVIDERS[pid]["base"], key,
                                      m.get("id"), timeout=20, retries=0)
        except Exception as e:
            ok, note, ms = False, "测试异常(%s)" % repr(e)[:40], 0
        kind = "ok" if ok else _failure_kind(note)
        flag = {"ok": "OK  ", "dead": "DEAD", "flaky": "WARN"}[kind]
        print("  [%s] %-40s %s" % (flag, str(m.get("id"))[:40],
                                   ("%dms %s" % (ms, note)) if ok else note))
        if kind == "dead":
            dead.append((pid, m))
        elif kind == "flaky":
            flaky.append((pid, m))
    if dead:
        print("\n[x] 以下条目确定不可用(平台已下架/改名, 或 Key 失效) —— 建议换掉:")
        for _pid, m in dead:
            print("    %s" % m.get("id"))
        print("    处理建议: 重跑本脚本对应平台(会自动清理下架条目), 或换 Key。")
    if flaky:
        print("\n[!] 以下条目本次没测通(免费池波动 / 网络抖动) —— 别急着删:")
        for _pid, m in flaky:
            print("    %s" % m.get("id"))
        print("    这类多半过一阵自己就恢复(实测: GLM-5.2 连续 3 次空响应后几分钟又能用)。")
    if not dead and not flaky:
        print("\n[√] 全部可用。")


def mode_list(pid, key):
    prov = PROVIDERS[pid]
    resolve_channel(prov["list"] or prov["base"], key)
    live = fetch_model_list(prov["list"], key if prov["needs_key_for_list"] else None)
    if not live:
        print("[!] 拿不到在线清单(可能该平台不提供 /models 接口, 或 Key 无权限)")
        print("[i] 内置候选: " + ", ".join(
            c["id"] if isinstance(c, dict) else c for c in prov["candidates"]))
        return
    print("[√] %s 在线模型 %d 个:" % (prov["title"], len(live)))
    for mid in sorted(live):
        meta = live[mid] or {}
        ctx = meta.get("context_length")
        print("    %-52s %s" % (mid, ("%dK" % (ctx // 1000)) if ctx else ""))


# ================= 参数解析 =================

def parse_args(argv):
    o = {"provider": None, "key": None, "batch": None, "proxy": None,
         "report": False, "probe": False, "doctor": False, "list": None,
         "deep": False, "prune": True, "only": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--provider", "-p") and i + 1 < len(argv):
            o["provider"] = argv[i + 1]; i += 2
        elif a == "--key" and i + 1 < len(argv):
            o["key"] = argv[i + 1]; i += 2
        elif a == "--batch" and i + 1 < len(argv):
            o["batch"] = argv[i + 1]; i += 2
        elif a == "--proxy" and i + 1 < len(argv):
            o["proxy"] = argv[i + 1]; i += 2
        elif a == "--only" and i + 1 < len(argv):
            o["only"] = [x.strip() for x in argv[i + 1].split(",") if x.strip()]; i += 2
        elif a == "--list":
            o["list"] = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else "ALL"
            i += 2 if (i + 1 < len(argv) and not argv[i + 1].startswith("-")) else 1
        elif a == "--report":
            o["report"] = True; i += 1
        elif a == "--probe":
            o["probe"] = True; i += 1
        elif a == "--doctor":
            o["doctor"] = True; i += 1
        elif a == "--deep":
            o["deep"] = True; i += 1
        elif a == "--no-prune":
            o["prune"] = False; i += 1
        elif a in ("-h", "--help"):
            print(__doc__); sys.exit(0)
        else:
            print("[x] 无法识别的参数:", a)
            print("    可用: --provider --key --batch --proxy --only --list "
                  "--probe --doctor --deep --no-prune --report")
            sys.exit(1)
    return o


def parse_batch(s):
    """解析 "4=xxx,7=yyy" -> [(pid, key), ...]"""
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            print("[!] 跳过无法解析的批量项:", item)
            continue
        pid, key = item.split("=", 1)
        pid, key = pid.strip(), key.strip()
        if pid not in PROVIDERS:
            print("[!] 跳过未知平台编号:", pid)
            continue
        out.append((pid, key))
    return out


# ================= 菜单 =================

def _brief(quota, width=30):
    """把额度说明压成一行短句, 供菜单显示。"""
    s = re.split(r"[;(（]", quota)[0].strip().rstrip(",，;；、").strip()
    if len(s) <= width:
        return s
    cut = s[:width]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut + "…"


def _row(pid):
    mark = "★" if pid in STAR else "  "
    return "  %s %2s. %-24s %s" % (mark, pid, PROVIDERS[pid]["title"],
                                   _brief(PROVIDERS[pid]["quota"], 36))


def print_menu():
    print("\n选择平台 (可以一次给多个平台的 Key, 用逗号隔开编号, 我一次全接进去)")
    print("  == 首推: 一个 Key 通吃多个模型 ==")
    for pid in AGG_ORDER:
        if pid in PROVIDERS:
            print(_row(pid))
    print("  == 单家平台: 一个 Key 只管自己家那几个模型 ==")
    print("   [国内直连, 不用代理]")
    for pid in sorted([k for k in CN_IDS if k not in AGG_ORDER], key=lambda x: int(x)):
        print(_row(pid))
    print("   [境外, 直连/代理总有一条通]")
    for pid in sorted([k for k in INTL_IDS if k not in AGG_ORDER], key=lambda x: int(x)):
        print(_row(pid))
    if STAR:
        print("  ★ = 最值得先接的:")
        ordered = [p for p in AGG_ORDER if p in STAR] + \
                  [p for p in sorted(STAR, key=lambda x: int(x)) if p not in AGG_ORDER]
        for pid in ordered:
            print("     %2s %s" % (pid, STAR[pid]))


def main():
    global MODE, PROXY_MODE, PROXIES, DEEP, PRUNE
    o = parse_args(sys.argv[1:])

    if o["report"]:
        print_report(SKILL_NAME)
        return

    print("=" * 56)
    print(" 免费大模型一键接入 WorkBuddy  v2.1")
    print(" 用自己的 Key 跑对话, 不消耗 WorkBuddy 积分")
    print("=" * 56)

    DEEP = o["deep"]
    PRUNE = o["prune"]
    if o["proxy"]:
        if o["proxy"].lower() == "auto":
            PROXY_MODE = "auto"
        elif o["proxy"].lower() in ("off", "none", "no"):
            PROXY_MODE = "off"
        else:
            PROXY_MODE = "manual"
            p = _norm_proxy(o["proxy"])
            PROXIES.update({"http": p, "https": p})
            print("[+] 指定代理:", p)

    # 体检类模式不写配置
    if o["probe"]:
        mode_probe(set(o["only"]) if o["only"] else None)
        return
    if o["doctor"]:
        build_proxy_candidates(verbose=False)
        mode_doctor(set(o["only"]) if o["only"] else None)
        return

    if PROXY_MODE == "manual":
        PROXY_CANDIDATES.extend([("直连", {}), ("指定代理", dict(PROXIES))])
    else:
        build_proxy_candidates()

    # 批量模式(可多个平台一次接完)
    if o["batch"]:
        MODE = "param"
        jobs = parse_batch(o["batch"])
        if not jobs:
            print("[x] --batch 没解析出可用平台。格式: --batch \"4=key1,7=key2\"")
            return
        total = []
        for pid, key in jobs:
            total += run_provider(pid, key)
        finish(total)
        return

    if o["list"]:
        MODE = "param"
        pid = o["list"]
        if pid == "ALL":
            for k in sorted(PROVIDERS, key=lambda x: int(x)):
                print("\n### %s %s" % (k, PROVIDERS[k]["title"]))
                print("    " + ", ".join(
                    c["id"] if isinstance(c, dict) else c for c in PROVIDERS[k]["candidates"]))
            return
        if pid not in PROVIDERS:
            print("[x] 未知平台编号:", pid); return
        if not o["key"] and PROVIDERS[pid]["needs_key_for_list"]:
            print("[!] 该平台需要 --key 才能拉在线清单, 先列出内置候选:")
            print("    " + ", ".join(c["id"] if isinstance(c, dict) else c
                                     for c in PROVIDERS[pid]["candidates"]))
            return
        mode_list(pid, o["key"])
        return

    # 单平台参数模式
    if o["key"]:
        MODE = "param"
        pid = o["provider"] or guess_provider_by_key(o["key"])
        if not pid:
            print("[!] 从 Key 前缀猜不出平台, 请显式指定 --provider 编号")
            print_menu(); return
        if pid not in PROVIDERS:
            print("[x] --provider 只能是:", ", ".join(sorted(PROVIDERS, key=lambda x: int(x))))
            return
        finish(run_provider(pid, o["key"]))
        return

    # 交互模式
    print_menu()
    print("  输入编号, 或直接回车看网络体检")
    choice = _input("\n平台编号(可多个, 用逗号隔开, 如 4,7,11): ").strip()
    if not choice:
        mode_probe()
        return
    pids = [x.strip() for x in choice.replace("，", ",").split(",") if x.strip()]
    bad = [p for p in pids if p not in PROVIDERS]
    if bad:
        print("[x] 无效编号:", ", ".join(bad)); return

    all_entries = []
    for pid in pids:
        prov = PROVIDERS[pid]
        print("\n拿 Key 方法(%s): %s" % (prov["title"], prov["howto"]))
        print("额度: %s" % prov["quota"])
        key = _input("粘贴 API Key (%s) [回车跳过]: " % prov["key_hint"]).strip()
        if not key:
            print("[i] 已跳过 %s" % prov["title"]); continue
        all_entries += run_provider(pid, key)
    finish(all_entries)


def finish(entries):
    if not entries:
        return
    print("\n" + "=" * 56)
    print(" 完成! 共接入 %d 个模型。接下来 2 步:" % len(entries))
    print(" 1. 完整退出 WorkBuddy 进程, 重新打开")
    print(" 2. 对话页模型选择器里挑模型 —— 列表最上面那个是实测最快的")
    print(" 遇 429(免费池繁忙)= 换列表里另一个模型, 不是坏了")
    print(" 想复查/清理死模型: python scripts/setup_free_llm.py --doctor")
    print("=" * 56)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[i] 已取消")
