
# 西元轉民國
def to_minguo(date_str):
    year = int(date_str[:4]) - 1911
    return f"{year:03d}{date_str[4:]}"

today = "20260211"
today_minguo = to_minguo(today)
print(today_minguo)