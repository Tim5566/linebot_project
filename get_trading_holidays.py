import requests
from datetime import date, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_Holidays = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
headers = {"User-Agent": "Mozilla/5.0"}

Trading_day = {"國曆新年開始交易日", "農曆春節前最後交易日"}

def _fetch_holidays():
    res  = requests.get(API_Holidays, headers=headers, verify=False)
    data = res.json()
    return {item[0]: item[1] for item in data["data"]}

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

def get_trading_status() -> dict:
    holidays  = _fetch_holidays()
    today     = date.today()
    is_trading = _is_trading_day_for(today, holidays)

    next_day = None
    if not is_trading:
        d = today
        for _ in range(30):
            d += timedelta(days=1)
            if _is_trading_day_for(d, holidays):
                next_day = d.isoformat()
                break

    return {
        "is_trading_day":   is_trading,
        "today":            today.isoformat(),
        "next_trading_day": next_day,
    }