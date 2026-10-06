# -*- coding: utf-8 -*-
"""十家大模型，同一个问题，同一份提示词。"""
import json, os, re, ssl, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

ssl._create_default_https_context = ssl._create_unverified_context
BASE = os.path.dirname(os.path.abspath(__file__))
def _vendor_of(mid):
    for pref, v in (("deepseek-ai/", "DeepSeek"), ("Qwen/", "阿里通义"), ("THUDM/", "智谱"),
                    ("zai-org/", "智谱"), ("moonshotai/", "月之暗面"), ("MiniMaxAI/", "MiniMax"),
                    ("stepfun-ai/", "阶跃星辰"), ("tencent/", "腾讯混元"),
                    ("ByteDance-Seed/", "字节"), ("meituan-longcat/", "美团"),
                    ("Pro/deepseek-ai/", "DeepSeek")):
        if mid.startswith(pref):
            return v
    return mid.split("/")[0] if mid and "/" in mid else mid


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
URL = "https://api.siliconflow.cn/v1/chat/completions"

raw = open(os.path.join(BASE, "prompt.txt"), encoding="utf-8").read()
SYS = raw.split("USER:")[0].replace("SYSTEM:", "").strip()
USER = raw.split("USER:")[1].strip()

# 模型清单直接来自你 models.json 的硅基流动条目（不写死，换电脑/换 key 都不用改）
COLORS = {"DeepSeek": "#4D6BFE", "阿里通义": "#615EED", "智谱": "#2C6BED",
          "月之暗面": "#0F1B2D", "MiniMax": "#E8452C", "阶跃星辰": "#00A4A6",
          "美团": "#FFD100", "腾讯混元": "#0052D9", "字节": "#25F4EE"}
PANEL = []
for m in SFMODELS:
    mid = m.get("id") or m.get("name")
    vendor = _vendor_of(mid)
    PANEL.append((mid, vendor, m.get("name", mid), COLORS.get(vendor, "#888888")))


def ask(item):
    mid, vendor, label, color = item
    payload = {
        "model": mid,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": USER}],
        "max_tokens": 4096,
        "temperature": 0.7,
    }
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))
        msg = r["choices"][0]["message"]
        text = (msg.get("content") or "").strip()
        if not text:                                  # 部分推理模型 content 为空
            text = "[reasoning] " + (msg.get("reasoning_content") or "").strip()
        usage = r.get("usage", {})
        return {"mid": mid, "vendor": vendor, "label": label, "color": color,
                "ok": True, "text": text, "sec": round(time.time() - t0, 1),
                "tokens": usage.get("completion_tokens")}
    except urllib.error.HTTPError as e:
        return {"mid": mid, "vendor": vendor, "label": label, "color": color,
                "ok": False, "text": f"HTTP {e.code}: {e.read().decode('utf-8','ignore')[:300]}",
                "sec": round(time.time() - t0, 1), "tokens": 0}
    except Exception as e:
        return {"mid": mid, "vendor": vendor, "label": label, "color": color,
                "ok": False, "text": f"{type(e).__name__}: {str(e)[:300]}",
                "sec": round(time.time() - t0, 1), "tokens": 0}


results = []
with ThreadPoolExecutor(max_workers=10) as ex:
    futs = {ex.submit(ask, it): it for it in PANEL}
    for f in as_completed(futs):
        r = f.result()
        results.append(r)
        flag = "OK  " if r["ok"] else "FAIL"
        print(f"[{flag}] {r['vendor']:8s} {r['label']:12s} {r['sec']:6.1f}s  {len(r['text'])}字")

order = {it[0]: i for i, it in enumerate(PANEL)}
results.sort(key=lambda x: order[x["mid"]])
json.dump(results, open(os.path.join(BASE, "answers.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\nsaved ->", os.path.join(BASE, "answers.json"))
