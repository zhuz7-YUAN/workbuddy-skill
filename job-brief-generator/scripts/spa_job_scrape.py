#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spa_job_scrape.py —— 抓「JS 动态渲染」的招聘官网（Edge CDP 通道）

原理：用系统自带 Edge 开调试端口（CDP），让真实浏览器把 JS 渲染完再读文本/链接。
      **零下载、零安装**，不需要 Playwright / Chromium（老机器/磁盘紧张的机器首选）。

读同目录 sources.default.json（或 sources.json），只处理 channel == "browser" 的条目。

依赖：
  - Microsoft Edge（Windows 自带）
  - Node.js 18+（自带全局 WebSocket；本脚本会自动寻找 node）
  - 同目录 edge_cdp.js

用法：
  python spa_job_scrape.py                          # 抓全部 browser 源
  python spa_job_scrape.py --only 国聘,武汉           # 只抓名字含这些词的源
  python spa_job_scrape.py --md 深度岗位.md
  python spa_job_scrape.py --keep-edge               # 抓完不关 Edge
  python spa_job_scrape.py --port 9444 --profile D:/JbEdgeProfile
"""
import argparse, datetime, io, json, os, re, shutil, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CDP_JS = os.path.join(HERE, "edge_cdp.js")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]
NODE_CANDIDATES = [
    r"C:\Program Files\nodejs\node.exe",
    r"C:\Program Files (x86)\nodejs\node.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe"),
]


def find_edge():
    for p in EDGE_CANDIDATES:
        if p and os.path.exists(p):
            return p
    w = shutil.which("msedge")
    if w:
        return w
    sys.exit("找不到 Microsoft Edge，请用 --edge 指定路径")


def _managed_node():
    """WorkBuddy 托管 Node（自动适配任意用户名 / 任意版本号）。"""
    root = os.path.expandvars(r"%USERPROFILE%\.workbuddy\binaries\node\versions")
    if not os.path.isdir(root):
        return None
    for ver in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, ver, "node.exe")
        if os.path.isfile(p):
            return p
    return None


def find_node():
    n = _managed_node()
    if n:
        return n
    for p in NODE_CANDIDATES:
        if p and os.path.exists(p):
            return p
    w = shutil.which("node")
    if w:
        return w
    sys.exit("找不到 Node.js（需 18+），请用 --node 指定路径")


def default_profile():
    # 优先放非系统盘且路径不含中文；退化到用户目录
    for cand in ("D:/JbEdgeProfile", "D:/WBEdgeProfile2"):
        if os.path.exists(os.path.splitdrive(cand)[0] + os.sep):
            return cand
    return os.path.join(os.path.expanduser("~"), "JbEdgeProfile")


def load_sources(path=None):
    for p in ([path] if path else [os.path.join(HERE, "sources.json"),
                                   os.path.join(HERE, "sources.default.json")]):
        if p and os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                return json.load(f).get("sources", [])
    sys.exit("找不到源清单")


def cdp_alive(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
            json.load(r)
        return True
    except Exception:
        return False


def start_edge(edge, port, profile, url="about:blank"):
    if cdp_alive(port):
        print(f"[复用] 端口 {port} 上已有 Edge CDP（**注意：确认它不是你日常浏览器的实例**）")
        return True
    os.makedirs(profile, exist_ok=True)
    args = [edge, "--headless=new", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            "--disable-sync", "--no-service-autorun", "--disable-background-networking", url]
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    # ★ 用 DETACHED 起，否则 shell/父进程一结束 Edge 就被回收，端口随即失联
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    for _ in range(20):
        time.sleep(1)
        if cdp_alive(port):
            return True
    return False


def run(node, port, args, wait=10):
    env = dict(os.environ, CDP_PORT=str(port), CDP_WAIT=str(wait * 1000))
    p = subprocess.run([node, CDP_JS] + args, capture_output=True, env=env, timeout=wait + 90)
    return p.stdout.decode("utf-8", "ignore"), p.stderr.decode("utf-8", "ignore")


URL_HINT = re.compile(r"recruit|job|position|news|notice|detail|show|zp|career|zhaopin", re.I)
ORG = re.compile(r"公司|集团|银行|研究院|研究所|设计院|学院|大学|中心|工厂|事业部|局|所|厂|社|学校|医院|国企|央企")
JOBKW = re.compile(r"招聘|公告|岗位|校招|双选|宣讲|应届|人才|考试|引进|选调|实习|录用")
SKIP = re.compile(r"^(登录|注册|首页|更多|下载|关于我们|隐私|协议|意见反馈|在线客服)$")


def pick_links(links_raw):
    keep, seen = [], set()
    for m in re.finditer(r"- (.+?)\n\s+(https?://\S+)", links_raw):
        t, h = m.group(1).strip(), m.group(2).strip()
        if not (6 <= len(t) <= 120) or h in seen or SKIP.search(t):
            continue
        if JOBKW.search(t) or (ORG.search(t) and len(t) >= 8) or (URL_HINT.search(h) and len(t) >= 8):
            seen.add(h)
            keep.append((t, h))
    return keep[:30]


def scrape(node, port, s, nav_wait, scrolls):
    run(node, port, ["goto", s["url"]], wait=nav_wait)
    time.sleep(2)
    txt, _ = run(node, port, ["text", str(scrolls)], wait=8)
    links, _ = run(node, port, ["links"], wait=8)
    return txt, pick_links(links)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="")
    ap.add_argument("--only", default="", help="逗号分隔，匹配源名子串")
    ap.add_argument("--md", default="深度的岗位.md")
    ap.add_argument("--region", default="")
    ap.add_argument("--port", type=int, default=9444,
                    help="CDP 端口。★别用 9222（容易被其它已登录会话占用）")
    ap.add_argument("--profile", default="")
    ap.add_argument("--nav-wait", type=int, default=15)
    ap.add_argument("--scrolls", type=int, default=2)
    ap.add_argument("--keep-edge", action="store_true")
    ap.add_argument("--edge", default="")
    ap.add_argument("--node", default="")
    a = ap.parse_args()

    edge = a.edge or find_edge()
    node = a.node or find_node()
    profile = a.profile or default_profile()

    srcs = [s for s in load_sources(a.sources or None)
            if s.get("channel") == "browser"
            and (not a.region or s.get("region") == a.region)]
    if a.only:
        kws = [k.strip() for k in a.only.split(",") if k.strip()]
        srcs = [s for s in srcs if any(k in s.get("name", "") for k in kws)]
    if not srcs:
        sys.exit("没有匹配的 browser 通道源")

    print(f"[配置] Edge={edge}\n[配置] Node={node}\n[配置] profile={profile}  port={a.port}")
    if not start_edge(edge, a.port, profile):
        sys.exit("❌ Edge 启动失败（端口被占用？试试 --port 换一个）")
    print(f"[就绪] 待抓 {len(srcs)} 个源\n")

    today = datetime.date.today().isoformat()
    L = [f"# 深度岗位（动态渲染站 · Edge CDP 实抓）· {today}", "",
         f"由 job-brief-generator 的 spa_job_scrape.py 渲染后抓取，共 {len(srcs)} 个源。",
         "> 抓不到的源会在 `官方直读清单.html` 里给出入口与搜索链接。", ""]
    for s in srcs:
        print(f"── {s['name']} …", flush=True)
        try:
            txt, links = scrape(node, a.port, s, a.nav_wait, a.scrolls)
            print(f"   正文 {len(txt)} 字，命中链接 {len(links)} 条")
        except Exception as e:
            txt, links = "", []
            print(f"   ❌ {type(e).__name__}: {e}")
        L.append(f"## 【{s.get('type','')}】{s['name']}")
        L.append(f"源: {s['url']}" + (f" ｜ {s['note']}" if s.get("note") else ""))
        if links:
            L.append("\n**命中岗位/公告链接**")
            for t, h in links:
                L.append(f"- {t}\n  {h}")
        if txt and len(txt.strip()) < 300:
            L.append("\n> ⚠️ 正文过短，该源可能需改用 manual 通道（给链接让用户自己点）")
        if txt:
            L.append("\n**页面正文摘录**\n")
            L.append("```")
            L.append(txt[:2500])
            L.append("```")
        L.append("")

    with io.open(a.md, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"\n[写入] {a.md}")

    if not a.keep_edge:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{a.port}/json/version", timeout=3)
            os.system("")  # no-op
        except Exception:
            pass
        for t in json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{a.port}/json/list", timeout=5).read().decode("utf-8", "ignore")
                or "[]"):
            try:
                if t.get("type") == "page":
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{a.port}/json/close/{t['id']}", timeout=3).read()
            except Exception:
                pass
        print("[收尾] 已请求关闭无头 Edge（若端口有其它用途可忽略）")


if __name__ == "__main__":
    main()
