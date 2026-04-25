"""
push_service.py（Firebase 同步版）
────────────────────────────────────────────────────────────────────────────
排程流程：
  1. 先呼叫 firebase_sync 同步資料到 Firebase
  2. 再廣播 LINE 通知

這樣使用者收到通知後查詢時，Firebase 已有最新資料。
────────────────────────────────────────────────────────────────────────────
"""

from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo
from get_trading_holidays import is_trading_day
import firebase_sync
import pytz

# ── 排程設定 ──────────────────────────────────────────────────────────────────
# label 對應說明：
#   0 → 休市通知（09:00）
#   1 → 法人總買賣金額 + 大盤資訊（15:10）── 同步三大法人 + 大盤
#   2 → 投信買賣超（15:00）
#   3 → 外資買賣超（16:10）
#   4 → 自營商買賣超（16:10）
#   5 → 處置股（17:30）── 同步處置股
#   6 → 注意股（17:30）
#   7 → 大盤融資金額 + 大盤資訊（21:10）── 同步大盤融資
#   8 → 借券賣出（21:30）── 同步借券賣出

SCHEDULE = [
    (0, 9,  0,  "休市通知"),
    (2, 15, 0,  "投信買賣超"),
    (1, 15, 10, "法人總買賣金額"),
    (3, 16, 10, "外資買賣超"),
    (4, 16, 10, "自營商買賣超"),
    (5, 17, 30, "處置股"),
    (6, 17, 30, "注意股"),
    (7, 21, 10, "大盤融資金額"),
    (8, 21, 30, "借券賣出"),
]

# ── Firebase 同步任務（各時段觸發）──────────────────────────────────────────
def _run_sync(label: int):
    """
    根據 label 決定要同步哪些資料。
    在廣播通知之前執行，確保使用者查詢時 Firebase 已有資料。
    """
    if not is_trading_day():
        return  # 休市不同步

    try:
        if label == 1:
            # 15:10：三大法人 + 大盤（金額）
            firebase_sync.sync_institutional()
            firebase_sync.sync_market()
        elif label == 5:
            # 17:30：處置股
            firebase_sync.sync_disposal()
        elif label == 7:
            # 21:10：大盤融資（更新）
            firebase_sync.sync_market()
        elif label == 8:
            # 21:30：借券賣出
            firebase_sync.sync_short_sale()
    except Exception as e:
        print(f"[sync_error] label={label} {e}")


# ── 廣播訊息內容 ──────────────────────────────────────────────────────────────
def _build_message(label):
    if label == 1:
        return [
            TextSendMessage(text="📢 今盤後，法人總買賣金額已更新❗"),
            TextSendMessage(text=market_pnfo()),
        ]
    if label == 7:
        return [
            TextSendMessage(text="📢 今盤後，大盤融資金額已更新❗"),
            TextSendMessage(text=market_pnfo()),
        ]

    texts = {
        2: "📢 今盤後，投信買賣超已更新❗\n目前個股可供查詢。",
        3: "📢 今盤後，外資買賣超已更新❗\n目前個股可供查詢。",
        4: "📢 今盤後，自營商買賣超已更新❗\n目前個股可供查詢。",
        5: "📢 今盤後，處置股已更新❗\n目前個股可供查詢。",
        6: "📢 今盤後，注意股已更新❗\n目前個股可供查詢。",
        8: "📢 今盤後，借券賣出已更新❗\n目前個股可供查詢。",
    }
    return TextSendMessage(text=texts[label])


# ── 廣播執行 ──────────────────────────────────────────────────────────────────
def broadcast_post_inf(line_bot_api, label):
    if not is_trading_day():
        if label == 0:
            line_bot_api.broadcast(TextSendMessage(text="📢 今日週末或連假未開盤❗"))
        return

    # 先同步 Firebase，再廣播通知
    _run_sync(label)
    line_bot_api.broadcast(_build_message(label))


# ── 排程啟動 ──────────────────────────────────────────────────────────────────
def start_scheduler(line_bot_api):
    scheduler = BackgroundScheduler()
    taiwan    = pytz.timezone("Asia/Taipei")

    for label, hour, minute, _ in SCHEDULE:
        scheduler.add_job(
            lambda lb=label: broadcast_post_inf(line_bot_api, lb),
            'cron',
            hour=hour, minute=minute,
            timezone=taiwan,
        )

    scheduler.start()