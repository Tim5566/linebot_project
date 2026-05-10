"""
post_Info.py（Firebase 快取版）
────────────────────────────────────────────────────────────────────────────
股票查詢邏輯：
  - stock_info()   → 優先從 Firebase 讀取，沒資料才 fallback 打 TWSE API
  - market_pnfo()  → 從 Firebase 讀取大盤資訊
  - twse_top50()   → 仍直接打 API（資料量大，全市場排行）
  - otc_top50()    → 仍直接打 API

個股查詢流程：
  1. 檢查今日是否交易日、時間是否 ≥ 15:00
  2. 查 Firebase stock_data/{today}/twse/{stock_id} 或 otc/{stock_id}
  3. 若 Firebase 無資料 → fallback 打 TWSE API（和舊版一樣）

修正重點：
  - _init_firebase 補上 firebase_admin.get_app() 判斷
    → 避免與 firebase_sync.py 重複初始化衝突
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import datetime
import requests
import re
import urllib3
import concurrent.futures
from zoneinfo import ZoneInfo

import os
import firebase_admin
from firebase_admin import credentials, db as firebase_db

from get_trading_holidays import is_trading_day
from tools import to_minguo

import time as _time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.twse.com.tw/",
    "X-Requested-With": "XMLHttpRequest",
}

# ── Firebase 初始化（單例）────────────────────────────────────────────────────
_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        # ✅ 修正：先檢查 App 是否已存在（避免與 firebase_sync.py 衝突）
        firebase_admin.get_app()
        _firebase_initialized = True
        print("[post_Info] 使用已存在的 Firebase app")
    except ValueError:
        # App 不存在，才初始化
        try:
            cred_path = os.environ.get("FIREBASE_CREDENTIAL_PATH", "firebase_credentials.json")
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {
                "databaseURL": os.environ.get("FIREBASE_DATABASE_URL", "")
            })
            _firebase_initialized = True
            print("✅ Firebase 初始化成功")
        except Exception as e:
            print(f"❌ Firebase 初始化失敗: {e}")

_init_firebase()

# ── 個股查詢結果快取（記憶體，跨日自動失效）──────────────────────────────────
_stock_cache: dict = {}

def _cache_key(keyword: str) -> str:
    return f"{get_today()}_{keyword}"

def _is_complete_result(reply: str) -> bool:
    return "暫未更新" not in reply

def get_today():
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")


# ══════════════════════════════════════════════════════════════════════════════
# Firebase 讀取
# ══════════════════════════════════════════════════════════════════════════════

def _read_firebase_stock(today: str, market: str, stock_id: str) -> dict | None:
    """
    從 Firebase 讀取單支個股資料。
    market: "twse" 或 "otc"
    回傳 dict 或 None（無資料）。
    """
    try:
        ref  = firebase_db.reference(f"stock_data/{today}/{market}/{stock_id}")
        data = ref.get()
        return data  # dict or None
    except Exception as e:
        print(f"[firebase_read] 失敗 {market}/{stock_id}: {e}")
        return None


def _read_firebase_market(today: str) -> dict | None:
    """從 Firebase 讀取大盤資訊。"""
    try:
        ref  = firebase_db.reference(f"stock_data/{today}/market")
        return ref.get()
    except Exception as e:
        print(f"[firebase_read_market] 失敗: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 代碼清單（用來判斷個股屬於上市或上櫃，以及名稱 ↔ 代碼互查）
# ══════════════════════════════════════════════════════════════════════════════

def fetch_with_retry(url, today, date_key="date", retries=4, delay=1.2):
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

            if not api_d:
                return data
            if today_d in api_d or api_d in today_d:
                return data
            if minguo_d and (minguo_d in api_d or api_d in minguo_d):
                return data

            print(f"[retry {attempt+1}/{retries}] 日期不符 api={api_d} today={today_d}")

        except Exception as e:
            print(f"[retry {attempt+1}/{retries}] 請求失敗: {e}")

        _time.sleep(0.5 if attempt == 0 else delay)

    return None


def _load_stock_list():
    """
    代碼清單載入：優先從 Firebase stock_list 讀取（毫秒級），
    Firebase 無資料才 fallback 打 API，並自動回寫 Firebase。
    """
    def _firebase_to_maps(market: str):
        """從 Firebase stock_list/{market} 讀取並回傳 (code2name, name2code)"""
        try:
            ref  = firebase_db.reference(f"stock_list/{market}")
            data = ref.get()   # {代碼: 名稱}
            if data and len(data) > 10:
                c2n = {str(k): str(v) for k, v in data.items()}
                n2c = {str(v): str(k) for k, v in data.items()}
                print(f"[stock_list] Firebase 讀取 {market} {len(c2n)} 筆 ✅")
                return c2n, n2c
        except Exception as e:
            print(f"[stock_list] Firebase 讀取 {market} 失敗: {e}")
        return None, None

    # ── 嘗試從 Firebase 讀取 ──────────────────────────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ft = pool.submit(_firebase_to_maps, "twse")
        fo = pool.submit(_firebase_to_maps, "otc")
        twse_c2n, twse_n2c = ft.result(timeout=15)
        otc_c2n,  otc_n2c  = fo.result(timeout=15)

    if twse_c2n and otc_c2n:
        return twse_c2n, twse_n2c, otc_c2n, otc_n2c

    # ── Firebase 無資料 → fallback 打 API，並回寫 Firebase ────────────────────
    print("[stock_list] Firebase 無資料，fallback 打 API 並回寫...")
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
            twse_c2n, twse_n2c = {}, {}
        try:
            otc_c2n, otc_n2c = fo.result(timeout=25)
        except concurrent.futures.TimeoutError:
            otc_c2n, otc_n2c = {}, {}

    # 回寫 Firebase（背景執行，不阻塞主流程）
    def _write_to_firebase():
        try:
            import firebase_sync as _fs
            if twse_c2n:
                _fs._write_batch("stock_list/twse", twse_c2n)
                print(f"[stock_list] 上市 {len(twse_c2n)} 筆已回寫 Firebase ✅")
            if otc_c2n:
                _fs._write_batch("stock_list/otc", otc_c2n)
                print(f"[stock_list] 上櫃 {len(otc_c2n)} 筆已回寫 Firebase ✅")
            import datetime as _dt
            firebase_db.reference("stock_list/meta").set({
                "updated_at": _dt.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
                "twse_count": len(twse_c2n),
                "otc_count":  len(otc_c2n),
            })
        except Exception as e:
            print(f"[stock_list] 回寫 Firebase 失敗: {e}")

    import threading
    threading.Thread(target=_write_to_firebase, daemon=True).start()

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

_stock_list_loaded_date: str = get_today()

def _ensure_stock_list_fresh():
    global TWSE_CODE2NAME, TWSE_NAME2CODE, OTC_CODE2NAME, OTC_NAME2CODE
    global TWSE_data_code, TWSE_data_name, OTC_data_code, OTC_data_name
    global _stock_list_loaded_date

    today = get_today()
    if today == _stock_list_loaded_date:
        return

    print(f"[auto-reload] 跨日偵測：{_stock_list_loaded_date} → {today}")

    old_keys = [k for k in _stock_cache if not k.startswith(today)]
    for k in old_keys:
        del _stock_cache[k]

    try:
        TWSE_CODE2NAME, TWSE_NAME2CODE, OTC_CODE2NAME, OTC_NAME2CODE = _load_stock_list()
        TWSE_data_code = list(TWSE_CODE2NAME.keys())
        TWSE_data_name = list(TWSE_CODE2NAME.values())
        OTC_data_code  = list(OTC_CODE2NAME.keys())
        OTC_data_name  = list(OTC_CODE2NAME.values())
        _stock_list_loaded_date = today
        print(f"✅ 代碼清單重載完成")
    except Exception as e:
        print(f"❌ 代碼清單重載失敗: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Fallback：Firebase 無資料時，直接打 TWSE API（和舊版一樣）
# ══════════════════════════════════════════════════════════════════════════════

def _twse_disposal(keyword, api_url):
    try:
        res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
        data = res.json()
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

def _otc_disposal(keyword, api_url):
    try:
        res  = requests.get(api_url, headers=headers, verify=False, timeout=10)
        data = res.json()
        for row in data["tables"][0]["data"]:
            stock_id, stock_name = row[2], row[3].split("(")[0]
            if keyword in stock_id or keyword in stock_name:
                return f"處置：⭕ 至 {row[5][10:]}"
        return "處置：❌"
    except Exception:
        return None

def _otc_institutional(keyword, api_url, today):
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
                return True
            api_d = re.sub(r"[^\d]", "", to_minguo(raw))
            if not api_d:
                return True
            return (today_d in api_d or api_d in today_d or
                    (minguo_today and (minguo_today in api_d or api_d in minguo_today)))

        inst_data = None
        for attempt in range(4):
            try:
                res = requests.get(api_url, headers=headers, verify=False, timeout=12)
                inst_data = res.json()
                if otc_date_ok(inst_data):
                    break
                print(f"[otc_inst retry {attempt+1}/4] 日期不符")
            except Exception as e:
                print(f"[otc_inst retry {attempt+1}/4] 失敗: {e}")
            _time.sleep(0.8 if attempt == 0 else 1.5)

        if not inst_data or not otc_date_ok(inst_data):
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
                except (KeyError, ValueError):
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


# ══════════════════════════════════════════════════════════════════════════════
# 主查詢：優先 Firebase，無資料才 fallback
# ══════════════════════════════════════════════════════════════════════════════

def _stock_id_from_keyword(keyword: str):
    """
    keyword 可能是代碼或名稱，回傳 (stock_id, market)。
    market: "twse" | "otc" | None

    查詢順序：
    1. 記憶體清單（TWSE_CODE2NAME / OTC_CODE2NAME）
    2. 若未找到 → 打 API 重新抓完整清單，自動補寫 Firebase（新掛牌公司）
    """
    # ── 先查記憶體 ──
    if keyword in TWSE_CODE2NAME:
        return keyword, "twse"
    if keyword in TWSE_NAME2CODE:
        return TWSE_NAME2CODE[keyword], "twse"
    if keyword in OTC_CODE2NAME:
        return keyword, "otc"
    if keyword in OTC_NAME2CODE:
        return OTC_NAME2CODE[keyword], "otc"

    # ── 找不到 → 嘗試 API 補查（可能是新掛牌公司）──────────────────────────
    print(f"[stock_id] 記憶體找不到「{keyword}」，嘗試 API 補查...")
    _refresh_stock_list_from_api(keyword)

    if keyword in TWSE_CODE2NAME:
        return keyword, "twse"
    if keyword in TWSE_NAME2CODE:
        return TWSE_NAME2CODE[keyword], "twse"
    if keyword in OTC_CODE2NAME:
        return keyword, "otc"
    if keyword in OTC_NAME2CODE:
        return OTC_NAME2CODE[keyword], "otc"

    return None, None


def _refresh_stock_list_from_api(trigger_keyword: str = ""):
    """
    重新從 API 抓最新代碼清單，並把新公司補寫進 Firebase。
    只在 _stock_id_from_keyword 找不到時才呼叫，不影響正常查詢效能。
    """
    global TWSE_CODE2NAME, TWSE_NAME2CODE, OTC_CODE2NAME, OTC_NAME2CODE
    global TWSE_data_code, TWSE_data_name, OTC_data_code, OTC_data_name

    from datetime import date, timedelta

    def _fetch_twse():
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
                    out = {}
                    for row in raw["data"]:
                        out[row[0].strip()] = row[1].strip()
                    return out
            except Exception as e:
                print(f"[refresh_list] 上市 {ds} 失敗: {e}")
        return {}

    def _fetch_otc():
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
                    out = {}
                    for row in tables[0]["data"]:
                        out[row[0].strip()] = row[1].strip()
                    return out
            except Exception as e:
                print(f"[refresh_list] 上櫃 {ds} 失敗: {e}")
        return {}

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            ft = pool.submit(_fetch_twse)
            fo = pool.submit(_fetch_otc)
            new_twse = ft.result(timeout=20)
            new_otc  = fo.result(timeout=20)
    except Exception as e:
        print(f"[refresh_list] API 補查失敗: {e}")
        return

    # 找出新增的公司（不在原清單的）
    new_twse_entries = {k: v for k, v in new_twse.items() if k not in TWSE_CODE2NAME}
    new_otc_entries  = {k: v for k, v in new_otc.items()  if k not in OTC_CODE2NAME}

    if new_twse_entries or new_otc_entries:
        print(f"[refresh_list] 發現新公司：上市 {len(new_twse_entries)} 筆、上櫃 {len(new_otc_entries)} 筆")
        # 背景補寫 Firebase
        def _write():
            try:
                import firebase_sync as _fs
                if new_twse_entries:
                    _fs._write_batch("stock_list/twse", new_twse_entries)
                    print(f"[refresh_list] 上市新公司已補寫 Firebase: {list(new_twse_entries.keys())}")
                if new_otc_entries:
                    _fs._write_batch("stock_list/otc", new_otc_entries)
                    print(f"[refresh_list] 上櫃新公司已補寫 Firebase: {list(new_otc_entries.keys())}")
            except Exception as e:
                print(f"[refresh_list] Firebase 補寫失敗: {e}")
        import threading
        threading.Thread(target=_write, daemon=True).start()
    else:
        print(f"[refresh_list] 無新公司（trigger={trigger_keyword}），代碼清單最新 ✅")

    # 更新記憶體清單（不管有無新公司都更新）
    if new_twse:
        TWSE_CODE2NAME.update(new_twse)
        TWSE_NAME2CODE.update({v: k for k, v in new_twse.items()})
        TWSE_data_code = list(TWSE_CODE2NAME.keys())
        TWSE_data_name = list(TWSE_CODE2NAME.values())
    if new_otc:
        OTC_CODE2NAME.update(new_otc)
        OTC_NAME2CODE.update({v: k for k, v in new_otc.items()})
        OTC_data_code = list(OTC_CODE2NAME.keys())
        OTC_data_name = list(OTC_CODE2NAME.values())


def _build_reply_from_firebase(keyword: str, stock_id: str, market: str, today: str) -> str | None:
    """
    從 Firebase 組出回覆字串。
    若 Firebase 完全沒有該股資料，回傳 None（交由 fallback 處理）。
    """
    data = _read_firebase_stock(today, market, stock_id)
    if not data:
        return None  # Firebase 尚未同步，走 fallback

    name     = data.get("name", keyword)
    foreign  = data.get("foreign")
    trust    = data.get("trust")
    prop     = data.get("proprietary")
    short    = data.get("short_sale")
    disposal = data.get("disposal")

    # 若三大法人都沒有，也走 fallback（可能 15:10 尚未同步）
    if foreign is None and trust is None and prop is None:
        return None

    # 格式化數字（加千分位）
    def _fmt(val, label, unit="股"):
        if val is None:
            return f"{label}：🚫 暫未更新"
        try:
            n = int(val)
            return f"{label}：{n:,} {unit}"
        except (ValueError, TypeError):
            return f"{label}：{val} {unit}"

    reply  = f"{name}({stock_id}) (今盤後買賣超)\n"
    reply += (disposal + "\n") if disposal else "處置：❌\n"
    reply += _fmt(foreign,  "外資") + "\n"
    reply += _fmt(trust,    "投信") + "\n"
    reply += _fmt(prop,     "自營商") + "\n"
    reply += _fmt(short,    "借卷賣出") + "\n"

    return reply.strip()


def _fallback_twse(keyword: str, today: str) -> str:
    """Firebase 無資料時，直接打上市 API（舊版邏輯）。"""
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

    reply  = f"{keyword} (今盤後買賣超)\n"
    reply += (D + "\n") if D else "處置：🚫 暫未更新\n"
    reply += (F + "\n") if F else "外資：🚫 暫未更新\n"
    reply += (T + "\n") if T else "投信：🚫 暫未更新\n"
    reply += (P + "\n") if P else "自營商：🚫 暫未更新\n"
    reply += (S + "\n") if S else "借卷賣出：🚫 暫未更新\n"
    return reply.strip()


def _fallback_otc(keyword: str, today: str) -> str:
    """Firebase 無資料時，直接打上櫃 API（舊版邏輯）。"""
    API_inst       = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
    API_Disposal   = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
    API_Short_Sale = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        fd = ex.submit(_otc_disposal,      keyword, API_Disposal)
        fi = ex.submit(_otc_institutional, keyword, API_inst,       today)
        fs = ex.submit(_otc_short_sale,    keyword, API_Short_Sale, today)
        D        = fd.result()
        F, T, P  = fi.result()
        S        = fs.result()

    reply  = f"{keyword} (今盤後買賣超)\n"
    reply += (D + "\n") if D else "處置：🚫 暫未更新\n"
    reply += (F + "\n") if F else "外資：🚫 暫未更新\n"
    reply += (T + "\n") if T else "投信：🚫 暫未更新\n"
    reply += (P + "\n") if P else "自營商：🚫 暫未更新\n"
    reply += (S + "\n") if S else "借卷賣出：🚫 暫未更新\n"
    return reply.strip()


def _fallback_search(keyword: str, today: str):
    """代碼清單為空（冷啟動失敗）時的備用查詢。"""
    print(f"[fallback] keyword={keyword}")
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
            r  = f"{keyword} (今盤後買賣超)\n"
            r += (F + "\n") if F else "外資：🚫 暫未更新\n"
            r += (T + "\n") if T else "投信：🚫 暫未更新\n"
            r += (P + "\n") if P else "自營商：🚫 暫未更新\n"
            return r.strip()
    except Exception as e:
        print(f"[fallback] 上市失敗: {e}")

    try:
        F2, T2, P2 = _otc_institutional(
            keyword,
            "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json",
            today)
        if F2 or T2 or P2:
            r  = f"{keyword} (今盤後買賣超)\n"
            r += (F2 + "\n") if F2 else "外資：🚫 暫未更新\n"
            r += (T2 + "\n") if T2 else "投信：🚫 暫未更新\n"
            r += (P2 + "\n") if P2 else "自營商：🚫 暫未更新\n"
            return r.strip()
    except Exception as e:
        print(f"[fallback] 上櫃失敗: {e}")

    return None


def stock_info(keyword: str) -> str:
    today = get_today()
    _ensure_stock_list_fresh()

    if not is_trading_day():
        return "📢 今日週末或連假未開盤❗"
    if datetime.datetime.now(ZoneInfo("Asia/Taipei")).hour < 15:
        return "📢 今盤後資料尚未更新❗\n請於今日 15:00 後再試一次。"

    # ── 記憶體快取（當日同一 keyword 不重複查）──
    ck = _cache_key(keyword)
    if ck in _stock_cache:
        return _stock_cache[ck]

    # ── 解析 stock_id & market ──
    stock_id, market = _stock_id_from_keyword(keyword)

    if stock_id and market:
        # 優先從 Firebase 讀
        reply = _build_reply_from_firebase(keyword, stock_id, market, today)
        if reply:
            if _is_complete_result(reply):
                _stock_cache[ck] = reply
            return reply

        # Firebase 無資料 → fallback 打 API
        print(f"[stock_info] Firebase miss，fallback to API: keyword={keyword}")
        if market == "twse":
            reply = _fallback_twse(keyword, today)
        else:
            reply = _fallback_otc(keyword, today)

        if _is_complete_result(reply):
            _stock_cache[ck] = reply
        return reply

    # ── 代碼清單查不到 → fallback 同時試上市 + 上櫃 ──
    result = _fallback_search(keyword, today)
    if result:
        return result
    return f"❌找不到「{keyword}」今盤後資料。"


# ══════════════════════════════════════════════════════════════════════════════
# 大盤總體資訊（從 Firebase 讀，無資料才打 API）
# ══════════════════════════════════════════════════════════════════════════════

def market_pnfo() -> str:
    today = get_today()

    # 嘗試從 Firebase 讀
    mkt = _read_firebase_market(today)
    if mkt:
        reply = "📉大盤盤後詳細資訊📈\n"
        labels = ["自營商", "投信", "外資及陸資", "外資"]
        for label in labels:
            if label in mkt:
                reply += f"{label} : {mkt[label]}億\n"
        if "合計金額" in mkt:
            reply += f"合計金額 : {mkt['合計金額']}億\n"
        reply += "---------------------------------------------\n"
        if "融資金額增減" in mkt:
            reply += f"融資金額增減 : {mkt['融資金額增減']}億\n"
        if "融資額金水位" in mkt:
            reply += f"融資額金水位 : {mkt['融資額金水位']}億\n"
        return reply.strip()

    # Fallback：直接打 API
    print("[market_pnfo] Firebase miss，fallback to API")
    reply = "📉大盤盤後詳細資訊📈\n"

    try:
        data = fetch_with_retry(
            f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}", today)
        if data is None:
            raise Exception("無資料")
        net_total = 0
        for i in range(3, -1, -1):
            row        = data["data"][i]
            net_amount = float(row[3].replace(',', '')) / 1e8
            net_total += net_amount
            net_amount = int(net_amount * 100) / 100
            label      = row[0][:5] if i == 3 else row[0]
            reply += f"{label} : {net_amount}億\n"
        reply += f"合計金額 : {int(net_total * 100) / 100}億\n"
        reply += "---------------------------------------------\n"
    except Exception:
        reply += "三大法人 : 🚫 暫未更新\n---------------------------------------------\n"

    try:
        data = fetch_with_retry(
            f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}", today)
        if data is None:
            raise Exception("無資料")
        row          = data["tables"][0]["data"]
        prev_margin  = int(row[2][4].replace(',', '')) / 1e5
        today_margin = int(row[2][5].replace(',', '')) / 1e5
        margin_delta = today_margin - prev_margin
        reply += f"融資金額增減 : {margin_delta:.2f}億\n"
        reply += f"融資額金水位 : {today_margin:.2f}億\n"
    except Exception:
        reply += "融資金額增減 : 🚫 暫未更新\n融資額金水位 : 🚫 暫未更新\n"

    return reply.strip()


# ══════════════════════════════════════════════════════════════════════════════
# 上市 / 上櫃 Top50（資料量大，仍直接打 API）
# ══════════════════════════════════════════════════════════════════════════════

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