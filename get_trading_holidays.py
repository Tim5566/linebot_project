import requests
from datetime import date, timedelta
import time as _time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_Holidays = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
headers = {"User-Agent": "Mozilla/5.0"}

Trading_day = {"國曆新年開始交易日", "農曆春節前最後交易日"}

# ── 假日清單記憶體快取（一天內只打一次 TWSE，避免每 30 秒輪詢狂打）────────
_holidays_cache:     dict  = {}
_holidays_cache_date: str  = ""   # 快取對應的日期（YYYY-MM-DD）
_holidays_last_fetch: float = 0.0
_HOLIDAYS_COOLDOWN = 3600         # 最多每小時打一次 API（秒）

def _fetch_holidays():
    global _holidays_cache, _holidays_cache_date, _holidays_last_fetch

    today_str = date.today().isoformat()
    now_ts    = _time.time()

    # 同一天且冷卻期內 → 直接回傳快取，不打 TWSE
    if (_holidays_cache_date == today_str
            and (now_ts - _holidays_last_fetch) < _HOLIDAYS_COOLDOWN):
        return _holidays_cache

    try:
        res  = requests.get(API_Holidays, headers=headers, verify=False, timeout=10)
        data = res.json()
        result = {item[0]: item[1] for item in data["data"]}
        # 更新快取
        _holidays_cache      = result
        _holidays_cache_date = today_str
        _holidays_last_fetch = now_ts
        return result
    except Exception as e:
        print(f"[holidays] API 失敗: {e}，回傳空字典，預設為交易日")
        # 失敗時若有舊快取就回傳舊快取，沒有才回傳空字典
        return _holidays_cache if _holidays_cache else {}

def _is_trading_day_for(d: date, holidays: dict) -> bool:
    if d.weekday() >= 5:
        return False
    iso = d.isoformat()
    if iso in holidays:
        return holidays[iso] in Trading_day
    return True

def is_trading_day() -> bool:
    holidays = _fetch_holidays()
    today = date.today()
    return _is_trading_day_for(today, holidays)

# ── get_trading_status 結果快取（api/trading_status 每次呼叫都會用到）────────
_trading_status_result_cache: dict = {}
_trading_status_result_date:  str  = ""

def get_trading_status() -> dict:
    global _trading_status_result_cache, _trading_status_result_date
    today     = date.today()
    today_str = today.isoformat()

    # 同一天已算過 → 直接回傳（holidays 已有自己的 1 小時冷卻）
    if _trading_status_result_date == today_str and _trading_status_result_cache:
        return _trading_status_result_cache

    holidays   = _fetch_holidays()
    is_trading = _is_trading_day_for(today, holidays)

    next_day = None
    if not is_trading:
        d = today
        for _ in range(30):
            d += timedelta(days=1)
            if _is_trading_day_for(d, holidays):
                next_day = d.isoformat()
                break

    result = {
        "is_trading_day":   is_trading,
        "today":            today_str,
        "next_trading_day": next_day,
    }
    _trading_status_result_cache = result
    _trading_status_result_date  = today_str
    return result