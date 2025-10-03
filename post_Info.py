import datetime
import requests
import re

# 供查詢今日個股資訊
def stock_info(keyword):
    today = datetime.datetime.now().strftime("%Y%m%d")
    API_Foreign = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
    API_Trust = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
    API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"

    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕

    Foreign_text = None
    Trust_text = None
    Proprietary_text = None

    #外資買賣超
    try:
        #外資
        res = requests.get(API_Foreign, headers=headers, verify=False)
        data = res.json()

        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]

            if re.search(r'售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword in stock_id or keyword in stock_name:
                Foreign_text = f"外資：{row[5]} 股"
                break
    except Exception :
        Foreign_text = None

    #投信買賣超
    try:        
        #投信
        res = requests.get(API_Trust, headers=headers, verify=False)
        data = res.json()

        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]

            if re.search(r'售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword in stock_id or keyword in stock_name:
                Trust_text = f"投信：{row[5]} 股"
                break
    except Exception :
        Trust_text = None

    #自營商買賣超
    try:  
        #自營商
        res = requests.get(API_Proprietary, headers=headers, verify=False)
        data = res.json()

        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[0], row[1]

            if re.search(r'購|售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword in stock_id or keyword in stock_name:
                Proprietary_text = f"自營商：{row[4]} 股"
                break
    except Exception :
        Proprietary_text = None

    reply = f"{keyword} (今盤後買賣超)\n"
    reply += (Foreign_text + "\n") if Foreign_text else "外資：🚫暫未更新" + "\n"
    reply += (Trust_text + "\n") if Trust_text else "投信：🚫暫未更新" + "\n"
    reply += (Proprietary_text + "\n") if Proprietary_text else "自營商：🚫暫未更新"
    
    if not (Foreign_text or Trust_text or Proprietary_text):
        return f"❌找不到「{keyword}」相關資料。"
    return reply.strip()

#大盤總體資訊
def market_pnfo():
    today = datetime.datetime.now().strftime("%Y%m%d")
    API_Net_Total = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"

    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕

    Net_Total_text = None
    reply = ""
    net_amount = 0
    net_total = 0

    #三大法買賣金額統計
    try:
        res = requests.get(API_Net_Total, headers=headers, verify=False)
        data = res.json()

        # data["data"] 格式: [單位名稱, 買進金額, 賣出金額, 買賣差額]
        for i in range(3, -1, -1):
            row = data["data"][i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100  # 截斷兩位小數

            if i == 3:
                reply += f"{row[0][:5]} : {net_amount}\u200B億\n"   # \u200B -> 阻止LINE自動連接
            else:
                reply += f"{row[0]} : {net_amount}\u200B億\n"

        net_total = int(net_total * 100) / 100  # 截斷兩位小數
        reply += f"合計金額 : {net_total}\u200B億"

    except Exception :
        Net_Total_text = None

    return reply.strip()