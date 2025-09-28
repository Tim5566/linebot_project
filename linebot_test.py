from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler  # 使用舊版 API，避免 v3 ImportError
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import datetime
import requests
import logging
import re

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
    user_text = event.message.text.strip()

    # 查詢外資買賣超
    reply_text = query_foreign_investor(user_text)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

def query_foreign_investor(keyword):
    """查詢今日外資買賣超"""
    today = datetime.datetime.now().strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={20250926}"
    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕

    try:
        res = requests.get(url, headers=headers)
        data = res.json()

        if data.get("stat") != "OK" or data.get("total", 0) == 0:
            return "今天沒有交易資料，可能是休假或沒有外資交易。"

        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]

            if re.search(r'售|認購|認售', stock_name):
                continue  # 跳過選擇權

            if keyword == keyword in stock_id or keyword in stock_name:
                return f"{stock_name}\n外資買賣超：{row[5]} 股"

        return f"找不到「{keyword}」的外資買賣超資料。"

    except Exception as e:
        logging.error("查詢發生錯誤: %s", e)
        return f"查詢時發生錯誤：{e}"

if __name__ == "__main__":
    # 使用 Render 提供的 PORT，並允許外部訪問
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
