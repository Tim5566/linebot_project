from dotenv import load_dotenv
load_dotenv()  # ✅ 第一件事就載入，之後所有 import 都能讀到環境變數

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler  # 使用舊版 API，避免 v3 ImportError
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

from push_service import start_scheduler
from post_Info import stock_info
from api_routes import register_api

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

register_api(app)  # 建立網站

# ✅ 修正：移到模組層級，gunicorn 啟動時也會執行排程
# 原本放在 if __name__ == "__main__" 裡，gunicorn 不會跑到
start_scheduler(line_bot_api)


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