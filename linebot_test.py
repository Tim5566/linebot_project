from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = Flask(__name__)

# 使用 Render 環境變數設定 Token 與 Secret
LINE_CHANNEL_ACCESS_TOKEN = 'H7QtaS6lbI5Pn8LcT3ZjcvMtgSUisFKarj+4gYUdzIb3kQ+LQrveZfm38UqRO7lq+N5/JSVIGEgsOAi1eJVOpVE4CrLMJdScGUBWpEhMrTe5WjsjLO66+RGLPtzygG4hIKLfMRAdiKnNWtOUJtW0ngdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '0f27654b82ca9f667ac6c8eb37dc0a07'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 簡單首頁測試
@app.route("/")
def home():
    return "LINE Bot Server 運行中！"

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
    user_text = event.message.text
    reply_text = f"你剛剛說：{user_text}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    # 使用 Render 提供的 PORT，並允許外部訪問
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
