"""
firebase_sync.py - 含日期驗證 + 重試等待機制
修正重點：
  1. sync_short_sale 加上空字串 sid 過濾
     → 避免 ValueError: Invalid path argument: "" 導致 sync_all 崩潰
  2. _fetch_twse_institutional 循序執行（移除 ThreadPoolExecutor）
  3. MAX_DATE_RETRIES=2、DATE_RETRY_WAIT=30 秒
  4. sync_otc_institutional() 獨立函式，15:30 觸發
"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import datetime
import requests
import urllib3
import time as _time

import firebase_admin
from firebase_admin import credentials, db as firebase_db
from zoneinfo import ZoneInfo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 重試設定 ──────────────────────────────────────────────────────────────────
MAX_DATE_RETRIES = 2
DATE_RETRY_WAIT  = 30

# ── Firebase 初始化（單例）────────────────────────────────────────────────────
_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        firebase_admin.get_app()
        _firebase_initialized = True
        print("[firebase_sync] 使用已存在的 Firebase app")
    except ValueError:
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

    foreign_map     = _parse_foreign()
    trust_map       = _parse_trust()
    proprietary_map = _parse_proprietary()

    if not foreign_map and not trust_map and not proprietary_map:
        print("[twse_inst] 三大法人全部未取得，略過寫入"); return {}

    result = {}
    for sid in set(foreign_map) | set(trust_map) | set(proprietary_map):
        entry  = foreign_map.get(sid, {})
        record = {"name": entry.get("name", sid)}
        if entry.get("foreign") is not None:
            record["foreign"] = entry["foreign"]
        if sid in trust_map:
            record["trust"] = trust_map[sid]
        if sid in proprietary_map:
            record["proprietary"] = proprietary_map[sid]
        result[sid] = record

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
        sid = row[0].strip()
        if not sid: continue  # ✅ 修正：過濾空字串 sid
        try:
            out[sid] = str(int(row[9].replace(',','')) - int(row[10].replace(',','')))
        except: pass
    print(f"[twse_short] 共 {len(out)} 筆 ✅")
    return out

def _fetch_otc_institutional(today: str) -> dict:
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?response=json"
    for attempt in range(1, MAX_DATE_RETRIES + 1):
        data = _fetch(url)
        if not data:
            print(f"[otc_inst] 第{attempt}次請求失敗")
            if attempt < MAX_DATE_RETRIES: _time.sleep(DATE_RETRY_WAIT)
            continue

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
            if not sid: continue  # 過濾空字串
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
                sid = row[0].strip()
                if not sid: continue  # 過濾空字串
                try:
                    out[sid] = str(int(row[9].replace(',','')) - int(row[10].replace(',','')))
                except: pass
        except Exception as e:
            print(f"[otc_short] 解析失敗: {e}")
        print(f"[otc_short] 共 {len(out)} 筆 ✅")
        return out
    print("[otc_short] 超過最大重試次數 ⚠️"); return {}

def _fetch_market(today: str) -> dict:
    result = {}

    # ── 法人買賣淨額 ──────────────────────────────────────────────────────────
    print(f"[market_debug] 開始抓法人資料 date={today}")
    url_net = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json&date={today}"
    raw_net = _fetch_with_date_check(url_net, today, "大盤法人")
    print(f"[market_debug] 法人 raw_net is None: {raw_net is None}")
    if raw_net is not None:
        print(f"[market_debug] 法人 stat={raw_net.get('stat')} date={raw_net.get('date')}")
    data = _check_twse_stat(raw_net, today, "大盤法人")
    print(f"[market_debug] 法人 _check_twse_stat 結果 is None: {data is None}")
    if data:
        try:
            net_total = 0
            for i in range(3, -1, -1):
                row = data["data"][i]
                net_amount = float(row[3].replace(',', '')) / 1e8
                net_total += net_amount
                label = row[0][:5] if i == 3 else row[0]
                if "自營商" in label:
                    result["自營商"] = round((result.get("自營商") or 0) + net_amount, 2)
                else:
                    result[label] = round(net_amount, 2)
            result["合計金額"] = round(net_total, 2)
            print(f"[market_debug] 法人寫入完成 keys={list(result.keys())} ✅")
        except Exception as e:
            print(f"[market_debug] 法人解析失敗: {e}")

    # ── 融資金額 ──────────────────────────────────────────────────────────────
    print(f"[market_debug] 開始抓融資資料 date={today}")
    url_margin = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={today}"
    raw_margin = _fetch_with_date_check(url_margin, today, "大盤融資")
    print(f"[market_debug] 融資 raw_margin is None: {raw_margin is None}")
    if raw_margin is not None:
        print(f"[market_debug] 融資 stat={raw_margin.get('stat')} date={raw_margin.get('date')} keys={list(raw_margin.keys())}")
    data = _check_twse_stat(raw_margin, today, "大盤融資")
    print(f"[market_debug] 融資 _check_twse_stat 結果 is None: {data is None}")
    if data:
        try:
            row = data["tables"][0]["data"]
            print(f"[market_debug] 融資 row[2]={row[2]}")
            prev_margin  = int(row[2][4].replace(',', '')) / 1e5
            today_margin = int(row[2][5].replace(',', '')) / 1e5
            result["融資金額增減"] = round(today_margin - prev_margin, 2)
            result["融資額金水位"] = round(today_margin, 2)
            print(f"[market_debug] 融資寫入完成 水位={today_margin:.2f}億 增減={today_margin - prev_margin:.2f}億 ✅")
        except Exception as e:
            print(f"[market_debug] 融資解析失敗: {e}")

    print(f"[market_debug] _fetch_market 完成 result keys={list(result.keys())}")
    return result

def _write_batch(ref_path: str, data: dict, chunk_size: int = 500):
    _init_firebase()
    ref   = firebase_db.reference(ref_path)
    items = list(data.items())
    total = len(items)
    for i in range(0, total, chunk_size):
        ref.update(dict(items[i:i+chunk_size]))
        print(f"[firebase] 寫入 {ref_path} {min(i+chunk_size,total)}/{total}")

# ── 公開同步函式 ───────────────────────────────────────────────────────────────

def sync_institutional(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步 TWSE 三大法人 date={today}")
    twse_inst = _fetch_twse_institutional(today)
    _init_firebase()
    if twse_inst:
        _write_batch(f"stock_data/{today}/twse", twse_inst)
    else:
        print("[sync] 上市三大法人無資料，略過 ⚠️")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "twse_institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "twse_count": len(twse_inst),
    })
    print(f"[sync] TWSE 三大法人完成 {len(twse_inst)}筆")

def sync_otc_institutional(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步 OTC 三大法人 date={today}")
    otc_inst = _fetch_otc_institutional(today)
    _init_firebase()
    if otc_inst:
        _write_batch(f"stock_data/{today}/otc", otc_inst)
    else:
        print("[sync] 上櫃三大法人無資料，略過 ⚠️")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "otc_institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "otc_count": len(otc_inst),
    })
    print(f"[sync] OTC 三大法人完成 {len(otc_inst)}筆")

def sync_short_sale(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步借券賣出 date={today}")
    twse_short = _fetch_twse_short_sale(today)
    otc_short  = _fetch_otc_short_sale(today)
    _init_firebase()
    if twse_short:
        ref = firebase_db.reference(f"stock_data/{today}/twse")
        for sid, val in twse_short.items():
            if not sid: continue  # ✅ 修正：過濾空字串 sid，避免 Firebase crash
            ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上市借券 {len(twse_short)} 筆 ✅")
    else:
        print("[sync] 上市借券無資料，略過 ⚠️")
    if otc_short:
        ref = firebase_db.reference(f"stock_data/{today}/otc")
        for sid, val in otc_short.items():
            if not sid: continue  # ✅ 修正：過濾空字串 sid，避免 Firebase crash
            ref.child(sid).update({"short_sale": val})
        print(f"[sync] 上櫃借券 {len(otc_short)} 筆 ✅")
    else:
        print("[sync] 上櫃借券無資料，略過 ⚠️")
    firebase_db.reference(f"stock_data/{today}/meta").update({
        "short_sale_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
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
    else:
        print("[sync] 大盤無資料，略過 ⚠️")

def sync_stock_list():
    """
    把 TWSE + TPEX 所有上市/上櫃公司的 代碼→名稱 寫入 Firebase。
    路徑：stock_list/twse/{代碼} = 名稱
          stock_list/otc/{代碼}  = 名稱
    平常只需執行一次（或定期每週執行一次）。
    新公司找不到時，post_Info 會自動呼叫此函式補寫。
    """
    from datetime import date, timedelta

    def _fetch_twse_list() -> dict:
        """抓上市代碼清單，回傳 {代碼: 名稱}"""
        d = date.today()
        for _ in range(12):
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            ds = d.strftime("%Y%m%d")
            try:
                r   = requests.get(
                    f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date={ds}",
                    headers=HEADERS, verify=False, timeout=10)
                raw = r.json()
                if raw.get("stat") == "OK" and raw.get("data"):
                    out = {}
                    for row in raw["data"]:
                        code = row[0].strip()
                        name = row[1].strip()
                        if code:
                            out[code] = name
                    print(f"[stock_list] 上市抓到 {len(out)} 筆 (date={ds}) ✅")
                    return out
            except Exception as e:
                print(f"[stock_list] 上市 {ds} 失敗: {e}")
        return {}

    def _fetch_otc_list() -> dict:
        """抓上櫃代碼清單，回傳 {代碼: 名稱}"""
        d = date.today()
        for _ in range(12):
            d -= timedelta(days=1)
            if d.weekday() >= 5:
                continue
            ds = d.strftime("%Y%m%d")
            try:
                r   = requests.get(
                    f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date={ds}",
                    headers=HEADERS, verify=False, timeout=10)
                raw = r.json()
                tables = raw.get("tables") or []
                if tables and tables[0].get("data"):
                    out = {}
                    for row in tables[0]["data"]:
                        code = row[0].strip()
                        name = row[1].strip()
                        if code:
                            out[code] = name
                    print(f"[stock_list] 上櫃抓到 {len(out)} 筆 (date={ds}) ✅")
                    return out
            except Exception as e:
                print(f"[stock_list] 上櫃 {ds} 失敗: {e}")
        return {}

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ft = pool.submit(_fetch_twse_list)
        fo = pool.submit(_fetch_otc_list)
        try:
            twse_map = ft.result(timeout=30)
        except Exception:
            twse_map = {}
        try:
            otc_map = fo.result(timeout=30)
        except Exception:
            otc_map = {}

    _init_firebase()
    if twse_map:
        _write_batch("stock_list/twse", twse_map)
        print(f"[stock_list] 上市 {len(twse_map)} 筆已寫入 Firebase ✅")
    else:
        print("[stock_list] 上市清單為空，略過 ⚠️")

    if otc_map:
        _write_batch("stock_list/otc", otc_map)
        print(f"[stock_list] 上櫃 {len(otc_map)} 筆已寫入 Firebase ✅")
    else:
        print("[stock_list] 上櫃清單為空，略過 ⚠️")

    # 記錄更新時間
    firebase_db.reference("stock_list/meta").set({
        "updated_at":  datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "twse_count":  len(twse_map),
        "otc_count":   len(otc_map),
    })
    print(f"[stock_list] 全部完成：上市 {len(twse_map)} + 上櫃 {len(otc_map)} 筆")
    return twse_map, otc_map



# ── 防重疊執行鎖（同一時間只允許一個 sync_all 在跑）────────────────────────
import threading as _threading
_sync_lock = _threading.Lock()


def sync_all(today: str = None, label: int = None):
    """
    依 label 精確執行對應同步任務，避免每次全跑造成重疊與多餘 API 呼叫。

    label 對照排程：
      None / 手動 → 全量同步（向下相容手動觸發）
      2  = 15:00  投信 TWSE（sync_institutional，只有投信先出）
      1  = 15:10  大盤法人（sync_market）
      9  = 15:30  OTC 三大法人（sync_otc_institutional）
      3  = 16:10  重跑 TWSE 三大法人（補外資 + 自營商）
      7  = 21:10  大盤融資（sync_market）
      8  = 21:30  借券賣出（sync_short_sale）
    """
    if today is None:
        today = get_today()

    # ── 防重疊：已有同步在跑就跳過，避免 thread 競爭 ──────────────────────
    if not _sync_lock.acquire(blocking=False):
        print(f"[sync_all] 上一次同步尚未完成，跳過此次觸發 label={label} ⚠️")
        return

    try:
        tag = f"label={label}" if label is not None else "全量"
        print(f"[sync_all] 開始同步 date={today} {tag}")

        if label == 2:
            # 15:00 — 投信 TWSE（外資/自營商此時尚未出爐，但先同步有資料的）
            sync_institutional(today)

        elif label == 1:
            # 15:10 — 大盤法人買賣金額
            sync_market(today)

        elif label == 9:
            # 15:30 — OTC 三大法人
            sync_otc_institutional(today)

        elif label == 3:
            # 16:10 — 重跑 TWSE 三大法人（補外資 + 自營商）
            sync_institutional(today)

        elif label == 7:
            # 21:10 — 大盤融資金額（重跑 market，融資資料此時才出）
            sync_market(today)

        elif label == 8:
            # 21:30 — 借券賣出
            sync_short_sale(today)

        else:
            # label=None 或未知 → 全量同步（手動觸發向下相容）
            now_hour = datetime.datetime.now(ZoneInfo("Asia/Taipei")).hour
            print(f"[sync_all] 全量模式 hour={now_hour}")

            if 15 <= now_hour < 21:
                sync_institutional(today)
                sync_otc_institutional(today)

            sync_market(today)

            if now_hour >= 21:
                sync_short_sale(today)

        print(f"[sync_all] 完成 date={today} {tag}")

    finally:
        _sync_lock.release()