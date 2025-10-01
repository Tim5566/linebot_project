from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from linebot.models import TextSendMessage

import pytz

def broadcast_post_inf(line_bot_api, label):
    if label == 0:
        message = TextSendMessage(text="📢 今盤後，投信買賣超資訊已更新!!!\n目前可供查詢。")
    elif label == 1:
        message = TextSendMessage(text="📢 今盤後，外資買賣超資訊已更新!!!\n目前可供查詢。")
    else:
        message = TextSendMessage(text="📢 今盤後，自營商買賣超資訊已更新!!!\n目前可供查詢。")
    line_bot_api.broadcast(message)   # 廣播給所有好友

def start_scheduler(line_bot_api):
    scheduler = BackgroundScheduler()
    taiwan = pytz.timezone("Asia/Taipei")
    # 每天 18:00 推播一次（可依需求調整）
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 0), 'cron', hour=15, minute=40, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 1), 'cron', hour=15, minute=43, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 2), 'cron', hour=15, minute=45, timezone=taiwan)

    scheduler.start()
