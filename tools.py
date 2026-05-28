import datetime

def to_minguo(date_str):
    year = int(date_str[:3]) + 1911
    return f"{year}{date_str[3:]}"