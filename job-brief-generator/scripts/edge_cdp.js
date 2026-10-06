#!/usr/bin/env node
/**
 * edge_cdp.js — 通过 Edge 的 CDP 调试端口读写页面（零 npm 依赖，Node 22 自带 fetch + WebSocket）
 *
 * 前置：先用 --remote-debugging-port 启动 Edge（见 SKILL.md）
 *   "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
 *      --headless=new --remote-debugging-port=9222 \
 *      --user-data-dir='D:\WBEdgeProfile' --no-first-run "https://目标站"
 *
 * 用法：
 *   node edge_cdp.js list                    列出所有标签页
 *   node edge_cdp.js text [滚动次数]          读纯文本（滚动累积去重）
 *   node edge_cdp.js html                    读 outerHTML
 *   node edge_cdp.js links                   列出所有链接（文本 + href）
 *   node edge_cdp.js eval "<js表达式>"        执行任意 JS 并返回结果
 *   node edge_cdp.js goto <url>              当前标签跳转
 *   node edge_cdp.js newtab <url>            新开标签
 *   node edge_cdp.js wait <毫秒>              等待
 *
 * 环境变量：
 *   CDP_PORT  默认 9222
 *   CDP_TAB   标签页 URL 关键词（多标签时用来选，默认第一个 page）
 *   CDP_WAIT  导航后默认等待毫秒（默认 8000）
 */
'use strict';

const PORT = process.env.CDP_PORT || 9222;
const HOST = '127.0.0.1';
const NAV_WAIT = parseInt(process.env.CDP_WAIT || '8000', 10);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function listTargets() {
  for (let i = 0; i < 15; i++) {
    try {
      const r = await fetch(`http://${HOST}:${PORT}/json/list`);
      return await r.json();
    } catch (e) {
      await sleep(1000);
    }
  }
  throw new Error(`连不上 CDP 端口 ${PORT}。Edge 是否用 --remote-debugging-port=${PORT} 启动了？`);
}

function pickTarget(targets) {
  // 排除浏览器扩展自带的页面（Tampermonkey/HIX/翻译插件等会开机自开欢迎页，抢 pages[0]）
  const pages = targets.filter((t) => {
    if (t.type !== 'page' || !t.webSocketDebuggerUrl) return false;
    const u = t.url || '';
    if (u.startsWith('chrome-extension://') || u.startsWith('edge-extension://')) return false;
    if (/tampermonkey\.net|hix\.ai|microsoftedge\.microsoft\.com\/addons/i.test(u)) return false;
    return true;
  });
  if (!pages.length) throw new Error('没有可用的 page 标签（可能全是扩展页面）');
  const kw = process.env.CDP_TAB;
  if (kw) {
    const hit = pages.find((p) => (p.url || '').includes(kw) || (p.title || '').includes(kw));
    if (hit) return hit;
    console.error(`[warn] CDP_TAB=${kw} 没匹配上，退回第一个业务页: ${pages[0].url}`);
  }
  return pages[0];
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener('open', () => resolve(api));
    ws.addEventListener('error', (e) => reject(new Error('WebSocket 错误: ' + (e.message || e))));
    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id && pending.has(msg.id)) {
        const { resolve: res, reject: rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(JSON.stringify(msg.error)));
        else res(msg.result);
      }
    });
    const send = (method, params = {}) => {
      const myId = ++id;
      return new Promise((res, rej) => {
        // ★ 必须 clearTimeout：否则每次调用的 60s 计时器会拖住事件循环，
        //   node 进程要等满 60 秒才退出（批量抓取时每站白等 1 分钟）。
        const timer = setTimeout(() => {
          if (pending.has(myId)) { pending.delete(myId); rej(new Error(`超时: ${method}`)); }
        }, 30000);
        pending.set(myId, {
          resolve: (v) => { clearTimeout(timer); res(v); },
          reject: (e) => { clearTimeout(timer); rej(e); },
        });
        ws.send(JSON.stringify({ id: myId, method, params }));
      });
    };
    const api = {
      send,
      close: () => ws.close(),
      async evaluate(expression) {
        const r = await send('Runtime.evaluate', {
          expression, returnByValue: true, awaitPromise: true,
          userGesture: true,
        });
        if (r.exceptionDetails) {
          throw new Error('页面 JS 异常: ' + JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails));
        }
        return r.result ? r.result.value : undefined;
      },
      async goto(url) {
        await send('Page.navigate', { url });
        await sleep(NAV_WAIT);
      },
      async newTab(url) {
        const r = await fetch(`http://${HOST}:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })
          .catch(() => fetch(`http://${HOST}:${PORT}/json/new?${encodeURIComponent(url)}`));
        await sleep(NAV_WAIT);
        return r;
      },
    };
  });
}

async function readAccumulated(api, scrolls) {
  if (scrolls <= 0) return await api.evaluate('document.body ? document.body.innerText : ""');
  const seen = new Set();
  const order = [];
  for (let i = 0; i <= scrolls; i++) {
    const chunk = await api.evaluate('document.body ? document.body.innerText : ""');
    for (const line of String(chunk || '').split('\n')) {
      const k = line.trim();
      if (!k || seen.has(k)) continue;
      seen.add(k);
      order.push(k);
    }
    const atBottom = await api.evaluate(
      '(function(){var h=document.documentElement.scrollHeight;window.scrollTo(0,h);' +
      'return (window.innerHeight+window.scrollY)>=h-50;})()'
    );
    await sleep(2500);
    if (atBottom && i > 0) break;
  }
  return order.join('\n');
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd) {
    console.error('用法: node edge_cdp.js list|text [n]|html|links|eval <js>|goto <url>|newtab <url>|wait <ms>');
    process.exit(2);
  }
  const targets = await listTargets();

  if (cmd === 'list') {
    for (const t of targets) {
      if (t.type !== 'page') continue;
      console.log(`- [${(t.title || '').slice(0, 60)}] ${t.url}`);
    }
    return;
  }
  if (cmd === 'newtab') {
    const url = rest[0];
    if (!url) throw new Error('newtab 需要 url');
    await fetch(`http://${HOST}:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })
      .catch(async () => fetch(`http://${HOST}:${PORT}/json/new?${encodeURIComponent(url)}`));
    await sleep(NAV_WAIT);
    console.log(`[已新开] ${url}`);
    return;
  }

  const t = pickTarget(targets);
  const api = await connect(t.webSocketDebuggerUrl);
  try {
    if (cmd === 'goto') {
      await api.goto(rest[0]);
      console.log(`[已跳转] ${rest[0]}`);
    } else if (cmd === 'wait') {
      await sleep(parseInt(rest[0] || '3000', 10));
      console.log('[已等待]');
    } else if (cmd === 'text') {
      console.log(await readAccumulated(api, parseInt(rest[0] || '0', 10)));
    } else if (cmd === 'html') {
      console.log(await api.evaluate('document.documentElement.outerHTML'));
    } else if (cmd === 'links') {
      const out = await api.evaluate(`JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(function(a){
        return {t:(a.innerText||a.title||'').replace(/\\s+/g,' ').trim().slice(0,80), h:a.href};
      }).filter(function(x){return x.t.length>3;}))`);
      const arr = JSON.parse(out || '[]');
      const seen = new Set();
      for (const x of arr) {
        if (seen.has(x.h)) continue;
        seen.add(x.h);
        console.log(`- ${x.t}\n  ${x.h}`);
      }
    } else if (cmd === 'eval') {
      const v = await api.evaluate(rest.join(' '));
      console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 2));
    } else {
      throw new Error(`未知命令: ${cmd}`);
    }
  } finally {
    api.close();
  }
}

main().then(() => process.exit(0)).catch((e) => { console.error('❌ ' + e.message); process.exit(1); });
