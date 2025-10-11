import requests
from datetime import date
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) #忽略警告

def is_trading_day():
    API_Holidays = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
    
    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕
    
    res = requests.get(API_Holidays, headers=headers, verify=False)
    data = res.json()

    holidays = set(item[0] for item in data["data"])

    today = date.today().isoformat()

    if today in holidays or date.today().weekday() >= 5:
        return False
    else:
        return True