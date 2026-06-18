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

def _fetch_with_date_check(url: str, today: str, label: str = "", max_retries: int = None):
    retries = max_retries if max_retries is not None else MAX_DATE_RETRIES
    for attempt in range(1, retries + 1):
        data = _fetch(url)
        if data is None:
            print(f"[{label}] 第{attempt}次請求失敗")
            if attempt < retries:
                print(f"[{label}] 等待 {DATE_RETRY_WAIT} 秒後重試...")
                _time.sleep(DATE_RETRY_WAIT)
            continue

        # stat 不是 OK（含 TWSE 自營商的特殊錯誤訊息）→ 視為資料未就緒，重試
        if isinstance(data, dict) and data.get("stat") not in (None, "", "OK"):
            print(f"[{label}] 第{attempt}次 stat={data.get('stat')}，資料未就緒，重試中...")
            if attempt < retries:
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
        if attempt < retries:
            print(f"[{label}] 等待 {DATE_RETRY_WAIT} 秒後重試...")
            _time.sleep(DATE_RETRY_WAIT)

    print(f"[{label}] 超過最大重試次數({retries})，放棄寫入 ⚠️")
    return None

def _check_twse_stat(data, today: str, label: str):
    # stat 已在 _fetch_with_date_check 過濾，這裡只做最後防線
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

def _fetch_twse_institutional(today: str, max_retries: int = None) -> dict:
    def _parse_foreign():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市外資", max_retries=max_retries), today, "上市外資")
        if not data: return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name): continue
            out[row[1].strip()] = {"name": name, "foreign": row[5].strip()}
        return out

    def _parse_trust():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市投信", max_retries=max_retries), today, "上市投信")
        if not data: return {}
        out = {}
        for row in data.get("data", []):
            name = row[2].strip()
            if re.search(r'購|售|認購|認售', name): continue
            out[row[1].strip()] = row[5].strip()
        return out

    def _parse_proprietary():
        url  = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={today}"
        data = _check_twse_stat(_fetch_with_date_check(url, today, "上市自營商", max_retries=max_retries), today, "上市自營商")
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

    # ✅ 修正：各法人 API 只回傳「當日有買賣」的股票，0 張的股票不出現。
    #
    # 判斷邏輯：
    #   foreign_ok / trust_ok / proprietary_ok = True
    #     → 該法人 API「今日已成功取得資料」（不管筆數多少，只要非空就算成功）
    #     → 若某股不在該法人清單，代表今日買賣 0 張，補寫 "0"
    #
    #   foreign_ok / trust_ok / proprietary_ok = False
    #     → 該法人 API「今日尚未取得資料」（官方還沒更新或抓取失敗）
    #     → 不寫入 Firebase，前端顯示「暫未更新」
    #
    # 注意各 map 結構：
    #   foreign_map     = { sid: {"name": 名稱, "foreign": 數值字串} }
    #   trust_map       = { sid: 數值字串 }          ← 只存淨買賣值
    #   proprietary_map = { sid: 數值字串 }          ← 只存淨買賣值
    foreign_ok     = bool(foreign_map)
    trust_ok       = bool(trust_map)
    proprietary_ok = bool(proprietary_map)

    result = {}
    for sid in set(foreign_map) | set(trust_map) | set(proprietary_map):
        # 名稱：外資 map 有就用，沒有就用代碼代替
        name = foreign_map.get(sid, {}).get("name", "") or sid

        record = {"name": name}

        # ── 外資 ────────────────────────────────────────────────────────────
        # foreign_map 的值是 dict，取 "foreign" 欄位
        if foreign_ok:
            # API 成功：在清單內就用實際值，不在清單內補 "0"（今日 0 張）
            record["foreign"] = foreign_map.get(sid, {}).get("foreign", "0")
        elif sid in foreign_map:
            # API 失敗但剛好有資料（理論上不會走到，保險用）
            record["foreign"] = foreign_map[sid].get("foreign")
        # else: foreign_ok=False 且 sid 不在 foreign_map → 不寫，保持 None（暫未更新）

        # ── 投信 ────────────────────────────────────────────────────────────
        # trust_map 的值直接是數值字串
        if trust_ok:
            record["trust"] = trust_map.get(sid, "0")
        elif sid in trust_map:
            record["trust"] = trust_map[sid]

        # ── 自營商 ──────────────────────────────────────────────────────────
        if proprietary_ok:
            record["proprietary"] = proprietary_map.get(sid, "0")
        elif sid in proprietary_map:
            record["proprietary"] = proprietary_map[sid]

        result[sid] = record

    print(f"[twse_inst] 共 {len(result)} 筆 ✅"
          f"（外資API={'✅' if foreign_ok else '❌'} "
          f"投信API={'✅' if trust_ok else '❌'} "
          f"自營商API={'✅' if proprietary_ok else '❌'}）")
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

def sync_institutional(today: str = None, max_retries: int = None):
    if today is None: today = get_today()
    retries_info = f"（max_retries={max_retries}）" if max_retries else ""
    print(f"[sync] 開始同步 TWSE 三大法人 date={today}{retries_info}")
    twse_inst = _fetch_twse_institutional(today, max_retries=max_retries)
    _init_firebase()
    if twse_inst:
        _write_batch(f"stock_data/{today}/twse", twse_inst)
    else:
        print("[sync] 上市三大法人無資料，略過 ⚠️")

    # ✅ 修正：記錄各 API 實際回傳筆數，而非只記合計
    # 三大法人各自的 API 回傳清單不同，用各別筆數判斷是否抓到，比抽樣股票更準確
    foreign_count     = sum(1 for v in twse_inst.values() if "foreign"     in v)
    trust_count       = sum(1 for v in twse_inst.values() if "trust"       in v)
    proprietary_count = sum(1 for v in twse_inst.values() if "proprietary" in v)
    print(f"[sync] TWSE 三大法人完成 {len(twse_inst)}筆（外資:{foreign_count} 投信:{trust_count} 自營商:{proprietary_count}）")

    firebase_db.reference(f"stock_data/{today}/meta").update({
        "twse_institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "twse_count":            len(twse_inst),
        "twse_foreign_count":    foreign_count,      # ✅ 新增：外資筆數
        "twse_trust_count":      trust_count,         # ✅ 新增：投信筆數
        "twse_proprietary_count":proprietary_count,   # ✅ 新增：自營商筆數
    })
    # 同步完立即更新 TWSE 前50快取，並清除舊日期快取
    if twse_inst:
        try:
            top100 = _calc_top100(twse_inst)
            firebase_db.reference(f"top100_cache/{today}/twse").set(top100)
            print(f"[top100] TWSE 快取更新 ✅")
            # 清除非今日的 top100_cache
            _cleanup_old_top100_cache(today)
        except Exception as e:
            print(f"[top100] TWSE 快取失敗: {e}")
    return len(twse_inst) > 0

def sync_otc_institutional(today: str = None):
    if today is None: today = get_today()
    print(f"[sync] 開始同步 OTC 三大法人 date={today}")
    otc_inst = _fetch_otc_institutional(today)
    _init_firebase()
    if otc_inst:
        _write_batch(f"stock_data/{today}/otc", otc_inst)
    else:
        print("[sync] 上櫃三大法人無資料，略過 ⚠️")
    # ✅ 修正：記錄各欄位實際筆數，供 _check_data_missing_otc 判斷
    otc_foreign_count     = sum(1 for v in otc_inst.values() if "foreign"     in v)
    otc_trust_count       = sum(1 for v in otc_inst.values() if "trust"       in v)
    otc_proprietary_count = sum(1 for v in otc_inst.values() if "proprietary" in v)
    print(f"[sync] OTC 三大法人完成 {len(otc_inst)}筆（外資:{otc_foreign_count} 投信:{otc_trust_count} 自營商:{otc_proprietary_count}）")

    firebase_db.reference(f"stock_data/{today}/meta").update({
        "otc_institutional_updated": datetime.datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "otc_count":            len(otc_inst),
        "otc_foreign_count":    otc_foreign_count,      # ✅ 新增
        "otc_trust_count":      otc_trust_count,         # ✅ 新增
        "otc_proprietary_count":otc_proprietary_count,   # ✅ 新增
    })
    # 同步完立即更新 OTC 前50快取，並清除舊日期快取
    if otc_inst:
        try:
            top100 = _calc_top100(otc_inst)
            firebase_db.reference(f"top100_cache/{today}/otc").set(top100)
            print(f"[top100] OTC 快取更新 ✅")
            # 清除非今日的 top100_cache
            _cleanup_old_top100_cache(today)
        except Exception as e:
            print(f"[top100] OTC 快取失敗: {e}")

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



# ── 清除舊日 stock_data（保留今日，刪除其餘）────────────────────────────────
def cleanup_old_stock_data(today: str = None):
    """
    刪除 stock_data 下除了今日以外的所有日期節點。
    例如今天是 20260528，會把 20260527、20260526 ... 全部刪除。
    在每天 label=2（15:00）第一次同步時執行一次即可。
    """
    if today is None:
        today = get_today()
    _init_firebase()
    try:
        ref  = firebase_db.reference("stock_data")
        keys = ref.get(shallow=True)  # 只取子節點 key，不撈完整資料
        if not keys:
            print("[cleanup] stock_data 無資料，略過")
            return
        old_keys = [k for k in keys if k != today]
        if not old_keys:
            print(f"[cleanup] 無舊資料需刪除（只有 {today}）")
            return
        for key in old_keys:
            firebase_db.reference(f"stock_data/{key}").delete()
            print(f"[cleanup] 已刪除 stock_data/{key} ✅")
        print(f"[cleanup] 共刪除 {len(old_keys)} 筆舊資料，保留 {today}")
    except Exception as e:
        print(f"[cleanup] 刪除舊資料失敗: {e} ⚠️")


# ── 防重疊執行鎖（同一時間只允許一個 sync_all 在跑）────────────────────────
import threading as _threading
_sync_lock = _threading.Lock()


def _cleanup_old_top100_cache(today: str = None):
    """
    刪除 top100_cache 下除了今日以外的所有日期節點，防止資料庫持續膨脹。
    每次寫入 top100_cache 後自動呼叫；sync_top100() 末尾亦會呼叫。
    """
    if today is None:
        today = get_today()
    try:
        ref  = firebase_db.reference("top100_cache")
        keys = ref.get(shallow=True)
        if not keys:
            return
        old_keys = [k for k in keys if k != today]
        for key in old_keys:
            firebase_db.reference(f"top100_cache/{key}").delete()
            print(f"[top100] 清除舊快取 top100_cache/{key} ✅")
        if old_keys:
            print(f"[top100] 共清除 {len(old_keys)} 筆舊快取，保留 {today}")
    except Exception as e:
        print(f"[top100] 清除舊快取失敗: {e} ⚠️")


def _calc_top100(inst_dict: dict, top_n: int = 100) -> dict:
    """
    從全量法人資料計算買超/賣超前100。
    inst_dict: { sid: {name, foreign, trust, proprietary} }
    回傳: {
      foreign:     { buy: [{id,name,net}, ...], sell: [...] },
      trust:        { buy: [...], sell: [...] },
      proprietary:  { buy: [...], sell: [...] },
    }
    """
    buckets = {
        "foreign":    {"buy": [], "sell": []},
        "trust":      {"buy": [], "sell": []},
        "proprietary":{"buy": [], "sell": []},
    }
    for sid, info in inst_dict.items():
        if not sid:
            continue
        name = info.get("name", sid)
        for key in ("foreign", "trust", "proprietary"):
            raw = info.get(key)
            if raw is None:
                continue
            try:
                net = int(str(raw).replace(",", ""))
            except (ValueError, TypeError):
                continue
            direction = "buy" if net > 0 else "sell" if net < 0 else None
            if direction:
                buckets[key][direction].append({"id": sid, "name": name, "net": net})

    # 排序並截前50
    for key in buckets:
        buckets[key]["buy"]  = sorted(buckets[key]["buy"],  key=lambda x: -x["net"])[:top_n]
        buckets[key]["sell"] = sorted(buckets[key]["sell"], key=lambda x:  x["net"])[:top_n]

    return buckets


def sync_top100(today: str = None):
    """
    從 Firebase 今日全量資料計算前100，寫入快取節點：
      top100_cache/{today}/twse  →  { foreign:{buy:[],sell:[]}, trust:..., proprietary:... }
      top100_cache/{today}/otc   →  同上
    每次 sync_institutional / sync_otc_institutional 完成後自動呼叫。
    """
    if today is None:
        today = get_today()
    _init_firebase()

    def _calc_and_write(market: str):
        try:
            data = firebase_db.reference(f"stock_data/{today}/{market}").get()
            if not data:
                print(f"[top100] {market} 無資料，略過")
                return
            top100 = _calc_top100(data)
            firebase_db.reference(f"top100_cache/{today}/{market}").set(top100)
            counts = {k: len(v["buy"]) for k, v in top100.items()}
            print(f"[top100] {market} 快取寫入完成 {counts} ✅")
        except Exception as e:
            print(f"[top100] {market} 計算失敗: {e} ⚠️")

    _calc_and_write("twse")
    _calc_and_write("otc")

    # 順便清除舊的 top100 快取（保留今日）
    _cleanup_old_top100_cache(today)


def sync_all(today: str = None, label: int = None):
    """
    依 label 精確執行對應同步任務，避免每次全跑造成重疊與多餘 API 呼叫。

    label 對照排程：
      None / 手動 → 全量同步（向下相容手動觸發）
      2  = 15:00  投信 TWSE（sync_institutional，只有投信先出）
      1  = 15:10  大盤法人（sync_market）
      9  = 15:30  OTC 三大法人（sync_otc_institutional）★ 不受鎖限制
      10 = 16:30  OTC 三大法人補跑（萬一 15:30 失敗）★ 不受鎖限制
      3  = 16:15  重跑 TWSE 三大法人（補外資 + 自營商）
      7  = 21:10  大盤融資（sync_market）
      8  = 21:30  借券賣出（sync_short_sale）
    """
    if today is None:
        today = get_today()

    # ── label=9 / label=10：OTC 資料來源獨立，不需要跟 TWSE 搶鎖 ──────────
    # 根本原因：label=2 含 DATE_RETRY_WAIT 等待，執行時間長，
    # 若 label=9 在鎖內等待會直接被 blocking=False 跳過，造成 OTC 當天沒寫入。
    if label in (9, 10):
        tag = f"label={label}"
        print(f"[sync_all] 開始同步 date={today} {tag}（OTC 獨立執行，不受鎖限制）")
        try:
            sync_otc_institutional(today)
            print(f"[sync_all] 完成 date={today} {tag}")
        except Exception as e:
            print(f"[sync_all] OTC 同步失敗 {tag}: {e} ⚠️")
        return

    # ── 防重疊：已有同步在跑就跳過，避免 thread 競爭 ──────────────────────
    if not _sync_lock.acquire(blocking=False):
        print(f"[sync_all] 上一次同步尚未完成，跳過此次觸發 label={label} ⚠️")
        return

    try:
        tag = f"label={label}" if label is not None else "全量"
        print(f"[sync_all] 開始同步 date={today} {tag}")

        if label == 2:
            # 15:00 — 先清除昨日（含更早）舊資料，再同步今日投信 TWSE
            cleanup_old_stock_data(today)
            sync_institutional(today)
            # 投信安全網：萬一 TWSE 15:00 也慢，每30分鐘補抓，最多到 18:00
            if _check_data_missing(today, check_foreign=False, check_proprietary=False):
                schedule_retry_if_missing(
                    today, label=2,
                    interval_minutes=30,
                    deadline_hour=18,
                    max_attempts=4,
                )

        elif label == 1:
            # 15:10 — 大盤法人買賣金額
            sync_market(today)

        elif label == 9:
            # 15:30 — OTC 三大法人
            sync_otc_institutional(today)
            # OTC 安全網：萬一 tpex 也慢，每30分鐘補抓，最多到 21:00
            if _check_data_missing_otc(today):
                schedule_retry_if_missing(
                    today, label=9,
                    interval_minutes=30,
                    deadline_hour=21,
                    max_attempts=6,
                )

        elif label == 3:
            # 16:15 — 重跑 TWSE 三大法人（補外資 + 自營商）
            # ✅ 先立即執行一次同步（與 label=2 一致）
            sync_institutional(today, max_retries=6)
            # 若仍有欄位缺失，再啟動背景自動重試，每5分鐘直到21:00或資料完整
            # 間隔從30分鐘縮短為5分鐘：TWSE API 實測約在排程後10~20分鐘才就緒，
            # 縮短間隔讓系統能在API更新後盡快自動補抓，不需手動介入
            if _check_data_missing(today, check_trust=False):
                schedule_retry_if_missing(
                    today, label=3,
                    interval_minutes=5,
                    deadline_hour=21,
                    max_attempts=20,
                )

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

            sync_market(today)

            sync_institutional(today)
            sync_otc_institutional(today)

            sync_short_sale(today)

        print(f"[sync_all] 完成 date={today} {tag}")

    finally:
        _sync_lock.release()

# ── 自動重試排程（TWSE/OTC 資料未更新時每30分鐘補抓）────────────────────────

_retry_threads: dict = {}
_retry_threads_lock = _threading.Lock()


def _check_data_missing(today: str,
                         check_foreign: bool = True,
                         check_trust: bool = True,
                         check_proprietary: bool = True) -> bool:
    """
    檢查 Firebase 今日 TWSE 資料是否完整。
    回傳 True 表示「仍有缺失，需要重試」。

    ✅ 修正：改用 meta 裡各 API 實際筆數判斷，不再抽樣單一股票。
    原因：三大法人三支 API 的股票清單本來就不完全相同（例如投信當天
    沒買賣的股票不會出現），單一股票缺某欄位是正常現象，不代表 API 沒抓到。
    """
    try:
        _init_firebase()
        meta = firebase_db.reference(f"stock_data/{today}/meta").get() or {}
        twse_count = int(meta.get("twse_count", 0))

        if twse_count == 0:
            print(f"[retry_check] twse_count=0，確認需要重試")
            return True

        missing = []
        if check_foreign and int(meta.get("twse_foreign_count", 0)) == 0:
            missing.append("外資")
        if check_trust and int(meta.get("twse_trust_count", 0)) == 0:
            missing.append("投信")
        if check_proprietary and int(meta.get("twse_proprietary_count", 0)) == 0:
            missing.append("自營商")

        if missing:
            print(f"[retry_check] TWSE 缺失：{missing}（meta counts: "
                  f"外資={meta.get('twse_foreign_count',0)} "
                  f"投信={meta.get('twse_trust_count',0)} "
                  f"自營商={meta.get('twse_proprietary_count',0)}）")
            return True

        print(f"[retry_check] TWSE 資料完整 ✅（"
              f"外資={meta.get('twse_foreign_count')} "
              f"投信={meta.get('twse_trust_count')} "
              f"自營商={meta.get('twse_proprietary_count')}）")
        return False

    except Exception as e:
        print(f"[retry_check] Firebase 檢查失敗: {e}，視為需要重試")
        return True


def _check_data_missing_otc(today: str) -> bool:
    """
    檢查 Firebase 今日 OTC 資料是否完整。
    回傳 True 表示「仍有缺失，需要重試」。

    ✅ 修正：改用 meta 裡 otc_foreign_count 等筆數判斷，不再抽樣單一股票。
    OTC API 一次回傳三大法人全部欄位，只要各筆數 > 0 即視為完整。
    """
    try:
        _init_firebase()
        meta = firebase_db.reference(f"stock_data/{today}/meta").get() or {}
        otc_count = int(meta.get("otc_count", 0))

        if otc_count == 0:
            print(f"[retry_check_otc] otc_count=0，確認需要重試")
            return True

        missing = []
        if int(meta.get("otc_foreign_count", 0)) == 0:
            missing.append("外資")
        if int(meta.get("otc_trust_count", 0)) == 0:
            missing.append("投信")
        if int(meta.get("otc_proprietary_count", 0)) == 0:
            missing.append("自營商")

        if missing:
            print(f"[retry_check_otc] OTC 缺失：{missing}（meta counts: "
                  f"外資={meta.get('otc_foreign_count',0)} "
                  f"投信={meta.get('otc_trust_count',0)} "
                  f"自營商={meta.get('otc_proprietary_count',0)}）")
            return True

        print(f"[retry_check_otc] OTC 資料完整 ✅（"
              f"外資={meta.get('otc_foreign_count')} "
              f"投信={meta.get('otc_trust_count')} "
              f"自營商={meta.get('otc_proprietary_count')}）")
        return False

    except Exception as e:
        print(f"[retry_check_otc] Firebase 檢查失敗: {e}，視為需要重試")
        return True


def schedule_retry_if_missing(
    today: str,
    label: int,
    interval_minutes: int = 30,
    deadline_hour: int = 21,
    max_attempts: int = 8,
):
    """
    若今日資料缺失，立即先嘗試一次同步；
    若仍失敗，啟動背景 thread，每 interval_minutes 分鐘重試一次，
    直到資料完整、超過 deadline_hour，或達到 max_attempts 為止。

    label 對照：
      2  → sync_institutional（TWSE 投信安全網）
      3  → sync_institutional（TWSE 外資+自營商補跑）
      9  → sync_otc_institutional（OTC 三大法人）
      10 → sync_otc_institutional（OTC 補跑）
    """
    thread_key = f"retry_{label}_{today}"

    with _retry_threads_lock:
        existing = _retry_threads.get(thread_key)
        if existing and existing.is_alive():
            print(f"[retry] label={label} 重試 thread 已在執行中，略過")
            return

    print(f"[retry] label={label} 啟動自動重試排程（間隔{interval_minutes}分鐘，截止{deadline_hour}:00，最多{max_attempts}次）")

    # label → 哪些欄位在重試中（用於寫 Firebase meta 讓前端顯示倒數）
    _LABEL_FIELDS = {
        2:  ["trust"],
        3:  ["foreign", "proprietary"],
        9:  ["foreign", "trust", "proprietary"],
        10: ["foreign", "trust", "proprietary"],
    }

    def _write_retry_status(next_ts_iso: str):
        """把重試狀態寫入 Firebase meta，前端讀取後顯示倒數計時。"""
        fields = _LABEL_FIELDS.get(label, [])
        if not fields:
            return
        try:
            _init_firebase()
            firebase_db.reference(f"stock_data/{today}/meta").update({
                "retry_fields":  fields,
                "retry_next_at": next_ts_iso,   # ISO 字串，前端 new Date() 可直接解析
                "retry_label":   label,
            })
        except Exception as e:
            print(f"[retry] 寫入重試狀態失敗: {e}")

    def _clear_retry_status():
        """資料補齊後清除重試狀態，前端停止顯示倒數。"""
        try:
            _init_firebase()
            firebase_db.reference(f"stock_data/{today}/meta").update({
                "retry_fields":  None,
                "retry_next_at": None,
                "retry_label":   None,
            })
        except Exception as e:
            print(f"[retry] 清除重試狀態失敗: {e}")

    def _worker():
        tz = ZoneInfo("Asia/Taipei")
        for attempt in range(1, max_attempts + 1):
            now = datetime.datetime.now(tz)

            # 超過截止時間就停止
            if now.hour >= deadline_hour:
                print(f"[retry] label={label} 已超過 {deadline_hour}:00，停止重試")
                _clear_retry_status()
                break

            print(f"[retry] label={label} 第 {attempt}/{max_attempts} 次嘗試 {now.strftime('%H:%M:%S')}")

            try:
                if label in (9, 10):
                    # OTC 本來就不走 _sync_lock，直接執行
                    sync_otc_institutional(today)
                else:
                    # TWSE 類同步需搶 _sync_lock，避免與 label=7/8 排程同時寫 Firebase
                    if not _sync_lock.acquire(timeout=60):
                        print(f"[retry] label={label} 第{attempt}次搶鎖逾時，跳過本次")
                        continue
                    try:
                        if label in (3, 2):
                            sync_institutional(today, max_retries=6)
                        elif label == 1:
                            sync_market(today)
                        else:
                            sync_institutional(today, max_retries=6)
                    finally:
                        _sync_lock.release()
            except Exception as e:
                print(f"[retry] label={label} 第{attempt}次同步例外: {e}")

            # 檢查資料是否已完整
            if label in (9, 10):
                still_missing = _check_data_missing_otc(today)
            else:
                still_missing = _check_data_missing(today)

            if not still_missing:
                print(f"[retry] label={label} 資料已完整，停止重試 ✅")
                _clear_retry_status()
                break

            if attempt < max_attempts:
                next_dt = now + datetime.timedelta(minutes=interval_minutes)
                if next_dt.hour >= deadline_hour:
                    print(f"[retry] label={label} 下次重試將超過截止時間，放棄")
                    _clear_retry_status()
                    break
                next_time = next_dt.strftime('%H:%M')
                # ── 寫入重試狀態讓前端顯示倒數 ────────────────────────────────
                _write_retry_status(next_dt.isoformat())
                print(f"[retry] label={label} 資料仍缺失，{interval_minutes}分鐘後 {next_time} 再試...")
                _time.sleep(interval_minutes * 60)
            else:
                print(f"[retry] label={label} 達最大重試次數 {max_attempts}，放棄 ⚠️")
                _clear_retry_status()

    t = _threading.Thread(target=_worker, name=thread_key, daemon=True)
    with _retry_threads_lock:
        _retry_threads[thread_key] = t
    t.start()