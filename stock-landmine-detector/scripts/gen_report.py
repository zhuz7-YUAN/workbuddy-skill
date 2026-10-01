#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股排雷器 - 报告生成器
用法（AI 调用）：
  python gen_report.py --code hk02533 --name 黑芝麻智能 --data '{"net_profit":3.13,...}' --out report.html

数据字段（单位：亿元人民币，缺失字段传 None 或省略）：
  net_profit        归母净利（GAAP）
  operating_profit  经营利润（亏损为负）
  fair_value_gain   公允价值变动收益（一次性，正为收益）
  adj_loss          经调整净亏损（非IFRS，正数=亏）
  eps_basic         基本EPS
  eps_diluted       摊薄EPS
  op_cash_flow      经营现金流（负为流出）
  pref_convertible  优先股/可转债规模（用于信号C分母）
  net_assets        净资产
  ps                市销率（亏损股看这个）
  revenue           营收
  notes             额外附注文字（字符串）

脚本只做：计算缺口、跑三个一票否决、渲染自包含 HTML（红涨绿跌）。
不联网、不抓数——数据由调用方（AI）填好传进来，保证口径可控。
"""
import argparse
import json
import html
import sys
from datetime import datetime

RED = "#d62728"   # 涨/风险高
GREEN = "#2ca02c" # 跌/安全
INK = "#1a1a1a"
BG = "#f7f7f5"
CARD = "#ffffff"

def verdict_color(level):
    return {"高危": RED, "黄灯": "#e8a33d", "绿灯": GREEN}.get(level, INK)

def run_checks(d):
    """返回 (steps, vetoes, level)"""
    steps = []
    np_ = d.get("net_profit")
    op_ = d.get("operating_profit")
    fv = d.get("fair_value_gain")
    adj = d.get("adj_loss")
    eps_b = d.get("eps_basic")
    eps_d = d.get("eps_diluted")
    ocf = d.get("op_cash_flow")
    pref = d.get("pref_convertible")
    na = d.get("net_assets")

    # Step1 缺口
    gap = None
    if np_ is not None and op_ is not None:
        gap = round(np_ - op_, 2)
    steps.append(("经营利润 vs 归母净利缺口",
                  f"归母净利 {np_} / 经营利润 {op_} → 缺口 {gap}",
                  "缺口为正且大 → 盈利非经营来源" if (gap and gap > 0) else "缺口正常或为负"))

    # Step2 公允价值
    steps.append(("公允价值变动一次性科目",
                  f"公允价值变动收益 {fv}",
                  "一次性、非现金、非经营，须剔除" if fv else "无大额一次性科目"))

    # Step3 经调整对照
    if adj is not None and np_ is not None:
        cmp = "GAAP 巨亏但经调整小亏 = 一次性科目作妖" if (np_ < 0 and adj < abs(np_)) else "经营与 GAAP 方向一致"
    else:
        cmp = "未提供经调整数据"
    steps.append(("经调整亏损对照",
                  f"经调整净亏损 {adj} / GAAP 归母 {np_}", cmp))

    # Step4 EPS 背离
    diverge = False
    if eps_b is not None and eps_d is not None:
        diverge = (eps_b > 0 and eps_d < 0)
    steps.append(("基本 vs 摊薄 EPS",
                  f"基本 {eps_b} / 摊薄 {eps_d}",
                  "背离 → 稀释证券吞噬利润" if diverge else "未背离"))

    # Step5 现金流试金石
    ocf_bad = False
    if ocf is not None:
        ocf_bad = ocf < 0
    steps.append(("经营现金流试金石",
                  f"经营现金流 {ocf}",
                  "持续为负 → 纸面富贵（硬反向指标）" if ocf_bad else "现金流为正/正常"))

    # Step6 研发资本化（本脚本仅占位，AI 填 ratio 时附 notes）
    steps.append(("研发资本化突变", d.get("rd_note", "未自动检测，需人工核对附注"),
                  "资本化率突跳/远高于同行 → 黄灯"))

    # Step7 收入确认质量
    steps.append(("收入确认质量", d.get("rev_note", "需核对应收/合同负债增速"),
                  "应收暴涨、合同负债萎缩 → 收入确认激进"))

    # 三个一票否决
    vetoes = []
    if np_ is not None and op_ is not None and fv is not None:
        if np_ > 0 and op_ < 0 and fv > 0 and (np_ - op_) > 10:
            vetoes.append(("信号A", "归母靠一次性公允价值转正，经营仍大额亏", True))
    if ocf is not None and np_ is not None:
        if ocf < 0 and abs(ocf) > (np_ if np_ else 0):
            vetoes.append(("信号B", "经营现金流为负且缺口大于净利润", True))
    if diverge and pref is not None and na is not None and na > 0:
        if pref > 0.3 * na:
            vetoes.append(("信号C", "摊薄击穿基本EPS，稀释证券>净资产30%", True))

    level = "高危" if vetoes else ("黄灯" if (gap and gap > 0) or ocf_bad or diverge else "绿灯")
    return steps, vetoes, level

def render(d, steps, vetoes, level, code, name):
    vu = d.get("verdict_user", "")
    notes = d.get("notes", "")
    step_rows = "".join(
        f'<tr><td>{html.escape(t)}</td><td>{html.escape(v)}</td><td>{html.escape(c)}</td></tr>'
        for t, v, c in steps)
    veto_html = "".join(
        f'<li style="color:{RED}"><b>{k}</b>：{html.escape(desc)}</li>' for k, desc, _ in vetoes) or \
        f'<li style="color:{GREEN}">三个一票否决均未命中</li>'
    src = html.escape(d.get("source", "非 NeoData 标准团队源，仅供参考"))

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>排雷报告 {name} {code}</title></head><body style="margin:0;background:{BG};color:{INK};font-family:-apple-system,'Microsoft YaHei',sans-serif">
<div style="max-width:860px;margin:0 auto;padding:24px">
<div style="background:{CARD};border-radius:14px;padding:22px;box-shadow:0 2px 10px rgba(0,0,0,.06)">
<h1 style="margin:0 0 4px;font-size:22px">{html.escape(name)} <span style="color:#888;font-size:15px">{html.escape(code)}</span></h1>
<div style="display:inline-block;padding:6px 14px;border-radius:20px;color:#fff;background:{verdict_color(level)};font-weight:700;font-size:16px">结论：{level}</div>
<p style="color:#666;font-size:13px;margin:10px 0 0">生成时间 {datetime.now():%Y-%m-%d %H:%M} ｜ 数据来源：{src}</p>
</div>
<div style="background:{CARD};border-radius:14px;padding:20px;margin-top:16px;box-shadow:0 2px 10px rgba(0,0,0,.06)">
<h2 style="font-size:17px;margin:0 0 12px">一票否决清单</h2><ul style="line-height:1.9;font-size:14px">{veto_html}</ul>
</div>
<div style="background:{CARD};border-radius:14px;padding:20px;margin-top:16px;box-shadow:0 2px 10px rgba(0,0,0,.06)">
<h2 style="font-size:17px;margin:0 0 12px">年报排雷 7 步法</h2>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<tr style="background:#f0f0ee;text-align:left"><th style="padding:8px">步骤</th><th style="padding:8px">数据</th><th style="padding:8px">判读</th></tr>
{step_rows}</table>
</div>
{'<div style="background:'+CARD+';border-radius:14px;padding:20px;margin-top:16px"><h2 style="font-size:17px">补充说明</h2><p style="font-size:14px;line-height:1.7">'+html.escape(notes)+'</p></div>' if notes else ''}
<p style="color:#999;font-size:12px;margin-top:18px;text-align:center">本报告由「个股排雷器」skill 自动生成，非交易建议。红涨绿跌配色。</p>
</div></body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--data", required=True, help="JSON 字符串")
    ap.add_argument("--out", default="report.html")
    a = ap.parse_args()
    try:
        d = json.loads(a.data)
    except Exception as e:
        print("DATA_JSON_ERROR:", e, file=sys.stderr); sys.exit(2)
    steps, vetoes, level = run_checks(d)
    html_out = render(d, steps, vetoes, level, a.code, a.name)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"OK|level={level}|vetoes={len(vetoes)}|out={a.out}")

if __name__ == "__main__":
    main()
