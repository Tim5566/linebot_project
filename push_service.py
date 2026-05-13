"""
push_service.py（Firebase 同步版）
────────────────────────────────────────────────────────────────────────────
修正重點：
  1. 各排程時間點依 label 呼叫 /api/sync_test?label=N，只跑對應任務
  2. sync_all 依 label 精確執行，不再用時間範圍判斷，避免重疊與多餘呼叫
  3. 廣播簡化：
     - 15:00 發送今日盤後更新時間表
     - 15:10 發送法人總買賣金額更新提示 + 大盤數據（同一則）
     - 21:10 發送大盤融資金額更新提示 + 數據（同一則）
  4. is_trading_day() 加 try/except，API 失敗時預設繼續執行，不讓排程崩潰
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
#   2  = 15:00 廣播更新時間表      → sync: 投信 (TWSE)
#   1  = 15:10 廣播法人總買賣金額  → sync: 大盤法人
#   9  = 15:30 OTC 三大法人        → sync: OTC 三大法人
#   3  = 16:10 外資、自營商        → sync: 重跑 TWSE 三大法人（補外資+自營商）
#   7  = 21:10 廣播大盤融資金額    → sync: 大盤融資
#   8  = 21:30 借券賣出            → sync: 借券賣出 TWSE + OTC
SCHEDULE = [
    (0, 9,  0,  "休市通知"),
    (2, 15, 0,  "投信買賣超 (TWSE)"),
    (1, 15, 10, "法人總買賣金額 (TWSE)"),
    (9, 15, 30, "三大法人 (OTC)"),
    (3, 16, 10, "外資、自營商 (TWSE)"),
    (7, 21, 10, "大盤融資金額 (TWSE)"),
    (8, 21, 30, "借券賣出 (TWSE、OTC)"),
]

# ── 代碼清單每週日同步（不廣播，背景執行）─────────────────────────────────
def _sync_stock_list_weekly():
    """每週日 08:00 更新 Firebase 代碼清單（stock_list/twse + otc）"""
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    token    = os.environ.get("SYNC_SECRET", "")

    if not base_url or not token:
        # 直接 import 跑（不透過 HTTP）
        try:
            import firebase_sync
            firebase_sync.sync_stock_list()
            print("[stock_list_weekly] 直接執行完成 ✅")
        except Exception as e:
            print(f"[stock_list_weekly] 執行失敗: {e}")
        return

    url = f"{base_url}/api/sync_stock_list?token={token}"
    print(f"[stock_list_weekly] 呼叫: {url}")
    try:
        res = requests.get(url, timeout=30)
        print(f"[stock_list_weekly] 回應: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[stock_list_weekly] 失敗: {e}")


# ── 今日盤後更新時間表（15:00 廣播）─────────────────────────────────────────
SCHEDULE_MESSAGE = """📋 今日盤後更新時間表
─────────────────
15:00 投信買賣超 (TWSE)
15:30 三大法人買賣超 (OTC)
16:10 外資、自營商 (TWSE)
21:30 借券賣出 (TWSE、OTC)
─────────────────
以上資料更新後可至機器人查詢個股"""


# ── 自動呼叫 sync_test API ────────────────────────────────────────────────────
def _call_sync_test(label: int):
    """
    呼叫 /api/sync_test?label=N，讓 sync_all 只跑該 label 對應的任務。
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

    url = f"{base_url}/api/sync_test?date={today}&label={label}&token={token}"
    print(f"[sync_test] 自動觸發 label={label}: {url}")

    try:
        res = requests.get(url, timeout=30)
        print(f"[sync_test] 回應: {res.status_code} {res.text}")
    except Exception as e:
        print(f"[sync_test] 呼叫失敗: {e}")


# ── Firebase 同步任務（各時段觸發）──────────────────────────────────────────
def _run_sync(label: int):
    if label == 0:
        return  # 休市通知，不需要同步

    # 依 label 傳入，讓 sync_all 只跑對應任務
    _call_sync_test(label)


# ── 廣播執行 ──────────────────────────────────────────────────────────────────
def broadcast_post_inf(line_bot_api, label):
    # ✅ 修正：is_trading_day() 加 try/except，API 失敗時預設繼續執行，不讓排程崩潰
    try:
        trading = is_trading_day()
    except Exception as e:
        print(f"[trading_day] 判斷失敗，預設為交易日繼續執行: {e}")
        trading = True

    if not trading:
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
            text="📢 今盤後，法人總買賣金額已更新❗\n\n" + market_pnfo()
        ))

    elif label == 7:
        # 21:10 廣播大盤融資金額更新提示 + 數據（同一則）
        line_bot_api.broadcast(TextSendMessage(
            text="📢 今盤後，大盤融資金額已更新❗\n\n" + market_pnfo()
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

    # ── 每週日 08:00 更新代碼清單（stock_list/twse + otc）────────────────────
    # 平常只有新公司上市才會差異，每週補一次即可
    scheduler.add_job(
        _sync_stock_list_weekly,
        'cron',
        day_of_week='sun',
        hour=8, minute=0,
        timezone=taiwan,
    )

    scheduler.start()
    print("[scheduler] 排程已啟動 ✅")