"""
push_service.py（Firebase 同步版）
────────────────────────────────────────────────────────────────────────────
修正重點：
  1. _run_sync 的 sync_institutional 和 sync_market 分開 try/except
     → institutional 失敗不會連 market 也一起跳過
  2. 新增 label=9（15:20）專門同步 OTC 三大法人
     → OTC 獨立排程，不被 TWSE 的 retry 拖累
  3. sync_institutional 改為只跑 TWSE，OTC 由 label=9 負責
  4. start_scheduler() 移到模組層級呼叫
     → Render 用 gunicorn 啟動時也會執行排程
────────────────────────────────────────────────────────────────────────────
"""

from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo
from get_trading_holidays import is_trading_day
import firebase_sync
import pytz

# ── 排程設定 ──────────────────────────────────────────────────────────────────
# label 說明：
#   0  = 09:00 休市通知
#   1  = 15:10 TWSE 三大法人 + 大盤
#   2  = 15:00 投信買賣超廣播
#   3  = 16:10 外資買賣超廣播
#   4  = 16:10 自營商買賣超廣播
#   5  = 17:30 處置股
#   6  = 17:30 注意股
#   7  = 21:10 大盤融資金額更新
#   8  = 21:30 借券賣出
#   9  = 15:20 OTC 三大法人（獨立排程，與 TWSE 不互相拖累）
SCHEDULE = [
    (0, 9,  0,  "休市通知"),
    (2, 15, 0,  "投信買賣超"),
    (1, 15, 10, "法人總買賣金額"),
    (9, 15, 10, "OTC三大法人"),       # ✅ 新增：OTC 獨立排程，與 TWSE 同時觸發但跑在不同 thread
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
    ⚠️ 每個同步任務獨立 try/except，避免一個失敗連累其他任務。
    """
    if not is_trading_day():
        return

    if label == 1:
        # 15:10：只同步 TWSE 三大法人，再同步大盤
        try:
            firebase_sync.sync_institutional()
        except Exception as e:
            print(f"[sync_error] label={label} sync_institutional 失敗: {e}")

        try:
            firebase_sync.sync_market()
        except Exception as e:
            print(f"[sync_error] label={label} sync_market 失敗: {e}")

    elif label == 9:
        # 15:20：OTC 三大法人（獨立排程，不被 TWSE retry 拖累）
        try:
            firebase_sync.sync_otc_institutional()
        except Exception as e:
            print(f"[sync_error] label={label} sync_otc_institutional 失敗: {e}")

    elif label == 5:
        # 17:30：處置股
        try:
            firebase_sync.sync_disposal()
        except Exception as e:
            print(f"[sync_error] label={label} sync_disposal 失敗: {e}")

    elif label == 7:
        # 21:10：大盤融資（更新）
        try:
            firebase_sync.sync_market()
        except Exception as e:
            print(f"[sync_error] label={label} sync_market 失敗: {e}")

    elif label == 8:
        # 21:30：借券賣出
        try:
            firebase_sync.sync_short_sale()
        except Exception as e:
            print(f"[sync_error] label={label} sync_short_sale 失敗: {e}")


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
        # label=9 是後台同步，不對用戶廣播
    }
    return TextSendMessage(text=texts[label])


# ── 廣播執行 ──────────────────────────────────────────────────────────────────
def broadcast_post_inf(line_bot_api, label):
    if not is_trading_day():
        if label == 0:
            line_bot_api.broadcast(TextSendMessage(text="📢 今日週末或連假未開盤❗"))
        return

    # 先同步 Firebase
    _run_sync(label)

    # label=9 是後台靜默同步，不廣播給用戶
    if label == 9:
        return

    # 其他 label 才廣播通知
    msg = _build_message(label)
    if msg:
        line_bot_api.broadcast(msg)


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
    print("[scheduler] 排程已啟動 ✅")