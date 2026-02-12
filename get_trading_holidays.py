import requests
from datetime import date
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def is_trading_day():
    API_Holidays = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    res = requests.get(API_Holidays, headers=headers, verify=False)
    data = res.json()

    # 建立日期→名稱對應
    holidays = {item[0]: item[1] for item in data["data"]}

    Trading_day = {"國曆新年開始交易日", "農曆春節前最後交易日"}

    today = date.today().isoformat()
    #today = "2026-02-14"

    # 週六週日一定不是交易日
    if date.fromisoformat(today).weekday() >= 5:
        return False

    # 如果今天在假日表中
    if today in holidays:
        holiday_name = holidays[today]

        # 但有些是「交易日」例外
        if holiday_name in Trading_day:
            return True
        else:
            return False

    # 不在假日表 → 正常交易日
    return True