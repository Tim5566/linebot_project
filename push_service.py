from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from linebot.models import TextSendMessage

import pytz

def broadcast_job(line_bot_api):
    # 寫死訊息，或是這裡呼叫 query_investor 取得動態資料
    message = TextSendMessage(text="📢 盤後已更新資訊")
    line_bot_api.broadcast(message)   # 廣播給所有好友

def start_scheduler(line_bot_api):
    scheduler = BackgroundScheduler()
    taiwan = pytz.timezone("Asia/Taipei")
    # 每天 18:00 推播一次（可依需求調整）
    scheduler.add_job(lambda: broadcast_job(line_bot_api), 'cron', hour=15, minute=5, timezone=taiwan)

    scheduler.start()
