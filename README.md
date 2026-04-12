# 盤後雷達 JellyStock

台股法人盤後買賣超查詢系統，結合 LINE Bot 推播與網站即時顯示。

---

## 專案架構

```
├── linebot_test.py          # Flask 主程式（LINE Webhook + 啟動入口）
├── push_service.py          # LINE Bot 定時推播排程
├── post_Info.py             # 核心資料抓取與查詢邏輯
├── get_trading_holidays.py  # 交易日判斷
├── tools.py                 # 工具函式（民國日期轉換）
├── requirements.txt         # 套件依賴
├── stock_site/
│   ├── api_routes.py        # 網站 REST API 路由
│   └── ...
└── test.py                  # 本地測試腳本
```

---

## 檔案說明

### `linebot_test.py`
Flask 應用程式主入口，負責：
- 接收 LINE Webhook 並回覆使用者查詢
- 啟動 `push_service` 推播排程
- 掛載 `api_routes` 網站 API

**用途：LINE Bot 專用**

---

### `push_service.py`
定時廣播排程，使用 APScheduler 在指定時間推播給所有訂閱者。

| Label | 時間  | 內容 |
|-------|-------|------|
| 0     | 09:00 | 休市通知 |
| 2     | 15:00 | 投信買賣超更新通知 |
| 1     | 15:10 | 法人總買賣金額 + 大盤資訊 |
| 3     | 16:10 | 外資買賣超更新通知 |
| 4     | 16:10 | 自營商買賣超更新通知 |
| 5     | 17:30 | 處置股更新通知 |
| 6     | 17:30 | 注意股更新通知 |
| 7     | 21:10 | 大盤融資金額 + 大盤資訊 |
| 8     | 21:30 | 借券賣出更新通知 |

**用途：LINE Bot 專用**

---

### `post_Info.py`
核心資料查詢模組，提供以下函式：

| 函式 | 說明 |
|------|------|
| `get_today()` | 回傳台灣當下日期（`YYYYMMDD`） |
| `fetch_with_retry()` | 帶日期驗證的 HTTP GET，自動重試 |
| `stock_info(keyword)` | 查詢個股盤後買賣超（上市 / 上櫃） |
| `market_pnfo()` | 查詢大盤三大法人金額與融資統計 |
| `twse_top50(today)` | 查詢上市外資、投信、自營商買賣超前50名 |

資料來源：TWSE（台灣證券交易所）、TPEx（櫃買中心）

**用途：LINE Bot + 網站共用**

---

### `get_trading_holidays.py`
判斷今天是否為交易日，提供以下函式：

| 函式 | 說明 |
|------|------|
| `is_trading_day()` | 判斷今天是否為交易日，回傳 `bool` |
| `get_trading_status()` | 回傳完整交易狀態 dict，供網站 API 使用 |

`get_trading_status()` 回傳格式：
```json
{
    "is_trading_day": false,
    "today": "2026-04-12",
    "next_trading_day": "2026-04-13"
}
```

**用途：LINE Bot + 網站共用**

---

### `stock_site/api_routes.py`
Flask REST API 路由，提供網站前端呼叫：

| Endpoint | 說明 |
|----------|------|
| `GET /api/trading_status` | 今日交易日狀態與下一個交易日 |
| `GET /api/stock?keyword=2330` | 個股盤後買賣超查詢 |
| `GET /api/market` | 大盤三大法人金額與融資統計 |

**用途：網站專用**

---

### `tools.py`
工具函式。

| 函式 | 說明 |
|------|------|
| `to_minguo(date_str)` | 民國年份轉西元，用於解析 TPEx 日期格式 |

**用途：`post_Info.py` 內部使用**

---

### `test.py`
本地測試腳本，使用 `DummyLineBotApi` 模擬 LINE Bot 回覆與推播，不需要真實 Token 即可測試。

---

## 資料流

```
使用者輸入
    │
    ▼
linebot_test.py (Webhook)
    │
    ▼
post_Info.py → TWSE / TPEx API
    │
    ▼
LINE Bot 回覆

網站前端 (index.html)
    │
    ▼
api_routes.py
    │
    ├── /api/trading_status → get_trading_holidays.py
    ├── /api/stock          → post_Info.py
    └── /api/market         → post_Info.py
```

---

## 環境變數設定

| 變數名稱 | 說明 |
|----------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `PORT` | Flask 監聽埠（Render 自動注入） |

本地開發時在根目錄建立 `.env` 檔案：
```
LINE_CHANNEL_ACCESS_TOKEN=your_token_here
LINE_CHANNEL_SECRET=your_secret_here
```

---

## 本地測試

```bash
# 安裝依賴
pip install -r requirements.txt

# 執行測試腳本（不需要真實 LINE Token）
python test.py

# 啟動完整伺服器
python linebot_test.py
```

---

## 測試歷史日期資料

在 `post_Info.py` 頂部設定：
```python
TEST_DATE = "20260410"  # 測試完改回 None
```

在 `get_trading_holidays.py` 設定：
```python
TEST_DATE = date(2026, 4, 10)  # 測試完改回 None
```

並將 `stock_info()` 裡的 15:00 時間限制暫時註解掉：
```python
# elif datetime.datetime.now(ZoneInfo("Asia/Taipei")).hour < 15:
#     return f"📢 今盤後資料尚未更新❗\n請於今日 15:00 後再試一次。"
```

---

## 部署（Render）

1. 將專案推上 GitHub
2. Render 新增 Web Service，選擇該 repo
3. Start Command 設定為：`python linebot_test.py`
4. 在 Environment 填入 `LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_CHANNEL_SECRET`

---

## 資料來源

- [台灣證券交易所 TWSE](https://www.twse.com.tw)
- [櫃買中心 TPEx](https://www.tpex.org.tw)

> 本專案資料僅供參考，不構成任何投資建議。
