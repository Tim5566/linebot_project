"""
firebase_sync.py
────────────────────────────────────────────────────────────────────────────
盤後全量同步：一次把 TWSE / TPEX 所有個股資料抓下來，寫進 Firebase。
使用者查詢時直接從 Firebase 讀，不再打 TWSE API。

觸發時機（由 push_service.py 排程呼叫）：
  - 15:10  同步三大法人（外資、投信、自營商）
  - 17:30  同步處置股、注意股
  - 21:10  同步大盤融資
  - 21:30  同步借券賣出
────────────────────────────────────────────────────────────────────────────
"""

import os
import re
import datetime
import requests
import urllib3
import concurrent.futures
import time as _time

import firebase_admin
from firebase_admin import credentials, db as firebase_db
from zoneinfo import ZoneInfo

from get_trading_holidays import is_trading_day

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Firebase 初始化（單例）────────────────────────────────────────────────────
_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    # 優先使用環境變數 JSON（Render Secret File 或直接設定）
    cred_path = os.environ.get("FIREBASE_CREDENTIAL_PATH", "firebase_credentials.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        "databaseURL": os.environ.get("FIREBASE_DATABASE_URL", "")
    })
    _firebase_initialized = True

# ── HTTP 請求設定 ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.twse.com.tw/",
    "X-Requested-With": "XMLHttpRequest",
}

def get_today():
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")

def _fetch(url, retries=3, delay=2.0):
    """簡單 GET，失敗自動重試。"""
    for i in range(retries):
        try:
            res = requests.get(url, headers=HEADERS, verify=False, timeout=15)
            return res.json()
        except Exception as e:
            print(f"[fetch retry {i+1}/{retries}] {e} url={url[:70]}")
            _time.sleep(delay)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 抓取函式
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_twse_institutional(today: str) -> dict:
    """
    同時抓取上市外資、投信、自營商三大法人，
    回傳 {stock_id: {name, foreign, trust, proprietary}}
    """
    result: dict = {}

    def _parse_foreign():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        data = _fetch(url)
        if not data or data.get("stat") != "OK":
            return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name):
                continue
            out[row[1].strip()] = {"name": name, "foreign": row[5].strip()}
        return out

    def _parse_trust():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        data = _fetch(url)
        if not data or data.get("stat") != "OK":
            return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name):
                continue
            out[row[1].strip()] = row[5].strip()
        return out

    def _parse_proprietary():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        data = _fetch(url)
        if not data or data.get("stat") != "OK":
            return {}
        out = {}
        for row in data.get("data", []):
            name = row[1].strip()
            if re.search(r'購|售|認購|認售', name):
                continue
            out[row[0].strip()] = row[10].strip()
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        ff = ex.submit(_parse_foreign)
        ft = ex.submit(_parse_trust)
        fp = ex.submit(_parse_proprietary)
        foreign_map     = ff.result()
        trust_map       = ft.result()
        proprietary_map = fp.result()

    # 合併：以 stock_id 為 key
    all_ids = set(foreign_map) | set(trust_map) | set(proprietary_map)
    for sid in all_ids:
        entry = foreign_map.get(sid, {})
        result[sid] = {
            "name":        entry.get("name", sid),
            "foreign":     entry.get("foreign", "0"),
            "trust":       trust_map.get(sid, "0"),
            "proprietary": proprietary_map.get(sid, "0"),
        }

    print(f"[twse_inst] 共 {len(result)} 筆")
    return result


def _fetch_twse_short_sale(today: str) -> dict:
    """上市借券賣出，回傳 {stock_id: short_sale_str}"""
    url  = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?response=json&date={today}"
    data = _fetch(url)
    if not data or data.get("stat") != "OK":
        return {}
    out = {}
    for row in data.get("data", []):
        name = row[1].strip()
        if re.search(r'購|售|認購|認售', name):
            continue
        try:
            val = int(row[9].replace(',', '')) - int(row[10].replace(',', ''))
            out[row[0].strip()] = str(val)
        except (ValueError, IndexError):
            pass
    print(f"[twse_short] 共 {len(out)} 筆")
    return out


def _fetch_twse_disposal(today: str) -> dict:
    """上市處置股，回傳 {stock_id: disposal_str}"""
    url  = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"
    data = _fetch(url)
    if not data:
        return {}
    out = {}
    try:
        for row in data.get("data", []):
            sid  = row[2].strip()
            end  = row[6][10:] if len(row) > 6 else ""
            out[sid] = f"處置：⭕ 至 {end}"
    except Exception as e:
        print(f"[twse_disposal] 解析失敗: {e}")
    print(f"[twse_disposal] 共 {len(out)} 筆")
    return out


def _fetch_otc_institutional(today: str) -> dict:
    """
    上櫃三大法人，回傳 {stock_id: {name, foreign, trust, proprietary}}
    """
    url  = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
    data = _fetch(url, retries=4, delay=2.0)
    if not data:
        return {}
    out = {}
    for row in data:
        sid  = row.get("SecuritiesCompanyCode", "").strip()
        name = row.get("CompanyName", "").strip()
        if re.search(r'購|售|認購|認售', name):
            continue
        try:
            f = str(int(row["Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"]))
            t = str(int(row["SecuritiesInvestmentTrustCompanies-Difference"]))
            p = str(int(row["Dealers-Difference"]))
        except (KeyError, ValueError):
            continue
        out[sid] = {"name": name, "foreign": f, "trust": t, "proprietary": p}
    print(f"[otc_inst] 共 {len(out)} 筆")
    return out


def _fetch_otc_short_sale(today: str) -> dict:
    """上櫃借券賣出，回傳 {stock_id: short_sale_str}"""
    url  = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"
    data = _fetch(url, retries=4, delay=2.0)
    if not data:
        return {}
    out = {}
    try:
        for row in data["tables"][0]["data"]:
            sid = row[0].strip()
            try:
                val = int(row[9].replace(',', '')) - int(row[10].replace(',', ''))
                out[sid] = str(val)
            except (ValueError, IndexError):
                pass
    except Exception as e:
        print(f"[otc_short] 解析失敗: {e}")
    print(f"[otc_short] 共 {len(out)} 筆")
    return out


def _fetch_otc_disposal(today: str) -> dict:
    """上櫃處置股，回傳 {stock_id: disposal_str}"""
    url  = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
    data = _fetch(url)
    if not data:
        return {}
    out = {}
    try:
        for row in data["tables"][0]["data"]:
            sid  = row[2].strip()
            end  = row[5][10:] if len(row) > 5 else ""
            out[sid] = f"處置：⭕ 至 {end}"
    except Exception as e:
        print(f"[otc_disposal] 解析失敗: {e}")
    print(f"[otc_disposal] 共 {len(out)} 筆")
    return out


def _fetch_market(today: str) -> dict:
    """大盤三大法人 + 融資，回傳 dict。"""
    result = {}

    # 三大法人淨買超金額
    url_net = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    data    = _fetch(url_net)
    if data:
        try:
            net_total = 0
            for i in range(3, -1, -1):
                row        = data["data"][i]
                net_amount = float(row[3].replace(',', '')) / 1e8
                net_total += net_amount
                label = row[0][:5] if i == 3 else row[0]
                result[label] = round(net_amount, 2)
            result["合計金額"] = round(net_total, 2)
        except Exception as e:
            print(f"[market_net] 解析失敗: {e}")

    # 融資
    url_margin = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"
    data       = _fetch(url_margin)
    if data:
        try:
            row          = data["tables"][0]["data"]
            prev_margin  = int(row[2][4].replace(',', '')) / 1e5
            today_margin = int(row[2][5].replace(',', '')) / 1e5
            result["融資金額增減"] = round(today_margin - prev_margin, 2)
            result["融資額金水位"] = round(today_margin, 2)
        except Exception as e:
            print(f"[market_margin] 解析失敗: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 寫入 Firebase
# ══════════════════════════════════════════════════════════════════════════════

def _write_batch(ref_path: str, data: dict, chunk_size: int = 500):
    """
    分批寫入 Firebase（避免單次 payload 過大）。
    ref_path 例如 "stock_data/20250425/twse"
    """
    _init_firebase()
    ref   = firebase_db.reference(ref_path)
    items = list(data.items())
    total = len(items)
    for i in range(0, total, chunk_size):
        chunk = dict(items[i:i + chunk_size])
        ref.update(chunk)
        print(f"[firebase] 寫入 {ref_path} {i+chunk_size}/{total}")


# ══════════════════════════════════════════════════════════════════════════════
# 公開介面：各時段同步任務
# ══════════════════════════════════════════════════════════════════════════════

def sync_institutional(today: str = None):
    """
    15:10 呼叫：同步上市 + 上櫃三大法人（外資、投信、自營商）。
    """
    if today is None:
        today = get_today()
    print(f"[sync] 開始同步三大法人 date={today}")

    twse_inst = _fetch_twse_institutional(today)
    otc_inst  = _fetch_otc_institutional(today)

    if twse_inst:
        _write_batch(f"stock_data/{today}/twse", twse_inst)
    if otc_inst:
        _write_batch(f"stock_data/{today}/otc", otc_inst)

    # 更新 meta
    _init_firebase()
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
    })
    print(f"[sync] 三大法人同步完成")


def sync_short_sale(today: str = None):
    """
    21:30 呼叫：同步上市 + 上櫃借券賣出。
    """
    if today is None:
        today = get_today()
    print(f"[sync] 開始同步借券賣出 date={today}")

    twse_short = _fetch_twse_short_sale(today)
    otc_short  = _fetch_otc_short_sale(today)

    # 把借券資料 merge 進已有的個股節點
    _init_firebase()
    if twse_short:
        twse_ref = firebase_db.reference(f"stock_data/{today}/twse")
        for sid, val in twse_short.items():
            twse_ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上市借券 {len(twse_short)} 筆寫入完成")

    if otc_short:
        otc_ref = firebase_db.reference(f"stock_data/{today}/otc")
        for sid, val in otc_short.items():
            otc_ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上櫃借券 {len(otc_short)} 筆寫入完成")

    firebase_db.reference(f"stock_data/{today}/meta").update({
        "short_sale_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
    })


def sync_disposal(today: str = None):
    """
    17:30 呼叫：同步上市 + 上櫃處置股。
    """
    if today is None:
        today = get_today()
    print(f"[sync] 開始同步處置股 date={today}")

    twse_disp = _fetch_twse_disposal(today)
    otc_disp  = _fetch_otc_disposal(today)

    _init_firebase()
    twse_ref = firebase_db.reference(f"stock_data/{today}/twse")
    otc_ref  = firebase_db.reference(f"stock_data/{today}/otc")

    if twse_disp:
        for sid, val in twse_disp.items():
            twse_ref.child(sid).update({"disposal": val})
        print(f"[sync] 上市處置 {len(twse_disp)} 筆")

    if otc_disp:
        for sid, val in otc_disp.items():
            otc_ref.child(sid).update({"disposal": val})
        print(f"[sync] 上櫃處置 {len(otc_disp)} 筆")

    firebase_db.reference(f"stock_data/{today}/meta").update({
        "disposal_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
    })


def sync_market(today: str = None):
    """
    15:10 / 21:10 呼叫：同步大盤三大法人 + 融資。
    """
    if today is None:
        today = get_today()
    print(f"[sync] 開始同步大盤資訊 date={today}")

    market = _fetch_market(today)
    if market:
        _init_firebase()
        firebase_db.reference(f"stock_data/{today}/market").set(market)
        firebase_db.reference(f"stock_data/{today}/meta").update({
            "market_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        })
        print(f"[sync] 大盤同步完成 {market}")


def sync_all(today: str = None):
    """
    一次同步所有資料（手動觸發 / 補跑用）。
    """
    if today is None:
        today = get_today()
    sync_institutional(today)
    sync_disposal(today)
    sync_market(today)
    sync_short_sale(today)
    print(f"[sync_all] 全部同步完成 date={today}")
