# -*- coding: utf-8 -*-
"""探测你 models.json 里配置的硅基流动模型是否还活着（不是探测写死的清单）"""
import json, os, ssl, time, urllib.request, urllib.error
ssl._create_default_https_context = ssl._create_unverified_context

def _load_sf():
    p = None
    for cand in (os.path.expanduser("~/.workbuddy/models.json"),
                 os.path.expanduser("~/.codebuddy/models.json")):
        if os.path.exists(cand):
            p = cand
            break
    if p is None:
        raise SystemExit("没找到 models.json，请先配置（运行 free-llm-setup 选硅基流动）。")
    try:
        models = json.load(open(p, encoding="utf-8")).get("models", [])
    except ValueError as e:
        raise SystemExit("models.json 不是合法 JSON：%s\n解决：重新运行 free-llm-setup 生成。" % e)
    sf = [m for m in models if "siliconflow" in m.get("url", "")]
    if not sf:
        raise SystemExit("models.json 里没有硅基流动模型，请先配置（运行 free-llm-setup 选硅基流动）。")
    return sf[0]["apiKey"], sf

KEY, SFMODELS = _load_sf()
# 直接探测你配置的模型，不写死——早期版本写死 DeepSeek-V4-Flash / Kimi-K2.7-Code /
# Qwen3.5-397B 等虚构版本号，在硅基流动真实 API 上全部 404，会误报。
CAND = [(m.get("vendor") or (m.get("id") or "").split("/")[0] or "?",
         m.get("id") or m.get("name")) for m in SFMODELS]

for vendor, mid in CAND:
    p = {"model": mid, "messages": [{"role": "user", "content": "回复：OK"}],
         "max_tokens": 64, "temperature": 0.1}
    req = urllib.request.Request("https://api.siliconflow.cn/v1/chat/completions",
                                 data=json.dumps(p).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8"))
        c = r["choices"][0]["message"]["content"].strip()
        print(f"[OK]   {vendor:14s} {mid:42s} {time.time()-t0:5.1f}s -> {c[:40]}")
    except urllib.error.HTTPError as e:
        print(f"[HTTP] {vendor:14s} {mid:42s} {e.code} {e.read().decode('utf-8','ignore')[:110]}")
    except Exception as e:
        print(f"[FAIL] {vendor:14s} {mid:42s} {type(e).__name__} {str(e)[:90]}")
