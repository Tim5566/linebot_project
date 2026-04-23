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

# ── API レスポンスキャッシュ（同日同 URL は再取得しない）─────────────────────
# 上市の外資/投信/自營商/借券 API は全銘柄分のデータが1本で返るため、
# 2銘柄目以降は HTTP リクエスト不要になり大幅に高速化される
_api_cache: dict = {}   # { "YYYYMMDD_url": data }

def _api_cache_key(url: str) -> str:
    return f"{get_today()}_{url}"

def _api_cache_get(url: str):
    return _api_cache.get(_api_cache_key(url))

def _api_cache_set(url: str, data) -> None:
    _api_cache[_api_cache_key(url)] = data

# ── 盤後資料 session 快取 ─────────────────────────────────────────────────────
# ⚠️ 修復：只快取「完全成功」的結果，避免把失敗結果永久快取
_stock_cache: dict = {}

def _cache_key(keyword: str) -> str:
    return f"{get_today()}_{keyword}"

def _is_complete_result(reply: str) -> bool:
    """只有不含任何「暫未更新」的回覆才算完整，才存入快取。"""
    return "暫未更新" not in reply

def get_today():
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")


def fetch_with_retry(url, today, date_key="date", retries=4, delay=1.2):
    """
    GET 請求，日期不符自動重試。
    ✅ 新增：API 回應快取（同日同 URL 直接回傳，跳過 HTTP 請求）
    """
    # ── 快取命中 → 直接回傳，零網路延遲 ──
    cached = _api_cache_get(url)
    if cached is not None:
        return cached

    today_d = re.sub(r"[^\d]", "", today)
    try:
        y = int(today_d[:4]) - 1911
        minguo_d = f"{y:03d}{today_d[4:]}"
    except Exception:
        minguo_d = ""

    for attempt in range(retries):
        try:
            res  = requests.get(url, headers=headers, verify=False, timeout=10)
            data = res.json()

            raw_date = ""
            for field in (date_key, "date", "Date", "queryDate", "QUERY_DATE", "reportDate"):
                v = data.get(field, "")
                if v:
                    raw_date = str(v)
                    break

            api_d = re.sub(r"[^\d]", "", raw_date)

            # 無日期欄位 → 直接信任
            if not api_d:
                _api_cache_set(url, data)   # ← 快取
                return data

            # 西元年或民國年任一相符
            if today_d in api_d or api_d in today_d:
                _api_cache_set(url, data)   # ← 快取
                return data
            if minguo_d and (minguo_d in api_d or api_d in minguo_d):
                _api_cache_set(url, data)   # ← 快取
                return data

            print(f"[retry {attempt+1}/{retries}] 日期不符 api={api_d} "
                  f"today={today_d} url={url[:65]}")

        except Exception as e:
            print(f"[retry {attempt+1}/{retries}] 請求失敗: {e} url={url[:65]}")

        _time.sleep(0.5 if attempt == 0 else delay)

    return None


# ── 上市 / 上櫃代碼清單（並行載入，帶超時保護）───────────────────────────────
def _load_stock_list():
    from datetime import date, timedelta

    def _fetch_twse():
        c2n, n2c = {}, {}
        d = date.today()
        for _ in range(12):
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            ds = d.strftime("%Y%m%d")
            try:
                r = requests.get(
                    f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date={ds}",
                    headers=headers, verify=False, timeout=10)
                raw = r.json()
                if raw.get("stat") == "OK" and raw.get("data"):
                    for row in raw["data"]:
                        c2n[row[0].strip()] = row[1].strip()
                        n2c[row[1].strip()] = row[0].strip()
                    print(f"[stock_list] 上市 {len(c2n)} 筆 date={ds}")
                    return c2n, n2c
            except Exception as e:
                print(f"[stock_list] 上市 {ds} 失敗: {e}")
        return c2n, n2c

    def _fetch_otc():
        c2n, n2c = {}, {}
        d = date.today()
        for _ in range(12):
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            ds = d.strftime("%Y%m%d")
            try:
                r = requests.get(
                    f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date={ds}",
                    headers=headers, verify=False, timeout=10)
                raw = r.json()
                tables = raw.get("tables") or []
                if tables and tables[0].get("data"):
                    for row in tables[0]["data"]:
                        c2n[row[0].strip()] = row[1].strip()
                        n2c[row[1].strip()] = row[0].strip()
                    print(f"[stock_list] 上櫃 {len(c2n)} 筆 date={ds}")
                    return c2n, n2c
            except Exception as e:
                print(f"[stock_list] 上櫃 {ds} 失敗: {e}")
        return c2n, n2c

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ft = pool.submit(_fetch_twse)
        fo = pool.submit(_fetch_otc)
        try:
            twse_c2n, twse_n2c = ft.result(timeout=25)
        except concurrent.futures.TimeoutError:
            print("[stock_list] 上市超時")
            twse_c2n, twse_n2c = {}, {}
        try:
            otc_c2n, otc_n2c = fo.result(timeout=25)
        except concurrent.futures.TimeoutError:
            print("[stock_list] 上櫃超時")
            otc_c2n, otc_n2c = {}, {}

    return twse_c2n, twse_n2c, otc_c2n, otc_n2c


try:
    TWSE_CODE2NAME, TWSE_NAME2CODE, OTC_CODE2NAME, OTC_NAME2CODE = _load_stock_list()
    TWSE_data_code = list(TWSE_CODE2NAME.keys())
    TWSE_data_name = list(TWSE_CODE2NAME.values())
    OTC_data_code  = list(OTC_CODE2NAME.keys())
    OTC_data_name  = list(OTC_CODE2NAME.values())
    print(f"✅ 代碼清單：上市 {len(TWSE_data_code)} 筆，上櫃 {len(OTC_data_code)} 筆")
except Exception as e:
    TWSE_CODE2NAME = TWSE_NAME2CODE = OTC_CODE2NAME = OTC_NAME2CODE = {}
    TWSE_data_code = TWSE_data_name = OTC_data_code = OTC_data_name = []
    print(f"❌ 代碼清單失敗: {e}")


# ── 上市個股 ──────────────────────────────────────────────────────────────────
def _twse_disposal(keyword, api_url):
    try:
        data = _api_cache_get(api_url)
        if data is None:
            res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
            data = res.json()
            _api_cache_set(api_url, data)
        for row in data["data"]:
            stock_id, stock_name = row[2], row[3]
            if keyword in stock_id or keyword in stock_name:
                return f"處置：⭕ 至 {row[6][10:]}"
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


# ── 上櫃個股 ──────────────────────────────────────────────────────────────────
def _otc_disposal(keyword, api_url):
    try:
        data = _api_cache_get(api_url)
        if data is None:
            res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
            data = res.json()
            _api_cache_set(api_url, data)
        for row in data["tables"][0]["data"]:
            stock_id, stock_name = row[2], row[3].split("(")[0]
            if keyword in stock_id or keyword in stock_name:
                return f"處置：⭕ 至 {row[5][10:]}"
        return "處置：❌"
    except Exception:
        return None

def _otc_institutional(keyword, api_url, today):
    """
    修復：
    1. 日期比對同時支援西元年與民國年
    2. retries 4 次
    3. 若 API 無 Date 欄位則直接信任資料
    """
    try:
        today_d = re.sub(r"[^\d]", "", today)
        try:
            y = int(today_d[:4]) - 1911
            minguo_today = f"{y:03d}{today_d[4:]}"
        except Exception:
            minguo_today = ""

        def otc_date_ok(data):
            if not data:
                return False
            raw = data[0].get("Date", "")
            if not raw:
                return True   # 無日期欄位 → 信任
            api_d = re.sub(r"[^\d]", "", to_minguo(raw))
            if not api_d:
                return True
            return (today_d in api_d or api_d in today_d or
                    (minguo_today and (minguo_today in api_d or api_d in minguo_today)))

        inst_data = None
        for attempt in range(4):
            try:
                # ── 快取命中 → 直接使用 ──
                cached = _api_cache_get(api_url)
                if cached is not None:
                    inst_data = cached
                    break
                res = requests.get(api_url, headers=headers, verify=False, timeout=12)
                inst_data = res.json()
                if otc_date_ok(inst_data):
                    _api_cache_set(api_url, inst_data)   # ← 快取
                    break
                print(f"[otc_inst retry {attempt+1}/4] 日期不符，等待...")
            except Exception as e:
                print(f"[otc_inst retry {attempt+1}/4] 失敗: {e}")
            _time.sleep(0.8 if attempt == 0 else 1.5)

        if not inst_data or not otc_date_ok(inst_data):
            print(f"[otc_inst] 最終失敗 keyword={keyword}")
            return None, None, None

        for row in inst_data:
            sid  = row.get("SecuritiesCompanyCode", "")
            name = row.get("CompanyName", "")
            if re.search(r'購|售|認購|認售', name):
                continue
            if keyword in sid or keyword in name:
                try:
                    f = f"外資：{int(row['Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference']):,} 股"
                    t = f"投信：{int(row['SecuritiesInvestmentTrustCompanies-Difference']):,} 股"
                    p = f"自營商：{int(row['Dealers-Difference']):,} 股"
                    return f, t, p
                except (KeyError, ValueError) as e:
                    print(f"[otc_inst] 欄位解析失敗 keyword={keyword}: {e}")
                    return None, None, None
        return None, None, None

    except Exception as e:
        print(f"[otc_inst] 未預期錯誤 keyword={keyword}: {e}")
        return None, None, None


def _otc_short_sale(keyword, api_url, today):
    try:
        data = fetch_with_retry(api_url, today, date_key="date", retries=4, delay=1.5)
        if data is None:
            return None
        kw = keyword if keyword.isdigit() else OTC_NAME2CODE.get(keyword, keyword)
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

    ck = _cache_key(keyword)
    if ck in _stock_cache:
        return _stock_cache[ck]

    reply = f"{keyword} (今盤後買賣超)\n"

    # ── 上市 ──────────────────────────────────────────────────────────────────
    if keyword in TWSE_CODE2NAME or keyword in TWSE_NAME2CODE:
        API_Disposal    = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"
        API_Foreign     = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        API_Trust       = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        API_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        API_Short_Sale  = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?response=json&date={today}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            fd = ex.submit(_twse_disposal,    keyword, API_Disposal)
            ff = ex.submit(_twse_foreign,     keyword, API_Foreign,     today)
            ft = ex.submit(_twse_trust,       keyword, API_Trust,       today)
            fp = ex.submit(_twse_proprietary, keyword, API_Proprietary, today)
            fs = ex.submit(_twse_short_sale,  keyword, API_Short_Sale,  today)
            D, F, T, P, S = fd.result(), ff.result(), ft.result(), fp.result(), fs.result()

        reply += (D + "\n") if D else "處置：🚫 暫未更新\n"
        reply += (F + "\n") if F else "外資：🚫 暫未更新\n"
        reply += (T + "\n") if T else "投信：🚫 暫未更新\n"
        reply += (P + "\n") if P else "自營商：🚫 暫未更新\n"
        reply += (S + "\n") if S else "借卷賣出：🚫 暫未更新\n"

        # ⚠️ 只快取完整結果（不含「暫未更新」）
        if _is_complete_result(reply):
            _stock_cache[ck] = reply.strip()
        return reply.strip()

    # ── 上櫃 ──────────────────────────────────────────────────────────────────
    elif keyword in OTC_CODE2NAME or keyword in OTC_NAME2CODE:
        API_inst       = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
        API_Disposal   = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
        API_Short_Sale = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fd = ex.submit(_otc_disposal,     keyword, API_Disposal)
            fi = ex.submit(_otc_institutional, keyword, API_inst,       today)
            fs = ex.submit(_otc_short_sale,   keyword, API_Short_Sale,  today)
            D        = fd.result()
            F, T, P  = fi.result()
            S        = fs.result()

        reply += (D + "\n") if D else "處置：🚫 暫未更新\n"
        reply += (F + "\n") if F else "外資：🚫 暫未更新\n"
        reply += (T + "\n") if T else "投信：🚫 暫未更新\n"
        reply += (P + "\n") if P else "自營商：🚫 暫未更新\n"
        reply += (S + "\n") if S else "借卷賣出：🚫 暫未更新\n"

        # ⚠️ 只快取完整結果
        if _is_complete_result(reply):
            _stock_cache[ck] = reply.strip()
        return reply.strip()

    # ── 代碼清單為空時的備用查詢（冷啟動保護）───────────────────────────────
    else:
        result = _fallback_search(keyword, today)
        if result:
            return result
        return f"❌找不到「{keyword}」今盤後資料。"


def _fallback_search(keyword: str, today: str):
    """
    代碼清單為空（冷啟動失敗）時的備用查詢。
    直接打 API 比對，不依賴預載入的 dict。
    """
    print(f"[fallback] keyword={keyword}")

    # 先試上市
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            ff = ex.submit(_twse_foreign,     keyword,
                           f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}", today)
            ft = ex.submit(_twse_trust,       keyword,
                           f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}", today)
            fp = ex.submit(_twse_proprietary, keyword,
                           f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}", today)
            F, T, P = ff.result(), ft.result(), fp.result()
        if F or T or P:
            r = f"{keyword} (今盤後買賣超)\n"
            r += (F + "\n") if F else "外資：🚫 暫未更新\n"
            r += (T + "\n") if T else "投信：🚫 暫未更新\n"
            r += (P + "\n") if P else "自營商：🚫 暫未更新\n"
            return r.strip()
    except Exception as e:
        print(f"[fallback] 上市失敗: {e}")

    # 再試上櫃
    try:
        F2, T2, P2 = _otc_institutional(
            keyword,
            "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json",
            today)
        if F2 or T2 or P2:
            r = f"{keyword} (今盤後買賣超)\n"
            r += (F2 + "\n") if F2 else "外資：🚫 暫未更新\n"
            r += (T2 + "\n") if T2 else "投信：🚫 暫未更新\n"
            r += (P2 + "\n") if P2 else "自營商：🚫 暫未更新\n"
            return r.strip()
    except Exception as e:
        print(f"[fallback] 上櫃失敗: {e}")

    return None


# ── 大盤總體資訊 ──────────────────────────────────────────────────────────────
def market_pnfo():
    today = get_today()
    API_Net_Amount  = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    API_MarginDelta = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"
    reply = "📉大盤盤後詳細資訊📈\n"

    try:
        data = fetch_with_retry(API_Net_Amount, today)
        if data is None:
            raise Exception("無資料")
        net_total = 0
        for i in range(3, -1, -1):
            row = data["data"][i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100
            label = row[0][:5] if i == 3 else row[0]
            reply += f"{label} : {net_amount}億\n"
        reply += f"合計金額 : {int(net_total * 100) / 100}億\n"
        reply += "---------------------------------------------\n"
    except Exception:
        reply += "三大法人 : 🚫 暫未更新\n---------------------------------------------\n"

    try:
        data = fetch_with_retry(API_MarginDelta, today)
        if data is None:
            raise Exception("無資料")
        row = data["tables"][0]["data"]
        prev_margin  = int(row[2][4].replace(',', '')) / 1e5
        today_margin = int(row[2][5].replace(',', '')) / 1e5
        margin_delta = today_margin - prev_margin
        reply += f"融資金額增減 : {margin_delta:.2f}億\n"
        reply += f"融資額金水位 : {today_margin:.2f}億\n"
    except Exception:
        reply += "融資金額增減 : 🚫 暫未更新\n融資額金水位 : 🚫 暫未更新\n"

    return reply.strip()


# ── 上市三大法人買賣超排行前50 ───────────────────────────────────────────────
def twse_top50(today=None):
    if today is None:
        today = get_today()

    def _parse(api_url, id_col, name_col, net_col):
        try:
            res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
            data = res.json()
            if data.get("stat") != "OK":
                return None, None
            processed = []
            for row in data["data"]:
                name = row[name_col].strip()
                if re.search(r'購|售|認購|認售', name):
                    continue
                try:
                    net = int(row[net_col].replace(",", "")) // 1000
                except (ValueError, IndexError):
                    continue
                processed.append({"id": row[id_col].strip(), "name": name, "net": net})
            buy  = sorted(processed, key=lambda x: x["net"], reverse=True)[:50]
            sell = sorted(processed, key=lambda x: x["net"])[:50]
            return buy, sell
        except Exception as e:
            print(f"[twse_top50] 失敗: {e}")
            return None, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        ff = ex.submit(_parse, f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}", 1, 2,  5)
        ft = ex.submit(_parse, f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}", 1, 2,  5)
        fp = ex.submit(_parse, f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}", 0, 1, 10)
        fb, fs = ff.result()
        tb, ts = ft.result()
        pb, ps = fp.result()

    def _wrap(b, s):
        return {"buy": b or [], "sell": s or [], "error": "🚫 暫未更新" if b is None else None}

    return {"foreign": _wrap(fb, fs), "trust": _wrap(tb, ts), "proprietary": _wrap(pb, ps)}


# ── 上櫃三大法人買賣超排行前50 ──────────────────────────────────────────────
def otc_top50():
    API_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"

    try:
        res  = requests.get(API_URL, headers=headers, verify=False, timeout=10)
        data = res.json()
        fl, tl, dl = [], [], []
        for row in data:
            sid  = row["SecuritiesCompanyCode"].strip()
            name = row["CompanyName"].strip()
            if re.search(r'購|售|認購|認售', name):
                continue
            try:
                f = int(row["Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"]) // 1000
                t = int(row["SecuritiesInvestmentTrustCompanies-Difference"]) // 1000
                d = int(row["Dealers-Difference"]) // 1000
            except (KeyError, ValueError):
                continue
            fl.append({"id": sid, "name": name, "net": f})
            tl.append({"id": sid, "name": name, "net": t})
            dl.append({"id": sid, "name": name, "net": d})

        def top(lst):
            return (sorted(lst, key=lambda x: x["net"], reverse=True)[:50],
                    sorted(lst, key=lambda x: x["net"])[:50])

        fb, fs = top(fl)
        tb, ts = top(tl)
        db, ds = top(dl)

        def _wrap(b, s):
            return {"buy": b, "sell": s, "error": None}

        return {"foreign": _wrap(fb, fs), "trust": _wrap(tb, ts), "proprietary": _wrap(db, ds)}

    except Exception as e:
        print(f"[otc_top50] 失敗: {e}")
        empty = {"buy": [], "sell": [], "error": "🚫 暫未更新"}
        return {"foreign": empty, "trust": empty, "proprietary": empty}