from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo
from get_trading_holidays import is_trading_day

import pytz

def broadcast_post_inf(line_bot_api, label):
    #如果今天休市
    if not is_trading_day():
        if label == 0:
            message = TextSendMessage(text="📢 今日週末或連假未開盤❗")
            line_bot_api.broadcast(message)
        return
    if label == 1:
        message = [
            TextSendMessage(text="📢 今盤後，法人總買賣金額已更新❗"),
            TextSendMessage(text=market_pnfo())
        ]
    elif label == 2:
        message = TextSendMessage(text="📢 今盤後，投信買賣超已更新❗\n目前個股可供查詢。")
    elif label == 3:
        message = TextSendMessage(text="📢 今盤後，外資買賣超已更新❗\n目前個股可供查詢。")
    elif label == 4:
        message = TextSendMessage(text="📢 今盤後，自營商買賣超已更新❗\n目前個股可供查詢。")
    elif label == 5:
        message = [
            TextSendMessage(text="📢 今盤後，大盤融資金額已更新❗"),
            TextSendMessage(text=market_pnfo())
        ]
    elif label == 6:
        message = TextSendMessage(text="📢 今盤後，借卷賣出已更新❗\n目前個股可供查詢。")

    line_bot_api.broadcast(message) 

def start_scheduler(line_bot_api):
    scheduler = BackgroundScheduler()
    taiwan = pytz.timezone("Asia/Taipei")

    # 判斷是否週末或連假
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 0), 'cron', hour=15, minute=0, timezone=taiwan) #15:00

    # 盤後整體資訊更新時間
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 1), 'cron', hour=15, minute=32, timezone=taiwan) #15:00
    
    # 三大法人個股買賣超更新時間
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 2), 'cron', hour=15, minute=0, timezone=taiwan) #15:00
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 3), 'cron', hour=16, minute=10, timezone=taiwan) #16:10
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 4), 'cron', hour=16, minute=10, timezone=taiwan) #16:10

    ##大盤融資卷總金額統計
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 5), 'cron', hour=21, minute=0, timezone=taiwan) #21:00

    # 個股借卷賣出
    scheduler.add_job(lambda: broadcast_post_inf(line_bot_api, 6), 'cron', hour=21, minute=30, timezone=taiwan) #21:30

    scheduler.start()