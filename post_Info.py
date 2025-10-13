import re
import urllib3
import datetime
import aiohttp
import asyncio

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
today = datetime.datetime.now().strftime("%Y%m%d")
#today = '20251009'

async def fetch_json(session, url):
    async with session.get(url, ssl=False) as res:
        return await res.json()

# 📊 個股盤後資訊 (外資、投信、自營商、借券) - 非同步版
async def stock_info_async(keyword):
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate"}
    base = "https://www.twse.com.tw/rwd/zh"

    apis = {
        "外資": f"{base}/fund/TWT38U?response=json&date={today}",
        "投信": f"{base}/fund/TWT44U?response=json&date={today}",
        "自營商": f"{base}/fund/TWT43U?response=json&date={today}",
        "借券": f"{base}/marginTrading/TWT93U?response=json&date={today}",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # 同時併發 4 個請求
        responses = await asyncio.gather(
            *[fetch_json(session, url) for url in apis.values()],
            return_exceptions=True
        )

    results = dict(zip(apis.keys(), responses))
    reply = f"{keyword} (今盤後買賣超)\n"

    # ---------------- 外資 ----------------
    try:
        data = results["外資"]["data"]
        text = None
        for row in data:
            stock_id, stock_name = row[1], row[2]
            if re.search(r'售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                text = f"外資：{row[5]} 股"
                break
        reply += (text + "\n") if text else "外資：🚫 暫未更新\n"
    except Exception:
        reply += "外資：🚫 暫未更新\n"

    # ---------------- 投信 ----------------
    try:
        data = results["投信"]["data"]
        text = None
        for row in data:
            stock_id, stock_name = row[1], row[2]
            if re.search(r'售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                text = f"投信：{row[5]} 股"
                break
        reply += (text + "\n") if text else "投信：🚫 暫未更新\n"
    except Exception:
        reply += "投信：🚫 暫未更新\n"

    # ---------------- 自營商 ----------------
    try:
        data = results["自營商"]["data"]
        text = None
        for row in data:
            stock_id, stock_name = row[0], row[1]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                text = f"自營商：{row[4]} 股"
                break
        reply += (text + "\n") if text else "自營商：🚫 暫未更新\n"
    except Exception:
        reply += "自營商：🚫 暫未更新\n"

    # ---------------- 借券 ----------------
    try:
        data = results["借券"]["data"]
        text = None
        for row in data:
            stock_id, stock_name = row[0], row[1]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                diff = int(row[9].replace(',', '')) - int(row[10].replace(',', ''))
                text = f"借券賣出：{diff:,} 股"
                break
        reply += (text + "\n") if text else "借券賣出：🚫 暫未更新\n"
    except Exception:
        reply += "借券賣出：🚫 暫未更新\n"

    return reply.strip()


# 提供同步介面給 LINE Bot 呼叫
def stock_info(keyword):
    return asyncio.run(stock_info_async(keyword))


# 📈 大盤盤後總體資訊 - 非同步版
async def market_pnfo_async():
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate"}
    base = "https://www.twse.com.tw/rwd/zh"

    apis = {
        "三大法人買賣金額": f"{base}/fund/BFI82U?response=json&date={today}",
        "大盤融資金額": f"{base}/marginTrading/MI_MARGN?response=json&date={today}"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        # 同時併發多個 API
        responses = await asyncio.gather(
            *[fetch_json(session, url) for url in apis.values()],
            return_exceptions=True
        )

    results = dict(zip(apis.keys(), responses))

    reply = "📉大盤盤後詳細資訊📈\n"

    # ---------------- 三大法人買賣金額 ----------------
    try:
        data = results["三大法人買賣金額"]["data"]
        net_total = 0
        for i in range(3, -1, -1):
            row = data[i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100
            name = row[0][:5] if i == 3 else row[0]
            reply += f"{name} : {net_amount}億\n"
        net_total = int(net_total * 100) / 100
        reply += f"合計金額 : {net_total}億\n"
        reply += "-----------------------------\n"
    except Exception:
        reply += "三大法人買賣金額：🚫 暫未更新\n"

    # ---------------- 大盤融資金額 ----------------
    try:
        row = results["大盤融資金額"]["tables"][0]["data"]
        prev_margin = int(row[2][4].replace(',', '')) / 1e5
        today_margin = int(row[2][5].replace(',', '')) / 1e5
        margin_delta = today_margin - prev_margin
        reply += f"融資金額增減 : {margin_delta:.2f}億\n"
        reply += f"融資額金水位 : {today_margin:.2f}億\n"
    except Exception:
        reply += f"融資金額增減 : 🚫 暫未更新\n"
        reply += f"融資額金水位 : 🚫 暫未更新\n"

    return reply.strip()

# 提供同步介面給 LINE Bot 呼叫
def market_pnfo():
    return asyncio.run(market_pnfo_async())
