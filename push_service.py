"""
push_service.py（Firebase 同步版）
────────────────────────────────────────────────────────────────────────────
修正：同步邏輯拆開，各 label 只同步自己負責的欄位
  label 2 (15:00) → 只同步投信 sync_trust()
  label 1 (15:10) → 只同步大盤 sync_market()
  label 3 (16:10) → 只同步外資 sync_foreign()
  label 4 (16:10) → 只同步自營商 sync_proprietary()
  各自用 ref.child(sid).update() 寫入，不互相覆蓋
────────────────────────────────────────────────────────────────────────────
"""

from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo
from get_trading_holidays import is_trading_day
import firebase_sync
import pytz

# ── 排程設定（時間維持原本）─────────────────────────────────────────────────────
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


# ── Firebase 同步任務 ─────────────────────────────────────────────────────────
def _run_sync(label: int):
    if not is_trading_day():
        return

    if label == 2:
        # 15:00：只同步投信（TWT44U 14:50 就好了）
        try:
            firebase_sync.sync_trust()
        except Exception as e:
            print(f"[sync_error] label={label} sync_trust 失敗: {e}")

    elif label == 1:
        # 15:10：只同步大盤法人合計 + market
        try:
            firebase_sync.sync_market()
        except Exception as e:
            print(f"[sync_error] label={label} sync_market 失敗: {e}")

    elif label == 3:
        # 16:10：只同步外資（TWT38U 16:05 才好）
        try:
            firebase_sync.sync_foreign()
        except Exception as e:
            print(f"[sync_error] label={label} sync_foreign 失敗: {e}")

    elif label == 4:
        # 16:10：只同步自營商（TWT43U 16:05 才好）
        try:
            firebase_sync.sync_proprietary()
        except Exception as e:
            print(f"[sync_error] label={label} sync_proprietary 失敗: {e}")

    elif label == 5:
        # 17:30：處置股
        try:
            firebase_sync.sync_disposal()
        except Exception as e:
            print(f"[sync_error] label={label} sync_disposal 失敗: {e}")

    elif label == 7:
        # 21:10：大盤融資更新
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
    }
    t = texts.get(label)
    return TextSendMessage(text=t) if t else None


# ── 廣播執行 ──────────────────────────────────────────────────────────────────
def broadcast_post_inf(line_bot_api, label):
    if not is_trading_day():
        if label == 0:
            line_bot_api.broadcast(TextSendMessage(text="📢 今日週末或連假未開盤❗"))
        return

    _run_sync(label)

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