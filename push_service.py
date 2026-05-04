"""
push_service.py（Firebase 同步版）
────────────────────────────────────────────────────────────────────────────
修正重點：
  1. 所有排程時間點（除了 label=0 休市通知）都自動呼叫 /api/sync_test
     → 確保每個時段資料更新後都能完整寫入 Firebase
  2. 同時段的 label 合併為一個，避免重複呼叫 sync_test
     → 16:10 外資+自營商合併、17:30 處置股+注意股合併
  3. 廣播簡化：
     - 15:00 發送今日盤後更新時間表
     - 15:10 發送法人總買賣金額更新提示 + 大盤數據（同一則）
     - 21:10 發送大盤融資金額更新提示 + 數據（同一則）
  4. 其他時段只做背景同步，不廣播
────────────────────────────────────────────────────────────────────────────
"""

from apscheduler.schedulers.background import BackgroundScheduler
from linebot.models import TextSendMessage
from post_Info import market_pnfo
from get_trading_holidays import is_trading_day
import pytz
import os
import requests
import datetime
from zoneinfo import ZoneInfo

# ── 排程設定 ──────────────────────────────────────────────────────────────────
# label 說明：
#   0  = 09:00 休市通知
#   2  = 15:00 廣播更新時間表
#   1  = 15:10 廣播法人總買賣金額 + 大盤數據
#   9  = 15:30 OTC 三大法人（背景同步，不廣播）
#   3  = 16:10 外資、自營商（背景同步，不廣播）
#   5  = 17:30 處置股、注意股（背景同步，不廣播）
#   7  = 21:10 廣播大盤融資金額數據
#   8  = 21:30 借券賣出（背景同步，不廣播）
SCHEDULE = [
    (0, 9,  0,  "休市通知"),
    (2, 15, 0,  "投信買賣超 (TWSE)"),
    (1, 15, 10, "法人總買賣金額 (TWSE)"),
    (9, 15, 30, "三大法人 (OTC)"),
    (3, 16, 10, "外資、自營商 (TWSE)"),
    (5, 17, 30, "處置股、注意股 (TWSE、OTC)"),
    (7, 21, 10, "大盤融資金額 (TWSE)"),
    (8, 21, 30, "借券賣出 (TWSE、OTC)"),
]

# ── 今日盤後更新時間表（15:00 廣播）─────────────────────────────────────────
SCHEDULE_MESSAGE = """📋 今日盤後更新時間表
─────────────────
15:00 投信買賣超 (TWSE)
15:30 三大法人買賣超 (OTC)
16:10 外資、自營商 (TWSE)
17:30 處置股 (TWSE、OTC)
21:30 借券賣出 (TWSE、OTC)
─────────────────
以上資料更新後可至機器人查詢個股"""


# ── 自動呼叫 sync_test API ────────────────────────────────────────────────────
def _call_sync_test():
    """
    直接呼叫自己的 /api/sync_test，與手動觸發完全相同。
    需要在 Render 環境變數設定：
      RENDER_EXTERNAL_URL = https://linebot-project-oxnw.onrender.com
      SYNC_SECRET = 你設定的 token
    """
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    token    = os.environ.get("SYNC_SECRET", "")
    today    = datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")

    if not base_url or not token:
        print("[sync_test] ⚠️ 缺少 RENDER_EXTERNAL_URL 或 SYNC_SECRET 環境變數，跳過")
        return

    url = f"{base_url}/api/sync_test?date={today}&token={token}"
    print(f"[sync_test] 自動觸發: {url}")

    try:
        res = requests.get(url, timeout=30)
        print(f"[sync_test] 回應: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[sync_test] 呼叫失敗: {e}")


# ── Firebase 同步任務（各時段觸發）──────────────────────────────────────────
def _run_sync(label: int):
    if not is_trading_day():
        return

    if label == 0:
        return  # 休市通知，不需要同步

    # 其他所有時間點都呼叫 sync_test 全量更新
    _call_sync_test()


# ── 廣播執行 ──────────────────────────────────────────────────────────────────
def broadcast_post_inf(line_bot_api, label):
    if not is_trading_day():
        if label == 0:
            line_bot_api.broadcast(TextSendMessage(text="📢 今日週末或連假未開盤❗"))
        return

    # 先同步 Firebase
    _run_sync(label)

    if label == 2:
        # 15:00 廣播今日盤後更新時間表
        line_bot_api.broadcast(TextSendMessage(text=SCHEDULE_MESSAGE))

    elif label == 1:
        # 15:10 廣播法人總買賣金額更新提示 + 大盤數據（同一則）
        line_bot_api.broadcast(TextSendMessage(
            text="📢 今盤後，法人總買賣金額已更新❗\n" + market_pnfo()
        ))

    elif label == 7:
        # 21:10 廣播大盤融資金額更新提示 + 數據（同一則）
        line_bot_api.broadcast(TextSendMessage(
            text="📢 今盤後，大盤融資金額已更新❗\n" + market_pnfo()
        ))

    # 其他 label：背景同步，不廣播


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