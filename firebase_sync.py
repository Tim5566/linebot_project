"""
firebase_sync.py - 含日期驗證 + 重試等待機制
"""
from dotenv import load_dotenv
load_dotenv()

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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 重試設定 ──────────────────────────────────────────────────────────────────
MAX_DATE_RETRIES = 5    # 日期不符時最多重試幾次
DATE_RETRY_WAIT  = 180  # 每次等幾秒（3 分鐘）

# ── Firebase 初始化（單例）────────────────────────────────────────────────────
_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        # 如果已經有初始化過的 app，直接使用，不重複初始化
        firebase_admin.get_app()
        _firebase_initialized = True
        print("[firebase_sync] 使用已存在的 Firebase app")
    except ValueError:
        # 還沒初始化，才執行初始化
        cred_path = os.environ.get("FIREBASE_CREDENTIAL_PATH", "firebase_credentials.json")
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            "databaseURL": os.environ.get("FIREBASE_DATABASE_URL", "")
        })
        _firebase_initialized = True
        print("[firebase_sync] Firebase 初始化成功")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.twse.com.tw/",
    "X-Requested-With": "XMLHttpRequest",
}

def get_today():
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")

def _to_minguo(today_d: str) -> str:
    try:
        y = int(today_d[:4]) - 1911
        return f"{y:03d}{today_d[4:]}"
    except Exception:
        return ""

def _date_matches(api_date_raw: str, today: str) -> bool:
    if not api_date_raw:
        return True
    today_d  = re.sub(r"[^\d]", "", today)
    minguo_d = _to_minguo(today_d)
    api_d    = re.sub(r"[^\d]", "", str(api_date_raw))
    if not api_d:
        return True
    return (today_d in api_d or api_d in today_d or
            bool(minguo_d and (minguo_d in api_d or api_d in minguo_d)))

def _fetch(url, retries=3, delay=2.0):
    for i in range(retries):
        try:
            res = requests.get(url, headers=HEADERS, verify=False, timeout=15)
            return res.json()
        except Exception as e:
            print(f"[fetch retry {i+1}/{retries}] {e}")
            _time.sleep(delay)
    return None

def _fetch_with_date_check(url: str, today: str, label: str = ""):
    """GET + 日期驗證，日期不符則等待重試。"""
    for attempt in range(1, MAX_DATE_RETRIES + 1):
        data = _fetch(url)
        if data is None:
            print(f"[{label}] 第{attempt}次請求失敗")
            if attempt < MAX_DATE_RETRIES:
                print(f"[{label}] 等待 {DATE_RETRY_WAIT} 秒後重試...")
                _time.sleep(DATE_RETRY_WAIT)
            continue

        raw_date = ""
        if isinstance(data, dict):
            for field in ("date", "Date", "queryDate", "QUERY_DATE", "reportDate"):
                v = data.get(field, "")
                if v:
                    raw_date = str(v)
                    break

        if _date_matches(raw_date, today):
            if attempt > 1:
                print(f"[{label}] 第{attempt}次日期正確 ✅")
            return data

        print(f"[{label}] 第{attempt}次資料日期={raw_date}，今天={today}，尚未更新")
        if attempt < MAX_DATE_RETRIES:
            print(f"[{label}] 等待 {DATE_RETRY_WAIT} 秒後重試...")
            _time.sleep(DATE_RETRY_WAIT)

    print(f"[{label}] 超過最大重試次數，放棄寫入 ⚠️")
    return None

def _check_twse_stat(data, today: str, label: str):
    if data is None:
        return None
    if data.get("stat") != "OK":
        print(f"[{label}] stat={data.get('stat')}，資料尚未更新")
        return None
    raw_date = data.get("date", "")
    if raw_date and not _date_matches(raw_date, today):
        print(f"[{label}] 日期不符 api={raw_date} today={today}")
        return None
    return data

def _fetch_twse_institutional(today: str) -> dict:
    def _parse_foreign():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市外資"), today, "上市外資")
        if not data: return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name): continue
            out[row[1].strip()] = {"name": name, "foreign": row[5].strip()}
        return out

    def _parse_trust():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市投信"), today, "上市投信")
        if not data: return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name): continue
            out[row[1].strip()] = row[5].strip()
        return out

    def _parse_proprietary():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市自營商"), today, "上市自營商")
        if not data: return {}
        out = {}
        for row in data.get("data", []):
            name = row[1].strip()
            if re.search(r'購|售|認購|認售', name): continue
            out[row[0].strip()] = row[10].strip()
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        ff, ft, fp = ex.submit(_parse_foreign), ex.submit(_parse_trust), ex.submit(_parse_proprietary)
        foreign_map, trust_map, proprietary_map = ff.result(), ft.result(), fp.result()

    if not foreign_map and not trust_map and not proprietary_map:
        print("[twse_inst] 三大法人全部未取得，略過寫入"); return {}

    result = {}
    for sid in set(foreign_map) | set(trust_map) | set(proprietary_map):
        entry = foreign_map.get(sid, {})
        result[sid] = {
            "name": entry.get("name", sid),
            "foreign": entry.get("foreign", "0"),
            "trust": trust_map.get(sid, "0"),
            "proprietary": proprietary_map.get(sid, "0"),
        }
    print(f"[twse_inst] 共 {len(result)} 筆 ✅")
    return result

def _fetch_twse_short_sale(today: str) -> dict:
    url  = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?response=json&date={today}"
    data = _check_twse_stat(_fetch_with_date_check(url, today, "上市借券"), today, "上市借券")
    if not data: return {}
    out = {}
    for row in data.get("data", []):
        name = row[1].strip()
        if re.search(r'購|售|認購|認售', name): continue
        try:
            out[row[0].strip()] = str(int(row[9].replace(',','')) - int(row[10].replace(',','')))
        except: pass
    print(f"[twse_short] 共 {len(out)} 筆 ✅")
    return out

def _fetch_twse_disposal(today: str) -> dict:
    url  = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"
    data = _fetch(url)
    if not data: return {}
    out = {}
    try:
        for row in data.get("data", []):
            out[row[2].strip()] = f"處置：⭕ 至 {row[6][10:] if len(row)>6 else ''}"
    except Exception as e:
        print(f"[twse_disposal] 解析失敗: {e}")
    print(f"[twse_disposal] 共 {len(out)} 筆 ✅")
    return out

def _fetch_otc_institutional(today: str) -> dict:
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
    for attempt in range(1, MAX_DATE_RETRIES + 1):
        data = _fetch(url)
        if not data:
            print(f"[otc_inst] 第{attempt}次請求失敗")
            if attempt < MAX_DATE_RETRIES: _time.sleep(DATE_RETRY_WAIT)
            continue

        # 上櫃日期格式為民國年 YYYMMDD（民國年 + 1911 = 西元年）
        raw_date = data[0].get("Date", "") if data else ""
        if raw_date:
            raw_d = re.sub(r"[^\d]", "", raw_date)
            try:
                western = str(int(raw_d[:3]) + 1911) + raw_d[3:]
                today_d = re.sub(r"[^\d]", "", today)
                if western != today_d:
                    print(f"[otc_inst] 第{attempt}次資料日期={raw_date}（西元{western}），今天={today}，尚未更新")
                    if attempt < MAX_DATE_RETRIES:
                        print(f"[otc_inst] 等待 {DATE_RETRY_WAIT} 秒後重試...")
                        _time.sleep(DATE_RETRY_WAIT)
                    continue
            except Exception:
                print(f"[otc_inst] 日期解析失敗 raw={raw_date}，直接信任資料")

        out = {}
        for row in data:
            sid  = row.get("SecuritiesCompanyCode", "").strip()
            name = row.get("CompanyName", "").strip()
            if re.search(r'購|售|認購|認售', name): continue
            try:
                out[sid] = {
                    "name": name,
                    "foreign": str(int(row["Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference"])),
                    "trust": str(int(row["SecuritiesInvestmentTrustCompanies-Difference"])),
                    "proprietary": str(int(row["Dealers-Difference"])),
                }
            except: continue
        print(f"[otc_inst] 共 {len(out)} 筆 ✅")
        return out

    print("[otc_inst] 超過最大重試次數 ⚠️"); return {}

def _fetch_otc_short_sale(today: str) -> dict:
    url = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?response=json"
    for attempt in range(1, MAX_DATE_RETRIES + 1):
        data = _fetch(url)
        if not data:
            if attempt < MAX_DATE_RETRIES: _time.sleep(DATE_RETRY_WAIT)
            continue
        raw_date = data.get("date", "") if isinstance(data, dict) else ""
        if raw_date and not _date_matches(raw_date, today):
            print(f"[otc_short] 第{attempt}次資料日期={raw_date}，尚未更新")
            if attempt < MAX_DATE_RETRIES:
                print(f"[otc_short] 等待 {DATE_RETRY_WAIT} 秒後重試...")
                _time.sleep(DATE_RETRY_WAIT)
            continue
        out = {}
        try:
            for row in data["tables"][0]["data"]:
                try:
                    out[row[0].strip()] = str(int(row[9].replace(',','')) - int(row[10].replace(',','')))
                except: pass
        except Exception as e:
            print(f"[otc_short] 解析失敗: {e}")
        print(f"[otc_short] 共 {len(out)} 筆 ✅")
        return out
    print("[otc_short] 超過最大重試次數 ⚠️"); return {}

def _fetch_otc_disposal(today: str) -> dict:
    url  = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
    data = _fetch(url)
    if not data: return {}
    out = {}
    try:
        for row in data["tables"][0]["data"]:
            out[row[2].strip()] = f"處置：⭕ 至 {row[5][10:] if len(row)>5 else ''}"
    except Exception as e:
        print(f"[otc_disposal] 解析失敗: {e}")
    print(f"[otc_disposal] 共 {len(out)} 筆 ✅")
    return out

def _fetch_market(today: str) -> dict:
    result = {}
    url_net = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    data    = _check_twse_stat(_fetch_with_date_check(url_net, today, "大盤法人"), today, "大盤法人")
    if data:
        try:
            net_total = 0
            for i in range(3, -1, -1):
                row = data["data"][i]
                net_amount = float(row[3].replace(',', '')) / 1e8
                net_total += net_amount
                result[row[0][:5] if i == 3 else row[0]] = round(net_amount, 2)
            result["合計金額"] = round(net_total, 2)
        except Exception as e:
            print(f"[market_net] 解析失敗: {e}")

    url_margin = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"
    data       = _check_twse_stat(_fetch_with_date_check(url_margin, today, "大盤融資"), today, "大盤融資")
    if data:
        try:
            row = data["tables"][0]["data"]
            prev_margin  = int(row[2][4].replace(',', '')) / 1e5
            today_margin = int(row[2][5].replace(',', '')) / 1e5
            result["融資金額增減"] = round(today_margin - prev_margin, 2)
            result["融資額金水位"] = round(today_margin, 2)
        except Exception as e:
            print(f"[market_margin] 解析失敗: {e}")
    return result

def _write_batch(ref_path: str, data: dict, chunk_size: int = 500):
    _init_firebase()
    ref   = firebase_db.reference(ref_path)
    items = list(data.items())
    total = len(items)
    for i in range(0, total, chunk_size):
        ref.update(dict(items[i:i+chunk_size]))
        print(f"[firebase] 寫入 {ref_path} {min(i+chunk_size,total)}/{total}")

def sync_institutional(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步三大法人 date={today}")
    twse_inst = _fetch_twse_institutional(today)
    otc_inst  = _fetch_otc_institutional(today)
    _init_firebase()
    if twse_inst: _write_batch(f"stock_data/{today}/twse", twse_inst)
    else: print("[sync] 上市三大法人無資料，略過 ⚠️")
    if otc_inst: _write_batch(f"stock_data/{today}/otc", otc_inst)
    else: print("[sync] 上櫃三大法人無資料，略過 ⚠️")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "twse_count": len(twse_inst), "otc_count": len(otc_inst),
    })
    print(f"[sync] 三大法人完成 上市{len(twse_inst)}筆 上櫃{len(otc_inst)}筆")

def sync_short_sale(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步借券賣出 date={today}")
    twse_short = _fetch_twse_short_sale(today)
    otc_short  = _fetch_otc_short_sale(today)
    _init_firebase()
    if twse_short:
        ref = firebase_db.reference(f"stock_data/{today}/twse")
        for sid, val in twse_short.items(): ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上市借券 {len(twse_short)} 筆 ✅")
    else: print("[sync] 上市借券無資料，略過 ⚠️")
    if otc_short:
        ref = firebase_db.reference(f"stock_data/{today}/otc")
        for sid, val in otc_short.items(): ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上櫃借券 {len(otc_short)} 筆 ✅")
    else: print("[sync] 上櫃借券無資料，略過 ⚠️")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "short_sale_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
    })

def sync_disposal(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步處置股 date={today}")
    twse_disp = _fetch_twse_disposal(today)
    otc_disp  = _fetch_otc_disposal(today)
    _init_firebase()
    if twse_disp:
        ref = firebase_db.reference(f"stock_data/{today}/twse")
        for sid, val in twse_disp.items(): ref.child(sid).update({"disposal": val})
        print(f"[sync] 上市處置 {len(twse_disp)} 筆 ✅")
    if otc_disp:
        ref = firebase_db.reference(f"stock_data/{today}/otc")
        for sid, val in otc_disp.items(): ref.child(sid).update({"disposal": val})
        print(f"[sync] 上櫃處置 {len(otc_disp)} 筆 ✅")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "disposal_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
    })

def sync_market(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步大盤 date={today}")
    market = _fetch_market(today)
    if market:
        _init_firebase()
        firebase_db.reference(f"stock_data/{today}/market").set(market)
        firebase_db.reference(f"stock_data/{today}/meta").update({
            "market_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        })
        print(f"[sync] 大盤同步完成 ✅")
    else: print("[sync] 大盤無資料，略過 ⚠️")

def sync_all(today: str = None):
    if today is None: today = get_today()
    print(f"[sync_all] 開始全量同步 date={today}")
    sync_institutional(today)
    sync_disposal(today)
    sync_market(today)
    sync_short_sale(today)
    print(f"[sync_all] 全部完成 date={today}")