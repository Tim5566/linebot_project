# test_linebot_dummy.py
from linebot.models import TextSendMessage

# 匯入你原本的 handle_message 函式
from linebot_test import handle_message

# 建立一個模擬的 event 物件
class DummyEvent:
    def __init__(self, text):
        self.message = type('Msg', (), {'text': text})()  # 只需要 text 屬性
        self.reply_token = "dummy_token"

# 模擬 line_bot_api.reply_message，不會真的傳送訊息，只印出回覆內容
class DummyLineBotApi:
    def reply_message(self, reply_token, message):
        if isinstance(message, TextSendMessage):
            print(f"[Bot 回覆] {message.text}")

# 替換 linebot_test 裡的 line_bot_api 為 Dummy
import linebot_test
linebot_test.line_bot_api = DummyLineBotApi()

# 測試訊息
test_messages = ["台積電", "仁寶"]

for msg in test_messages:
    print(f"[模擬使用者] {msg}")
    dummy_event = DummyEvent(msg)
    handle_message(dummy_event)
    print("------")
