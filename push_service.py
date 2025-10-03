from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo

import pytz

def broadcast_post_inf(line_bot_api, label):
    if label == 0:
        message = TextSendMessage(text=f"📢 今盤後，三大法人買賣金額已更新❗\n{market_pnfo()}")
    elif label == 1:
        message = TextSendMessage(text="📢 今盤後，投信買賣超已更新❗\n目前個股可供查詢。")
    elif label == 2:
        message = TextSendMessage(text="📢 今盤後，外資買賣超已更新❗\n目前個股可供查詢。")
    elif label == 3:
        message = TextSendMessage(text="📢 今盤後，自營商買賣超已更新❗\n目前個股可供查詢。")

    line_bot_api.broadcast(message) 

def start_scheduler(line_bot_api):
    scheduler = BackgroundScheduler()
    taiwan = pytz.timezone("Asia/Taipei")

    # 盤後整體資訊更新時間
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 0), 'cron', hour=17, minute=40, timezone=taiwan)

    # 三大法人個股買賣超更新時間
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 1), 'cron', hour=15, minute=0, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 2), 'cron', hour=16, minute=10, timezone=taiwan)
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 3), 'cron', hour=16, minute=10, timezone=taiwan)

    scheduler.start()