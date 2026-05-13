from dotenv import load_dotenv
load_dotenv()  # ✅ 第一件事就載入，之後所有 import 都能讀到環境變數

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler  # 使用舊版 API，避免 v3 ImportError
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import threading
import time
import requests as _req

from push_service import start_scheduler
from post_Info import stock_info
from api_routes import register_api

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

register_api(app)  # 建立網站

# ✅ 啟動排程（gunicorn 也會執行）
start_scheduler(line_bot_api)


# ── 自我 ping，防止 Render 休眠（取代 UptimeRobot）────────────────────────────
def _self_ping():
    """每 10 分鐘 ping 自己一次，讓 Render 不休眠。"""
    # 從環境變數讀服務網址，例如 https://your-app.onrender.com
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not base_url:
        print("[self-ping] 未設定 RENDER_EXTERNAL_URL，自我 ping 停用")
        return

    while True:
        time.sleep(10 * 60)   # 等 10 分鐘
        try:
            resp = _req.get(f"{base_url}/ping", timeout=10)
            print(f"[self-ping] {resp.status_code} OK")
        except Exception as e:
            print(f"[self-ping] 失敗: {e}")

# daemon=True：主程式結束時這條 thread 自動跟著結束，不會卡住 gunicorn
_ping_thread = threading.Thread(target=_self_ping, daemon=True)
_ping_thread.start()
# ─────────────────────────────────────────────────────────────────────────────


# 保活用的 ping 路由
@app.route("/ping")
def ping():
    return "pong", 200


# Webhook 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    reply_text = stock_info(user_text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)