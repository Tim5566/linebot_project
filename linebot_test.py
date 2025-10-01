from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler  # 使用舊版 API，避免 v3 ImportError
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import datetime
import requests
import logging
import re

# 每日推播
from push_service import broadcast_job

app = Flask(__name__)

# 使用 Render 環境變數設定 Token 與 Secret
LINE_CHANNEL_ACCESS_TOKEN = 'H7QtaS6lbI5Pn8LcT3ZjcvMtgSUisFKarj+4gYUdzIb3kQ+LQrveZfm38UqRO7lq+N5/JSVIGEgsOAi1eJVOpVE4CrLMJdScGUBWpEhMrTe5WjsjLO66+RGLPtzygG4hIKLfMRAdiKnNWtOUJtW0ngdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '0f27654b82ca9f667ac6c8eb37dc0a07'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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

    # 供查詢今日個股買賣超
    reply_text = query_investor(user_text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

# 供查詢今日個股買賣超
def query_investor(keyword):
    today = datetime.datetime.now().strftime("%Y%m%d")
    url_Foreign = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date={20250926}"
    url_Trust = f"https://www.twse.com.tw/rwd/zh/fund/TWT44U?response=json&date={20250926}"
    url_Proprietary = f"https://www.twse.com.tw/rwd/zh/fund/TWT43U?response=json&date={20250926}"

    headers = {"User-Agent": "Mozilla/5.0"}  # 模擬瀏覽器，避免被 TWSE 拒絕

    try:
        #外資
        res = requests.get(url_Foreign, headers=headers, verify=False)
        data = res.json()

        Foreign_text = None
        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]

            if re.search(r'售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword == keyword in stock_id or keyword in stock_name:
                Foreign_text = f"外資買賣超：{row[5]} 股"
                break
        
        #投信
        res = requests.get(url_Trust, headers=headers, verify=False)
        data = res.json()

        Trust_text = None
        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[1], row[2]

            if re.search(r'售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword == keyword in stock_id or keyword in stock_name:
                Trust_text = f"投信買賣超：{row[5]} 股"
                break
        
        #自營商
        res = requests.get(url_Proprietary, headers=headers, verify=False)
        data = res.json()

        Proprietary_text = None
        # data["data"] 格式: [證券代號, 證券名稱, 買進股數, 賣出股數, 買賣超股數]
        for row in data["data"]:
            stock_id, stock_name = row[0], row[1]

            if re.search(r'購|售|認購|認售', stock_name):
                continue #跳過選擇權

            if keyword == keyword in stock_id or keyword in stock_name:
                Proprietary_text = f"自營商買賣超：{row[4]} 股"
                break

        if Foreign_text or Trust_text or Proprietary_text:
            reply = f"{keyword} (今盤後)\n"

            #外資
            if Foreign_text:
                reply += Foreign_text + "\n"
            else:
                reply += "外資買賣超：暫未更新。" + "\n"

            #投信
            if Trust_text:
                reply += Trust_text + "\n"
            else:
                reply += "投信買賣超：暫未更新。" + "\n"

            #自營商
            if Proprietary_text:
                reply += Proprietary_text + "\n"
            else:
                reply += "自營商買賣超：暫未更新" + "\n"

            return reply.strip()
        else:
            return f"找不到「{keyword}」的外資或投信買賣超資料。"

    except Exception as e:
        return f"今日週休或連假未開盤"

if __name__ == "__main__":
    # 啟動推播排程
    start_scheduler(line_bot_api)

    # 使用 Render 提供的 PORT，並允許外部訪問
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
