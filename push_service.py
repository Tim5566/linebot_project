from apscheduler.schedulers.background import BackgroundScheduler
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
    # 每天推播一次
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 0), 'cron', hour=15, minute=0, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 1), 'cron', hour=16, minute=10, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 2), 'cron', hour=16, minute=10, timezone=taiwan)

    scheduler.start()
