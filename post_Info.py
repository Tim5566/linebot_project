import datetime
import requests
import re
import urllib3
import pandas as pd
from io import StringIO
from zoneinfo import ZoneInfo

from get_trading_holidays import is_trading_day
from tools import to_minguo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 忽略警告

import time as _time

#today = '20260327'

def fetch_with_retry(url, today, date_key="date", retries=3, delay=1.5):
    """發出 GET 請求，若回傳日期不是今天則自動重試最多 retries 次。"""
    _headers = {"User-Agent": "Mozilla/5.0"}
    today_d = re.sub(r"[^\d]", "", today)
    for attempt in range(retries):
        try:
            res = requests.get(url, headers=_headers, verify=False, timeout=10)
            data = res.json()
            api_date = re.sub(r"[^\d]", "", str(data.get(date_key, "")))
            if today_d in api_date:
                return data
            print(f"[retry {attempt+1}/{retries}] 日期不符 api={api_date} today={today_d}")
        except Exception as e:
            print(f"[retry {attempt+1}/{retries}] 請求失敗: {e}")
        _time.sleep(delay)
    return None


#上市or上櫃公司代碼名稱存檔 (初始讀取一次)
try:
    TWSE = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date=20260309"
    OTC = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date=20260309"
    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕
    TWSE_res = requests.get(TWSE, headers=headers, verify=False)
    OTC_res = requests.get(OTC, headers=headers, verify=False)
    TWSE_data = TWSE_res.json()
    OTC_data = OTC_res.json()
    TWSE_data_code = [item[0] for item in TWSE_data["data"]]
    OTC_data_code = [item[0] for item in OTC_data["tables"][0]["data"]]
    TWSE_data_name = [item[1] for item in TWSE_data["data"]]
    OTC_data_name = [item[1] for item in OTC_data["tables"][0]["data"]]
except Exception:
    TWSE_data_code = []
    OTC_data_code = []
    TWSE_data_name = []
    OTC_data_name = []
    print(f"❌ 無法取得資料: {e}")

# 供查詢今日個股資訊
def stock_info(keyword):
    today = datetime.datetime.now().strftime("%Y%m%d")

    #判斷是否假日或盤後更新
    if not is_trading_day():
        return f"📢 今日週末或連假未開盤❗0"
    elif datetime.datetime.now(ZoneInfo("Asia/Taipei")).hour < 15:
        return f"📢 今盤後資料尚未更新❗\n請於今日 15:00 後再試一次。"

    #變數初始化
    Disposal_text = None
    Foreign_text = None
    Trust_text = None
    Proprietary_text = None
    Short_sale_text = None   
    reply = f"{keyword} (今盤後買賣超)\n"

    #上市個股資料
    if keyword in TWSE_data_code or keyword in TWSE_data_name:
        API_Foreign = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        API_Trust = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        API_Short_Sale = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?response=json&date={today}"
        API_Disposal = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"

        #處置股
        try:
            res = requests.get(API_Disposal, headers=headers, verify=False)
            data = res.json()

            for row in data["data"]:
                stock_id, stock_name = row[2], row[3]
                disposal_end_date = row[6][10:]
                if keyword in stock_id or keyword in stock_name:
                    Disposal_text = f"處置：⭕ 至 {disposal_end_date}"
                    break
                else:
                    Disposal_text = "處置：❌"
        except Exception:
            Disposal_text = None

        # 外資買賣超
        try:
            data = fetch_with_retry(API_Foreign, today)
            if data is None:
                Foreign_text = None
            else:
                for row in data["data"]:
                    stock_id, stock_name = row[1], row[2]
                    if re.search(r'購|售|認購|認售', stock_name):
                        continue  # 跳過選擇權
                    if keyword in stock_id or keyword in stock_name:
                        Foreign_text = f"外資：{row[5]} 股"
                        break
        except Exception:
            Foreign_text = None

        # 投信買賣超
        try:
            data = fetch_with_retry(API_Trust, today)
            if data is None:
                Trust_text = None
            else:
                for row in data["data"]:
                    stock_id, stock_name = row[1], row[2]
                    if re.search(r'購|售|認購|認售', stock_name):
                        continue
                    if keyword in stock_id or keyword in stock_name:
                        Trust_text = f"投信：{row[5]} 股"
                        break
        except Exception:
            Trust_text = None

        # 自營商買賣超
        try:
            data = fetch_with_retry(API_Proprietary, today)
            if data is None:
                Proprietary_text = None
            else:
                for row in data["data"]:
                    stock_id, stock_name = row[0], row[1]
                    if re.search(r'購|售|認購|認售', stock_name):
                        continue
                    if keyword in stock_id or keyword in stock_name:
                        Proprietary_text = f"自營商：{row[10]} 股"
                        break
        except Exception:
            Proprietary_text = None

        # 借卷賣出
        try:
            data = fetch_with_retry(API_Short_Sale, today)
            if data is None:
                Short_sale_text = None
            else:
                for row in data["data"]:
                    stock_id, stock_name = row[0], row[1]
                    if re.search(r'購|售|認購|認售', stock_name):
                        continue
                    if keyword in stock_id or keyword in stock_name:
                        Short_sale_text = f"借卷賣出：{int(row[9].replace(',', '')) - int(row[10].replace(',', '')):,} 股"
                        break
        except Exception:
            Short_sale_text = None

        reply += (Disposal_text + "\n") if Disposal_text else "處置：🚫 暫未更新\n"
        reply += (Foreign_text + "\n") if Foreign_text else "外資：🚫 暫未更新\n"
        reply += (Trust_text + "\n") if Trust_text else "投信：🚫 暫未更新\n"
        reply += (Proprietary_text + "\n") if Proprietary_text else "自營商：🚫 暫未更新\n"
        reply += (Short_sale_text + "\n") if Short_sale_text else "借卷賣出：🚫 暫未更新\n"
        return reply.strip()

    elif keyword in OTC_data_code or keyword in OTC_data_name:
        API_institutional = f"https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
        API_Disposal = f"https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
        API_Short_Sale = f"https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"

        #處置股
        try:
            res = requests.get(API_Disposal, headers=headers, verify=False)
            data = res.json()

            for row in data["tables"][0]["data"]:
                stock_id, stock_name = row[2], row[3].split("(")[0]
                disposal_end_date = row[5][10:]
                if keyword in stock_id or keyword in stock_name:
                    Disposal_text = f"處置：⭕ 至 {disposal_end_date}"
                    break
            else:
                Disposal_text = "處置：❌"
        except Exception:
            Disposal_text = None

        # 上櫃三大法人：只請求一次，外資/投信/自營商共用
        try:
            # 上櫃日期格式為民國，轉成西元後比對
            def otc_date_ok(data):
                raw = data[0]["Date"] if data else ""
                return re.sub(r"[^\d]", "", to_minguo(raw)) == re.sub(r"[^\d]", "", today)

            inst_data = None
            for attempt in range(3):
                res = requests.get(API_institutional, headers=headers, verify=False, timeout=10)
                inst_data = res.json()
                if otc_date_ok(inst_data):
                    break
                import time as _t; _t.sleep(1.5)

            if not otc_date_ok(inst_data):
                Foreign_text = Trust_text = Proprietary_text = None
            else:
                for row in inst_data:
                    stock_id, stock_name = row["SecuritiesCompanyCode"], row["CompanyName"]
                    if re.search(r'購|售|認購|認售', stock_name):
                        continue
                    if keyword in stock_id or keyword in stock_name:
                        Foreign_text     = f"外資：{int(row['Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference']):,} 股"
                        Trust_text       = f"投信：{int(row['SecuritiesInvestmentTrustCompanies-Difference']):,} 股"
                        Proprietary_text = f"自營商：{int(row['Dealers-Difference']):,} 股"
                        break
        except Exception:
            Foreign_text = Trust_text = Proprietary_text = None

        # 借卷賣出
        try:
            res = requests.get(API_Short_Sale, headers=headers, verify=False)
            data = res.json()

            if not keyword.isdigit():
                idx = OTC_data_name.index(keyword) 
                keyword = OTC_data_code[idx]

            if today not in data.get("date", ""):
                Short_sale_text = None
            else:
                for row in data["tables"][0]["data"]:
                    stock_id = row[0]
                    if keyword in stock_id:
                        Short_sale_text = f"借卷賣出：{int(row[9].replace(',', '')) - int(row[10].replace(',', '')):,} 股"
                        break
        except Exception:
            Short_sale_text = None

        reply += (Disposal_text + "\n") if Disposal_text else "處置：🚫 暫未更新\n"
        reply += (Foreign_text + "\n") if Foreign_text else "外資：🚫 暫未更新\n"
        reply += (Trust_text + "\n") if Trust_text else "投信：🚫 暫未更新\n"
        reply += (Proprietary_text + "\n") if Proprietary_text else "自營商：🚫 暫未更新\n"
        reply += (Short_sale_text + "\n") if Short_sale_text else "借卷賣出：🚫 暫未更新\n"
        return reply.strip()
    
    else:
        return f"❌找不到「{keyword}」今盤後資料。"

# 大盤總體資訊
def market_pnfo():
    today = datetime.datetime.now().strftime("%Y%m%d")

    API_Net_Amount = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    API_MarginDelta = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"

    reply = "📉大盤盤後詳細資訊📈\n"

    # 三大法買賣金額統計
    try:
        net_amount = 0
        net_total = 0
        headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕
        res = requests.get(API_Net_Amount, headers=headers, verify=False)
        data = res.json()  # data["data"] 格式: [單位名稱, 買進金額, 賣出金額, 買賣差額]

        for i in range(3, -1, -1):
            row = data["data"][i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100  # 截斷兩位小數
            if i == 3:
                reply += f"{row[0][:5]} : {net_amount}億\n"
            else:
                reply += f"{row[0]} : {net_amount}億\n"
        net_total = int(net_total * 100) / 100
        reply += f"合計金額 : {net_total}億\n"
        reply += "---------------------------------------------\n"
    except Exception:
        Net_Amount_text = None

    # 大盤融資金額統計
    try:
        res = requests.get(API_MarginDelta, headers=headers, verify=False)
        data = res.json()

        row = data["tables"][0]["data"]
        prev_margin = int(row[2][4].replace(',', '')) / 1e5
        today_margin = int(row[2][5].replace(',', '')) / 1e5
        margin_delta = today_margin - prev_margin
        reply += f"融資金額增減 : {margin_delta:.2f}億\n"
        reply += f"融資額金水位 : {today_margin:.2f}億\n"
    except Exception:
        reply += f"融資金額增減 : 🚫 暫未更新\n"
        reply += f"融資額金水位 : 🚫 暫未更新\n"

    return reply.strip()
