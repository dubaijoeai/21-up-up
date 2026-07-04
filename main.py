# -*- coding: utf-8 -*-
"""
A股每日盘后报告（网页版）
功能：抓取当日大盘资金流、行业/概念板块资金流排名、持续吸金板块、
      个股资金净流入排行、涨停板池、龙虎榜，生成一个网页，保存到 docs/index.html。
      配合 GitHub Pages 使用，每天自动更新同一个网址，直接打开浏览器就能看最新报告。

重要说明（请务必阅读）：
1. 本程序只做「客观数据汇总」，不做「预测明天涨跌」。任何号称能预测股价的程序都不可信，
   这里呈现的是资金流向、板块热度等参考信息，最终判断和决策请自己做，或咨询有资质的投资顾问。
2. 数据来自东方财富网（通过 akshare 库抓取），东财接口偶尔会抽风或改版，
   本脚本对每个数据源都做了独立的 try/except，某一项失败不会影响其他部分正常生成。
3. 如果某天报告里发现"某项抓取失败"，通常过一天会自动恢复；如果连续多天失败，
   大概率是 akshare 库或东财接口有更新，需要执行： pip install -U akshare 或到
   https://github.com/akfamily/akshare/issues 看看是否有人反馈同样问题。
"""

import os
import traceback
from datetime import datetime

import akshare as ak
import pandas as pd

pd.set_option("display.unicode.ambiguous_as_wide", True)
pd.set_option("display.unicode.east_asian_width", True)

NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
UPDATED_AT = NOW.strftime("%Y-%m-%d %H:%M:%S")
PERSISTENT_TOP_N = 15  # 判断"持续吸金"时，看每个周期榜单的前多少名
OUTPUT_PATH = "docs/index.html"


def safe_call(func_name, func, *args, **kwargs):
    """包一层安全调用，失败了返回 None 并打印原因，不让整个脚本崩溃"""
    try:
        df = func(*args, **kwargs)
        print(f"[OK] {func_name} 抓取成功，{len(df)} 行")
        return df
    except Exception as e:
        print(f"[FAIL] {func_name} 抓取失败：{e}")
        traceback.print_exc()
        return None


def df_to_html_table(df, cols=None, top_n=10, highlight_col=None):
    """把 DataFrame 转成简单的 HTML 表格，只取前 top_n 行、指定列"""
    if df is None or len(df) == 0:
        return "<p class='muted'>（今日该项数据抓取失败，暂无数据）</p>"
    if cols:
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
    df = df.head(top_n)

    html = "<div class='table-wrap'><table>"
    html += "<tr>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr>"
    for _, row in df.iterrows():
        html += "<tr>"
        for c in df.columns:
            val = row[c]
            css = ""
            try:
                if c == highlight_col or "涨跌幅" in str(c) or "净流入" in str(c):
                    fv = float(val)
                    if fv > 0:
                        css = "class='up'"
                    elif fv < 0:
                        css = "class='down'"
            except (ValueError, TypeError):
                pass
            html += f"<td {css}>{val}</td>"
        html += "</tr>"
    html += "</table></div>"
    return html


def fetch_market_overview():
    """大盘整体资金流"""
    return safe_call("大盘资金流 stock_market_fund_flow", ak.stock_market_fund_flow)


def fetch_sector_fund_flow(sector_type="行业资金流", period="今日"):
    """
    通用板块资金流排名抓取。
    sector_type: "行业资金流" 或 "概念资金流"
    period: "今日" / "5日" / "10日"（akshare 原生支持这几个周期的累计净流入排名）
    """
    df = safe_call(
        f"{sector_type}排名（{period}）",
        ak.stock_sector_fund_flow_rank,
        indicator=period,
        sector_type=sector_type,
    )
    if df is not None:
        net_col = [c for c in df.columns if "主力净流入-净额" in c]
        if net_col:
            df = df.sort_values(net_col[0], ascending=False)
    return df


def fetch_persistent_hot_sectors(sector_type="行业资金流", top_n=PERSISTENT_TOP_N):
    """
    找"持续吸金板块"：分别取 今日 / 5日 / 10日 的板块资金流排名前 top_n 名，
    三个榜单的交集，说明这个板块不是资金一日游，而是持续被关注。
    """
    boards = {}
    dfs = {}
    for period in ["今日", "5日", "10日"]:
        df = fetch_sector_fund_flow(sector_type=sector_type, period=period)
        dfs[period] = df
        if df is None:
            return None, dfs
        name_col = "名称" if "名称" in df.columns else df.columns[1]
        boards[period] = set(df[name_col].head(top_n).tolist())

    persistent = boards["今日"] & boards["5日"] & boards["10日"]
    return persistent, dfs


def fetch_individual_fund_flow_rank():
    """个股资金净流入排行（今日）"""
    return safe_call(
        "个股资金流排名 stock_individual_fund_flow_rank",
        ak.stock_individual_fund_flow_rank,
        indicator="今日",
    )


def fetch_zt_pool():
    """涨停板池 —— 判断今日情绪热度、连板情况"""
    date_str = NOW.strftime("%Y%m%d")
    return safe_call("涨停板池 stock_zt_pool_em", ak.stock_zt_pool_em, date=date_str)


def fetch_lhb():
    """龙虎榜每日明细 —— 主力/游资动向"""
    date_str = NOW.strftime("%Y%m%d")
    return safe_call(
        "龙虎榜 stock_lhb_detail_em",
        ak.stock_lhb_detail_em,
        start_date=date_str,
        end_date=date_str,
    )


def render_persistent_sectors_html(persistent, label):
    """把'持续吸金板块'交集渲染成简单列表"""
    if persistent is None:
        return f"<p class='muted'>（{label}数据抓取失败，暂无法计算）</p>"
    if len(persistent) == 0:
        return f"<p class='muted'>今日没有{label}同时进入 今日/5日/10日 前{PERSISTENT_TOP_N}名，暂无持续吸金标的</p>"
    items = "".join(f"<span class='tag'>{name}</span>" for name in persistent)
    return f"<div class='tag-wrap'>{items}</div>"


def build_report_html():
    market_df = fetch_market_overview()

    persistent_industry, industry_dfs = fetch_persistent_hot_sectors(sector_type="行业资金流")
    persistent_concept, concept_dfs = fetch_persistent_hot_sectors(sector_type="概念资金流")

    industry_today_df = industry_dfs.get("今日")
    concept_today_df = concept_dfs.get("今日")

    indiv_df = fetch_individual_fund_flow_rank()
    zt_df = fetch_zt_pool()
    lhb_df = fetch_lhb()

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股每日盘后报告 - {TODAY}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
         max-width: 900px; margin: 0 auto; padding: 20px; background: #fafafa; color: #222; }}
  h1 {{ font-size: 22px; }}
  h2 {{ font-size: 17px; margin-top: 32px; border-left: 4px solid #d0021b; padding-left: 10px; }}
  .muted {{ color: #999; font-size: 13px; }}
  .updated {{ color: #999; font-size: 12px; margin-bottom: 20px; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #e5e5e5; padding: 6px 8px; text-align: left; white-space: nowrap; }}
  th {{ background: #f5f5f5; }}
  .up {{ color: #d0021b; font-weight: 600; }}
  .down {{ color: #0a8f3c; font-weight: 600; }}
  .tag-wrap {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .tag {{ background: #fff0f0; color: #d0021b; border: 1px solid #ffd0d0;
          padding: 4px 12px; border-radius: 16px; font-weight: 600; font-size: 13px; }}
  .disclaimer {{ margin-top: 30px; padding: 12px; background: #fff8e6; border: 1px solid #ffe4a3;
                 border-radius: 6px; font-size: 12px; color: #7a5c00; }}
</style>
</head>
<body>
  <h1>📊 A股每日盘后报告 —— {TODAY}</h1>
  <p class="updated">最后更新时间：{UPDATED_AT}（北京时间，每个交易日收盘后自动更新）</p>
  <p class="muted">本报告仅汇总客观市场数据（资金流向、板块热度、涨停/龙虎榜等），不构成任何投资建议，也不对次日涨跌做预测。数据源：东方财富网，通过 akshare 抓取。</p>

  <h2>1️⃣ 大盘资金流概览（最近几个交易日）</h2>
  {df_to_html_table(market_df, top_n=5)}

  <h2>2️⃣ 今日行业板块资金流排名 Top10</h2>
  {df_to_html_table(industry_today_df, top_n=10)}

  <h2>🔥 持续吸金行业板块（同时进入 今日/5日/10日 前{PERSISTENT_TOP_N}名）</h2>
  <p class="muted">连续多日被资金关注，比单日排名更有参考价值，但同样不代表接下来一定继续上涨。</p>
  {render_persistent_sectors_html(persistent_industry, "行业板块")}

  <h2>3️⃣ 今日概念板块资金流排名 Top10</h2>
  {df_to_html_table(concept_today_df, top_n=10)}

  <h2>🔥 持续吸金概念板块（同时进入 今日/5日/10日 前{PERSISTENT_TOP_N}名）</h2>
  {render_persistent_sectors_html(persistent_concept, "概念板块")}

  <h2>4️⃣ 今日个股资金净流入排行 Top15</h2>
  {df_to_html_table(indiv_df, top_n=15)}

  <h2>5️⃣ 今日涨停板池</h2>
  {df_to_html_table(zt_df, top_n=15)}

  <h2>6️⃣ 今日龙虎榜明细</h2>
  {df_to_html_table(lhb_df, top_n=15)}

  <div class="disclaimer">
  ⚠️ 免责声明：以上数据仅供研究参考，市场有风险，任何决策请结合自己的判断，必要时咨询有资质的投资顾问。本报告由自动化脚本生成，不构成任何投资建议。
  </div>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    report_html = build_report_html()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"报告已生成：{OUTPUT_PATH}")
