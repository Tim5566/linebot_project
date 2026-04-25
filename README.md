# 盤後雷達 JellyStock

台股法人盤後買賣超查詢系統，結合 LINE Bot 推播與網站即時顯示。

---

## 專案架構

```
├── linebot_test.py          # Flask 主程式（LINE Webhook + 啟動入口）
├── push_service.py          # LINE Bot 定時推播排程 + 觸發 Firebase 同步
├── post_Info.py             # 核心資料查詢邏輯（優先從 Firebase 讀取）
├── firebase_sync.py         # 盤後全量資料同步（TWSE/TPEx → Firebase）
├── get_trading_holidays.py  # 交易日判斷
├── api_routes.py            # 網站 REST API 路由
├── tools.py                 # 工具函式（民國日期轉換）
├── requirements.txt         # 套件依賴
└── stock_site/
    └── ...
```

---

## 資料流（新架構）

```
盤後排程觸發（push_service.py）
    │
    ▼
firebase_sync.py → TWSE / TPEx API（一次性全量抓取）
    │
    ▼
Firebase Realtime Database（快取全市場資料）
    │
    ├── 使用者查詢個股 → post_Info.py → Firebase 讀取（毫秒級回應）
    │
    └── 若 Firebase 無資料 → fallback 打 TWSE API（保底機制）

LINE Bot 推播（同步完成後才廣播通知）
```

**優點：**
- 使用者查詢速度大幅提升（不再即時打 TWSE API）
- 避免大量請求導致 IP 被 TWSE 封鎖
- Firebase 快取當日全市場資料，查詢無限次

---

## 檔案說明

### `linebot_test.py`
Flask 應用程式主入口，負責：
- 接收 LINE Webhook 並回覆使用者查詢
- 啟動 `push_service` 推播排程
- 掛載 `api_routes` 網站 API

---

### `push_service.py`
定時廣播排程，使用 APScheduler 在指定時間：
1. 先呼叫 `firebase_sync` 同步資料到 Firebase
2. 再廣播 LINE 通知（確保使用者收到通知時資料已就緒）

| Label | 時間  | 內容 | Firebase 同步 |
|-------|-------|------|--------------|
| 0     | 09:00 | 休市通知 | — |
| 2     | 15:00 | 投信買賣超更新通知 | — |
| 1     | 15:10 | 法人總買賣金額 + 大盤資訊 | 三大法人 + 大盤 |
| 3     | 16:10 | 外資買賣超更新通知 | — |
| 4     | 16:10 | 自營商買賣超更新通知 | — |
| 5     | 17:30 | 處置股更新通知 | 處置股 |
| 6     | 17:30 | 注意股更新通知 | — |
| 7     | 21:10 | 大盤融資金額 + 大盤資訊 | 大盤融資 |
| 8     | 21:30 | 借券賣出更新通知 | 借券賣出 |

---

### `firebase_sync.py`
盤後全量同步模組，一次把全市場資料寫入 Firebase。

| 函式 | 說明 |
|------|------|
| `sync_institutional(today)` | 同步上市 + 上櫃三大法人（外資、投信、自營商） |
| `sync_short_sale(today)` | 同步上市 + 上櫃借券賣出 |
| `sync_disposal(today)` | 同步上市 + 上櫃處置股 |
| `sync_market(today)` | 同步大盤三大法人金額 + 融資統計 |
| `sync_all(today)` | 一次執行所有同步（手動補跑用） |

**日期驗證機制：**
- 每支 API 抓到資料後驗證日期是否為今天
- 若資料還是舊的 → 等待 3 分鐘後重試，最多 5 次
- 超過次數仍是舊資料 → 不寫入 Firebase，保留舊資料
- 使用者查詢時自動 fallback 打 TWSE API，不會顯示錯誤資料

**Firebase 資料結構：**
```
stock_data/
  {YYYYMMDD}/
    twse/
      {stock_id}: {name, foreign, trust, proprietary, short_sale, disposal}
    otc/
      {stock_id}: {name, foreign, trust, proprietary, short_sale, disposal}
    market/
      {外資, 投信, 自營商, 合計金額, 融資金額增減, 融資額金水位}
    meta/
      {institutional_updated, disposal_updated, market_updated, short_sale_updated}
visitors/
  daily/
    {YYYY-MM-DD}: count
  total: count
```

---

### `post_Info.py`
核心資料查詢模組，查詢流程：

```
stock_info(keyword)
    │
    ├── 1. 檢查是否交易日、時間是否 ≥ 15:00
    │
    ├── 2. 查記憶體快取（當日同一 keyword 不重複查）
    │
    ├── 3. 查 Firebase stock_data/{today}/{market}/{stock_id}
    │       └── 有資料 → 直接回傳 ✅
    │
    └── 4. Firebase 無資料 → fallback 打 TWSE/TPEx API（保底）
```

| 函式 | 說明 |
|------|------|
| `stock_info(keyword)` | 查詢個股盤後買賣超（優先 Firebase） |
| `market_pnfo()` | 查詢大盤資訊（優先 Firebase） |
| `twse_top50(today)` | 上市三大法人買賣超前50（直接打 API） |
| `otc_top50()` | 上櫃三大法人買賣超前50（直接打 API） |

---

### `get_trading_holidays.py`
判斷今天是否為交易日。

| 函式 | 說明 |
|------|------|
| `is_trading_day()` | 判斷今天是否為交易日，回傳 `bool` |
| `get_trading_status()` | 回傳完整交易狀態 dict |

`get_trading_status()` 回傳格式：
```json
{
    "is_trading_day": false,
    "today": "2026-04-25",
    "next_trading_day": "2026-04-28"
}
```

---

### `api_routes.py`
Flask REST API 路由。

| Endpoint | 方法 | 說明 |
|----------|------|------|
| `GET /api/trading_status` | GET | 今日交易日狀態 |
| `GET /api/stock?keyword=2330` | GET | 個股盤後買賣超查詢 |
| `GET /api/market` | GET | 大盤三大法人金額與融資統計 |
| `GET /api/top50` | GET | 上市三大法人買賣超前50 |
| `GET /api/otc_top50` | GET | 上櫃三大法人買賣超前50 |
| `POST /api/visitor` | POST | 訪客統計（寫入 Firebase） |
| `GET /api/sync_test` | GET | 手動觸發 Firebase 同步（測試用） |

**`/api/sync_test` 使用方式：**
```
GET /api/sync_test?date=20260424&token=你的SYNC_SECRET
```
需帶正確 token 才能執行，防止未授權觸發。
同步在背景執行，立刻回傳結果，請看 Render Log 確認進度。

---

### `tools.py`

| 函式 | 說明 |
|------|------|
| `to_minguo(date_str)` | 民國年份轉西元，用於解析 TPEx 日期格式 |

---

## 環境變數設定

| 變數名稱 | 說明 |
|----------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `FIREBASE_DATABASE_URL` | Firebase Realtime Database URL |
| `FIREBASE_CREDENTIAL_PATH` | Firebase 憑證 JSON 路徑 |
| `SYNC_SECRET` | 手動觸發同步的驗證密碼（/api/sync_test 用） |
| `SUPABASE_URL` | Supabase URL（訪客統計，舊版保留） |
| `SUPABASE_KEY` | Supabase Key（訪客統計，舊版保留） |
| `PORT` | Flask 監聽埠（Render 自動注入） |

本地開發在根目錄建立 `.env`：
```
LINE_CHANNEL_ACCESS_TOKEN=your_token_here
LINE_CHANNEL_SECRET=your_secret_here
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.asia-southeast1.firebasedatabase.app
FIREBASE_CREDENTIAL_PATH=firebase_credentials.json
SYNC_SECRET=your_secret_here
```

> ⚠️ `firebase_credentials.json` 請加入 `.gitignore`，不可上傳至 GitHub。
> Render 上請使用 Secret Files 功能上傳憑證檔。

---

## 本地測試

```bash
# 安裝依賴
pip install -r requirements.txt

# 手動測試 Firebase 同步（指定日期）
python -c "from firebase_sync import sync_all; sync_all('20260424')"

# 啟動完整伺服器
python linebot_test.py
```

---

## 部署（Render）

1. 將專案推上 GitHub
2. Render 新增 Web Service，選擇該 repo
3. Start Command：`python linebot_test.py`
4. Environment 填入所有環境變數
5. Secret Files 上傳 `firebase_credentials.json`，路徑設為 `/etc/secrets/firebase_credentials.json`

---

## 資料來源

- [台灣證券交易所 TWSE](https://www.twse.com.tw)
- [櫃買中心 TPEx](https://www.tpex.org.tw)

> 本專案資料僅供參考，不構成任何投資建議。