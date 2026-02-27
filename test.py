# test_linebot_dummy.py
from linebot.models import TextSendMessage
import linebot_test
from push_service import broadcast_post_inf
from post_Info import stock_info, market_pnfo

import time

# 建立一個模擬的 event 物件
class DummyEvent:
    def __init__(self, text):
        self.message = type('Msg', (), {'text': text})()
        self.reply_token = "dummy_token"

# 模擬 line_bot_api（回覆 + 推播）
class DummyLineBotApi:
    def reply_message(self, reply_token, message):
        if isinstance(message, TextSendMessage):
            print(f"[Bot 回覆] {message.text}")

    def broadcast(self, message):
        if isinstance(message, TextSendMessage):
            print(f"[Bot 推播] {message.text}")

# 替換 linebot_test 裡的 line_bot_api 為 Dummy
linebot_test.line_bot_api = DummyLineBotApi()

start = time.perf_counter()

# 測試回覆功能
test_messages = ["泰茂"]
for msg in test_messages:
    print(f"[模擬使用者] {msg}")
    dummy_event = DummyEvent(msg)
    linebot_test.handle_message(dummy_event)
    print("------")

end = time.perf_counter() 
print(f"執行時間：{end - start:.2f} 秒")

"""
# 測試推播功能（直接呼叫副程式）
print("[測試推播] 開始")
broadcast_post_inf(linebot_test.line_bot_api, 0)
broadcast_post_inf(linebot_test.line_bot_api, 1)
broadcast_post_inf(linebot_test.line_bot_api, 2)
broadcast_post_inf(linebot_test.line_bot_api, 3)
broadcast_post_inf(linebot_test.line_bot_api, 4)
broadcast_post_inf(linebot_test.line_bot_api, 5)
broadcast_post_inf(linebot_test.line_bot_api, 6)
print("[測試推播] 結束")
"""


#測試大盤總資訊
print("[測試大盤資訊]")
print(market_pnfo())





