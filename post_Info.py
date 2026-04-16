import datetime
import requests
import re
import urllib3
import concurrent.futures
from zoneinfo import ZoneInfo

from get_trading_holidays import is_trading_day
from tools import to_minguo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import time as _time

headers = {"User-Agent": "Mozilla/5.0"}

def get_today():
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")

def fetch_with_retry(url, today, date_key="date", retries=3, delay=1.5):
    """發出 GET 請求，若回傳日期不是今天則自動重試最多 retries 次。"""
    today_d = re.sub(r"[^\d]", "", today)
    for attempt in range(retries):
        try:
            res = requests.get(url, headers=headers, verify=False, timeout=10)
            data = res.json()
            api_date = re.sub(r"[^\d]", "", str(data.get(date_key, "")))
            if today_d in api_date:
                return data
            print(f"[retry {attempt+1}/{retries}] 日期不符 api={api_date} today={today_d}")
        except Exception as e:
            print(f"[retry {attempt+1}/{retries}] 請求失敗: {e}")
        _time.sleep(delay)
    return None


# ── 上市 / 上櫃公司代碼名稱存檔（初始讀取一次）────────────────────────────────
try:
    TWSE_res = requests.get(
        "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date=20260309",
        headers=headers, verify=False)
    OTC_res = requests.get(
        "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date=20260309",
        headers=headers, verify=False)
    TWSE_data_raw  = TWSE_res.json()
    OTC_data_raw   = OTC_res.json()
    TWSE_data_code = [item[0] for item in TWSE_data_raw["data"]]
    TWSE_data_name = [item[1] for item in TWSE_data_raw["data"]]
    OTC_data_code  = [item[0] for item in OTC_data_raw["tables"][0]["data"]]
    OTC_data_name  = [item[1] for item in OTC_data_raw["tables"][0]["data"]]
except Exception as e:
    TWSE_data_code = []
    TWSE_data_name = []
    OTC_data_code  = []
    OTC_data_name  = []
    print(f"❌ 無法取得代碼清單: {e}")


# ── 上市個股查詢（並行） ──────────────────────────────────────────────────────
def _twse_disposal(keyword, api_url):
    try:
        res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
        data = res.json()
        for row in data["data"]:
            stock_id, stock_name = row[2], row[3]
            disposal_end_date = row[6][10:]
            if keyword in stock_id or keyword in stock_name:
                return f"處置：⭕ 至 {disposal_end_date}"
        return "處置：❌"
    except Exception:
        return None

def _twse_foreign(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today)
        if data is None:
            return None
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                return f"外資：{row[5]} 股"
    except Exception:
        return None

def _twse_trust(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today)
        if data is None:
            return None
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                return f"投信：{row[5]} 股"
    except Exception:
        return None

def _twse_proprietary(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today)
        if data is None:
            return None
        for row in data["data"]:
            stock_id, stock_name = row[0], row[1]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                return f"自營商：{row[10]} 股"
    except Exception:
        return None

def _twse_short_sale(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today)
        if data is None:
            return None
        for row in data["data"]:
            stock_id, stock_name = row[0], row[1]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                return f"借卷賣出：{int(row[9].replace(',', '')) - int(row[10].replace(',', '')):,} 股"
    except Exception:
        return None


# ── 上櫃個股查詢（並行） ──────────────────────────────────────────────────────
def _otc_disposal(keyword, api_url):
    try:
        res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
        data = res.json()
        for row in data["tables"][0]["data"]:
            stock_id, stock_name = row[2], row[3].split("(")[0]
            disposal_end_date = row[5][10:]
            if keyword in stock_id or keyword in stock_name:
                return f"處置：⭕ 至 {disposal_end_date}"
        return "處置：❌"
    except Exception:
        return None

def _otc_institutional(keyword, api_url, today):
    try:
        def otc_date_ok(data):
            raw = data[0]["Date"] if data else ""
            return re.sub(r"[^\d]", "", to_minguo(raw)) == re.sub(r"[^\d]", "", today)

        inst_data = None
        for attempt in range(3):
            res = requests.get(api_url, headers=headers, verify=False, timeout=10)
            inst_data = res.json()
            if otc_date_ok(inst_data):
                break
            print(f"[otc_inst retry {attempt+1}/3] 日期不符，等待重試...")
            _time.sleep(1.5)

        if not otc_date_ok(inst_data):
            return None, None, None

        for row in inst_data:
            stock_id, stock_name = row["SecuritiesCompanyCode"], row["CompanyName"]
            if re.search(r'購|售|認購|認售', stock_name):
                continue
            if keyword in stock_id or keyword in stock_name:
                foreign     = f"外資：{int(row['Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference']):,} 股"
                trust       = f"投信：{int(row['SecuritiesInvestmentTrustCompanies-Difference']):,} 股"
                proprietary = f"自營商：{int(row['Dealers-Difference']):,} 股"
                return foreign, trust, proprietary
        return None, None, None
    except Exception:
        return None, None, None

def _otc_short_sale(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today, date_key="date", retries=3, delay=1.5)
        if data is None:
            return None
        kw = keyword
        if not kw.isdigit():
            idx = OTC_data_name.index(kw)
            kw  = OTC_data_code[idx]
        for row in data["tables"][0]["data"]:
            if kw in row[0]:
                return f"借卷賣出：{int(row[9].replace(',', '')) - int(row[10].replace(',', '')):,} 股"
    except Exception:
        return None


# ── 主查詢函式 ────────────────────────────────────────────────────────────────
def stock_info(keyword):
    today = get_today()

    if not is_trading_day():
        return f"📢 今日週末或連假未開盤❗"
    elif datetime.datetime.now(ZoneInfo("Asia/Taipei")).hour < 15:
        return f"📢 今盤後資料尚未更新❗\n請於今日 15:00 後再試一次。"

    reply = f"{keyword} (今盤後買賣超)\n"

    # ── 上市 ──────────────────────────────────────────────────────────────────
    if keyword in TWSE_data_code or keyword in TWSE_data_name:
        API_Disposal    = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"
        API_Foreign     = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        API_Trust       = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        API_Short_Sale  = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?response=json&date={today}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            f_disposal    = executor.submit(_twse_disposal,    keyword, API_Disposal)
            f_foreign     = executor.submit(_twse_foreign,     keyword, API_Foreign,     today)
            f_trust       = executor.submit(_twse_trust,       keyword, API_Trust,       today)
            f_proprietary = executor.submit(_twse_proprietary, keyword, API_Proprietary, today)
            f_short_sale  = executor.submit(_twse_short_sale,  keyword, API_Short_Sale,  today)

            Disposal_text    = f_disposal.result()
            Foreign_text     = f_foreign.result()
            Trust_text       = f_trust.result()
            Proprietary_text = f_proprietary.result()
            Short_sale_text  = f_short_sale.result()

        reply += (Disposal_text    + "\n") if Disposal_text    else "處置：🚫 暫未更新\n"
        reply += (Foreign_text     + "\n") if Foreign_text     else "外資：🚫 暫未更新\n"
        reply += (Trust_text       + "\n") if Trust_text       else "投信：🚫 暫未更新\n"
        reply += (Proprietary_text + "\n") if Proprietary_text else "自營商：🚫 暫未更新\n"
        reply += (Short_sale_text  + "\n") if Short_sale_text  else "借卷賣出：🚫 暫未更新\n"
        return reply.strip()

    # ── 上櫃 ──────────────────────────────────────────────────────────────────
    elif keyword in OTC_data_code or keyword in OTC_data_name:
        API_institutional = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
        API_Disposal      = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
        API_Short_Sale    = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_disposal   = executor.submit(_otc_disposal,     keyword, API_Disposal)
            f_inst       = executor.submit(_otc_institutional, keyword, API_institutional, today)
            f_short_sale = executor.submit(_otc_short_sale,   keyword, API_Short_Sale,    today)

            Disposal_text                              = f_disposal.result()
            Foreign_text, Trust_text, Proprietary_text = f_inst.result()
            Short_sale_text                            = f_short_sale.result()

        reply += (Disposal_text    + "\n") if Disposal_text    else "處置：🚫 暫未更新\n"
        reply += (Foreign_text     + "\n") if Foreign_text     else "外資：🚫 暫未更新\n"
        reply += (Trust_text       + "\n") if Trust_text       else "投信：🚫 暫未更新\n"
        reply += (Proprietary_text + "\n") if Proprietary_text else "自營商：🚫 暫未更新\n"
        reply += (Short_sale_text  + "\n") if Short_sale_text  else "借卷賣出：🚫 暫未更新\n"
        return reply.strip()

    else:
        return f"❌找不到「{keyword}」今盤後資料。"


# ── 大盤總體資訊 ──────────────────────────────────────────────────────────────
def market_pnfo():
    today = get_today()

    API_Net_Amount  = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    API_MarginDelta = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"

    reply = "📉大盤盤後詳細資訊📈\n"

    # 三大法人買賣金額統計
    try:
        data = fetch_with_retry(API_Net_Amount, today)
        if data is None:
            raise Exception("日期不符或無資料")
        net_total = 0
        for i in range(3, -1, -1):
            row        = data["data"][i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100
            label = row[0][:5] if i == 3 else row[0]
            reply += f"{label} : {net_amount}億\n"
        reply += f"合計金額 : {int(net_total * 100) / 100}億\n"
        reply += "---------------------------------------------\n"
    except Exception:
        reply += "三大法人 : 🚫 暫未更新\n"
        reply += "---------------------------------------------\n"

    # 大盤融資金額統計
    try:
        data = fetch_with_retry(API_MarginDelta, today)
        if data is None:
            raise Exception("日期不符或無資料")
        row          = data["tables"][0]["data"]
        prev_margin  = int(row[2][4].replace(',', '')) / 1e5
        today_margin = int(row[2][5].replace(',', '')) / 1e5
        margin_delta = today_margin - prev_margin
        reply += f"融資金額增減 : {margin_delta:.2f}億\n"
        reply += f"融資額金水位 : {today_margin:.2f}億\n"
    except Exception:
        reply += "融資金額增減 : 🚫 暫未更新\n"
        reply += "融資額金水位 : 🚫 暫未更新\n"

    return reply.strip()

# ── 上市上櫃三大法人買賣超排行前50 ────────────────────────────────────────────────────
def twse_top50(today=None):
    if today is None:
        today = get_today()

    #TEST_DATE = "20260410"  # 測試用，完成後刪掉此行

    #API_Foreign     = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={TEST_DATE}"
    #API_Trust       = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={TEST_DATE}"
    #API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={TEST_DATE}"

    API_Foreign     = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
    API_Trust       = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
    API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"

    def _parse_top50(api_url, id_col, name_col, net_col):
        try:
            # 直接 GET，不用 fetch_with_retry（TWSE 這支 API 的 date 欄位不可靠）
            res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
            data = res.json()

            if data.get("stat") != "OK":
                print(f"[twse_top50] API stat: {data.get('stat')}")
                return None, None

            processed = []
            for row in data["data"]:
                name = row[name_col].strip()
                if re.search(r'購|售|認購|認售', name):
                    continue
                stock_id = row[id_col].strip()
                try:
                    net = int(row[net_col].replace(",", "")) // 1000
                except (ValueError, IndexError):
                    continue
                processed.append({"id": stock_id, "name": name, "net": net})

            buy  = sorted(processed, key=lambda x: x["net"], reverse=True)[:50]
            sell = sorted(processed, key=lambda x: x["net"])[:50]
            return buy, sell

        except Exception as e:
            print(f"[twse_top50] 查詢失敗: {e}")
            return None, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_foreign     = executor.submit(_parse_top50, API_Foreign,     1, 2,  5)
        f_trust       = executor.submit(_parse_top50, API_Trust,       1, 2,  5)
        f_proprietary = executor.submit(_parse_top50, API_Proprietary, 0, 1, 10)

        foreign_buy,     foreign_sell     = f_foreign.result()
        trust_buy,       trust_sell       = f_trust.result()
        proprietary_buy, proprietary_sell = f_proprietary.result()

    return {
        "foreign": {
            "buy":  foreign_buy  if foreign_buy  is not None else [],
            "sell": foreign_sell if foreign_sell is not None else [],
            "error": "🚫 暫未更新" if foreign_buy is None else None,
        },
        "trust": {
            "buy":  trust_buy  if trust_buy  is not None else [],
            "sell": trust_sell if trust_sell is not None else [],
            "error": "🚫 暫未更新" if trust_buy is None else None,
        },
        "proprietary": {
            "buy":  proprietary_buy  if proprietary_buy  is not None else [],
            "sell": proprietary_sell if proprietary_sell is not None else [],
            "error": "🚫 暫未更新" if proprietary_buy is None else None,
        },
    }

# ── 上櫃三大法人買賣超排行前50 ────────────────────────────────────────────────
def otc_top50():
    API_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"

    def _parse_otc_top50():
        try:
            res  = requests.get(API_URL, headers=headers, verify=False, timeout=10)
            data = res.json()

            foreign_list = []
            trust_list   = []
            dealer_list  = []

            for row in data:
                stock_id   = row["SecuritiesCompanyCode"].strip()
                stock_name = row["CompanyName"].strip()

                # 過濾權證、認購認售
                if re.search(r'購|售|認購|認售', stock_name):
                    continue

                try:
                    foreign = int(row["Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"]) // 1000
                    trust   = int(row["SecuritiesInvestmentTrustCompanies-Difference"]) // 1000
                    dealer  = int(row["Dealers-Difference"]) // 1000
                except (KeyError, ValueError):
                    continue

                foreign_list.append({"id": stock_id, "name": stock_name, "net": foreign})
                trust_list.append(  {"id": stock_id, "name": stock_name, "net": trust})
                dealer_list.append( {"id": stock_id, "name": stock_name, "net": dealer})

            def top50(lst):
                buy  = sorted(lst, key=lambda x: x["net"], reverse=True)[:50]
                sell = sorted(lst, key=lambda x: x["net"])[:50]
                return buy, sell

            return top50(foreign_list), top50(trust_list), top50(dealer_list)

        except Exception as e:
            print(f"[otc_top50] 查詢失敗: {e}")
            return (None, None), (None, None), (None, None)

    (foreign_buy, foreign_sell), (trust_buy, trust_sell), (dealer_buy, dealer_sell) = _parse_otc_top50()

    return {
        "foreign": {
            "buy":   foreign_buy  if foreign_buy  is not None else [],
            "sell":  foreign_sell if foreign_sell is not None else [],
            "error": "🚫 暫未更新" if foreign_buy is None else None,
        },
        "trust": {
            "buy":   trust_buy  if trust_buy  is not None else [],
            "sell":  trust_sell if trust_sell is not None else [],
            "error": "🚫 暫未更新" if trust_buy is None else None,
        },
        "proprietary": {
            "buy":   dealer_buy  if dealer_buy  is not None else [],
            "sell":  dealer_sell if dealer_sell is not None else [],
            "error": "🚫 暫未更新" if dealer_buy is None else None,
        },
    }