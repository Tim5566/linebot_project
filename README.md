# 盤後雷達 JellyStock 📊

台股法人盤後買賣超查詢系統，結合 LINE Bot 推播與網站即時顯示。

---

## 目錄

- [專案簡介](#專案簡介)
- [系統架構](#系統架構)
- [資料流說明](#資料流說明)
- [檔案說明](#檔案說明)
- [Firebase 資料結構](#firebase-資料結構)
- [環境變數設定](#環境變數設定)
- [本地開發](#本地開發)
- [部署到 Render](#部署到-render)
- [手動補跑資料](#手動補跑資料)
- [資料來源](#資料來源)

---

## 專案簡介

使用者可以透過：
- **LINE Bot**：傳股票代碼或名稱（例如 `2330` 或 `台積電`）查詢今日盤後三大法人買賣超
- **網站**：即時搜尋個股、瀏覽大盤資訊、查看三大法人買賣超前 50 名

系統在每個交易日盤後，自動從 TWSE / TPEx 抓取全市場資料並存入 **Firebase**，使用者查詢時直接從 Firebase 讀取，速度快且不會打爆 TWSE API。

---

## 系統架構

```
linebot_test.py         → Flask 主程式（LINE Webhook + 網站 API）
push_service.py         → 每日盤後定時排程（觸發同步 + 廣播推播）
firebase_sync.py        → 全量資料同步（TWSE/TPEx → Firebase）
post_Info.py            → 個股查詢邏輯（優先讀 Firebase，無資料才打 API）
api_routes.py           → 網站 REST API 路由
get_trading_holidays.py → 交易日判斷
tools.py                → 工具函式
```

---

## 資料流說明

### 正常盤後流程

```
每日 15:10（APScheduler 排程觸發）
        │
        ▼
firebase_sync.py
  └─ 從 TWSE / TPEx 一次抓取全市場資料
  └─ 驗證資料日期是否為今天（防止抓到舊資料）
  └─ 寫入 Firebase Realtime Database
        │
        ▼
push_service.py 廣播 LINE 推播通知
        │
        ▼
使用者收到通知，傳股票代碼給 LINE Bot
        │
        ▼
post_Info.py
  └─ 先查 Firebase（毫秒級回應）✅
  └─ Firebase 無資料 → fallback 打 TWSE API（保底）
```

### 為什麼要先存 Firebase？

| 舊架構 | 新架構 |
|--------|--------|
| 每次查詢都打 TWSE API | 盤後只打一次 TWSE API |
| 速度慢（每次 3～10 秒） | 速度快（從 Firebase 讀，毫秒級） |
| 多人同時查 → 容易被 TWSE 封鎖 | 無此風險 |

---

## 檔案說明

---

### `linebot_test.py` — Flask 主程式

專案的啟動入口，負責三件事：

1. 接收 LINE Webhook，把使用者訊息丟給 `post_Info.stock_info()` 處理後回覆
2. 呼叫 `push_service.start_scheduler()` 啟動定時排程
3. 呼叫 `api_routes.register_api()` 掛載網站 API

---

### `push_service.py` — 定時推播排程

使用 **APScheduler** 每天在指定時間觸發，流程是：
**先同步 Firebase → 再廣播 LINE 通知**（確保使用者收到通知時資料已就緒）

| Label | 時間  | 廣播內容 | 同步動作 |
|-------|-------|---------|---------|
| 0 | 09:00 | 休市通知（週末 / 連假） | 無 |
| 2 | 15:00 | 投信買賣超已更新 | 無 |
| 1 | 15:10 | 法人總買賣金額 + 大盤資訊 | ✅ 三大法人 + 大盤 |
| 3 | 16:10 | 外資買賣超已更新 | 無 |
| 4 | 16:10 | 自營商買賣超已更新 | 無 |
| 5 | 17:30 | 處置股已更新 | ✅ 處置股 |
| 6 | 17:30 | 注意股已更新 | 無 |
| 7 | 21:10 | 大盤融資金額 + 大盤資訊 | ✅ 大盤融資 |
| 8 | 21:30 | 借券賣出已更新 | ✅ 借券賣出 |

> 休市日（週末 / 連假）只有 09:00 發休市通知，其餘排程不執行、不同步。

---

### `firebase_sync.py` — 全量資料同步

負責從 TWSE / TPEx 抓取全市場資料並寫入 Firebase。

**公開函式：**

| 函式 | 觸發時間 | 說明 |
|------|---------|------|
| `sync_institutional(today)` | 15:10 | 同步上市 + 上櫃三大法人（外資、投信、自營商） |
| `sync_disposal(today)` | 17:30 | 同步上市 + 上櫃處置股 |
| `sync_market(today)` | 15:10 / 21:10 | 同步大盤三大法人金額 + 融資統計 |
| `sync_short_sale(today)` | 21:30 | 同步上市 + 上櫃借券賣出 |
| `sync_all(today)` | 手動 | 一次執行所有同步（補跑用） |

**日期驗證 + 重試機制：**

TWSE 有時候盤後資料不會立刻更新，為了防止把舊資料寫進 Firebase：

```
抓到資料
  ├── 驗證日期是否為今天？
  │     ├── ✅ 是 → 寫入 Firebase
  │     └── ❌ 否 → 等待 3 分鐘後重試
  │               └── 最多重試 5 次（共等 15 分鐘）
  │                     └── 還是舊資料 → 放棄寫入 ⚠️
  │                           └── 使用者查詢時自動 fallback 打 TWSE API
```

**Render Log 觀察重點：**
```
[上市外資] 第1次日期正確 ✅           → 正常
[上市外資] 第1次資料日期=...，尚未更新  → 資料還沒好，等待重試中
[firebase] 寫入 stock_data/...       → 寫入 Firebase 成功
[sync_all] 全部完成 date=20260428    → 全部同步完成
```

---

### `post_Info.py` — 個股查詢邏輯

個股查詢的核心模組，查詢流程：

```
使用者輸入 keyword（股票代碼或名稱）
        │
        ├─ 1. 今天是交易日嗎？時間 ≥ 15:00 嗎？
        │       └── 否 → 回傳提示訊息
        │
        ├─ 2. 記憶體快取有資料嗎？（當日同 keyword 不重複查）
        │       └── 有 → 直接回傳
        │
        ├─ 3. 查 Firebase stock_data/{today}/{twse or otc}/{stock_id}
        │       └── 有資料 → 回傳 ✅（毫秒級）
        │
        └─ 4. Firebase 無資料 → fallback 打 TWSE / TPEx API（保底）
```

**公開函式：**

| 函式 | 說明 |
|------|------|
| `stock_info(keyword)` | 查詢個股盤後買賣超，回傳格式化文字 |
| `market_pnfo()` | 查詢大盤三大法人金額 + 融資統計 |
| `twse_top50(today)` | 上市三大法人買賣超前 50 名（直接打 API） |
| `otc_top50()` | 上櫃三大法人買賣超前 50 名（直接打 API） |
| `get_today()` | 回傳台灣當下日期（`YYYYMMDD`） |

> `twse_top50` / `otc_top50` 因為要排行全市場，資料量太大不適合存 Firebase，仍直接打 API。

---

### `api_routes.py` — 網站 REST API

網站前端呼叫的所有 API 路由：

| Endpoint | 方法 | 說明 |
|----------|------|------|
| `/api/trading_status` | GET | 今日是否為交易日 + 下一個交易日 |
| `/api/stock?keyword=2330` | GET | 個股盤後買賣超查詢 |
| `/api/market` | GET | 大盤三大法人金額 + 融資統計 |
| `/api/top50` | GET | 上市三大法人買賣超前 50 名 |
| `/api/otc_top50` | GET | 上櫃三大法人買賣超前 50 名 |
| `/api/visitor` | POST | 訪客統計（寫入 Firebase） |
| `/api/sync_test` | GET | 手動觸發 Firebase 同步（測試用，需帶 token） |

**`/api/sync_test` 使用方式：**
```
https://你的網址/api/sync_test?date=20260428&token=你的SYNC_SECRET
```
- 需帶正確 `token` 才能執行（對應 Render 環境變數 `SYNC_SECRET`）
- 同步在背景執行，立刻回傳 `{"status": "started"}`
- 執行進度請看 Render Log

---

### `get_trading_holidays.py` — 交易日判斷

從 TWSE 抓取當年度休市日曆，判斷今天是否為交易日。

| 函式 | 說明 |
|------|------|
| `is_trading_day()` | 今天是否為交易日，回傳 `bool` |
| `get_trading_status()` | 回傳完整交易狀態（供網站 API 使用） |

`get_trading_status()` 回傳格式：
```json
{
    "is_trading_day": false,
    "today": "2026-04-25",
    "next_trading_day": "2026-04-28"
}
```

---

### `tools.py` — 工具函式

| 函式 | 說明 |
|------|------|
| `to_minguo(date_str)` | 民國年 YYYMMDD → 西元年 YYYYMMDD（用於解析 TPEx 日期） |

---

## Firebase 資料結構

```
Firebase Realtime Database
│
├── stock_data/
│   └── {YYYYMMDD}/                ← 每個交易日一個節點
│       ├── twse/
│       │   └── {stock_id}/        ← 上市個股（例如 "2330"）
│       │       ├── name           ← 股票名稱（例如 "台積電"）
│       │       ├── foreign        ← 外資買賣超（張）
│       │       ├── trust          ← 投信買賣超（張）
│       │       ├── proprietary    ← 自營商買賣超（張）
│       │       ├── short_sale     ← 借券賣出（股，21:30 後更新）
│       │       └── disposal       ← 處置股狀態（17:30 後更新）
│       ├── otc/
│       │   └── {stock_id}/        ← 上櫃個股（結構同上）
│       ├── market/
│       │   ├── 外資及陸資          ← 大盤外資淨買超金額（億）
│       │   ├── 投信                ← 大盤投信淨買超金額（億）
│       │   ├── 自營商              ← 大盤自營商淨買超金額（億）
│       │   ├── 合計金額            ← 三大法人合計（億）
│       │   ├── 融資金額增減        ← 當日融資增減（億）
│       │   └── 融資額金水位        ← 融資總水位（億）
│       └── meta/
│           ├── institutional_updated  ← 三大法人同步時間
│           ├── disposal_updated       ← 處置股同步時間
│           ├── market_updated         ← 大盤同步時間
│           ├── short_sale_updated     ← 借券同步時間
│           ├── twse_count             ← 上市同步筆數
│           └── otc_count              ← 上櫃同步筆數
│
└── visitors/
    ├── daily/
    │   └── {YYYY-MM-DD}: count    ← 每日訪客數
    └── total: count               ← 累積總訪客數
```

---

## 環境變數設定

| 變數名稱 | 說明 | 必要 |
|----------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token | ✅ |
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret | ✅ |
| `FIREBASE_DATABASE_URL` | Firebase Realtime Database URL | ✅ |
| `FIREBASE_CREDENTIAL_PATH` | Firebase 憑證 JSON 路徑 | ✅ |
| `SYNC_SECRET` | 手動觸發同步的驗證密碼 | ✅ |
| `SUPABASE_URL` | Supabase URL（舊版訪客統計，保留備用） | — |
| `SUPABASE_KEY` | Supabase Key（舊版訪客統計，保留備用） | — |
| `PORT` | Flask 監聽埠（Render 自動注入） | — |

本地開發在根目錄建立 `.env`：
```
LINE_CHANNEL_ACCESS_TOKEN=your_token_here
LINE_CHANNEL_SECRET=your_secret_here
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.asia-southeast1.firebasedatabase.app
FIREBASE_CREDENTIAL_PATH=firebase_credentials.json
SYNC_SECRET=your_secret_here
```

> ⚠️ `firebase_credentials.json` 已加入 `.gitignore`，絕對不可上傳至 GitHub！
> Render 上請使用 **Secret Files** 功能上傳憑證檔。

---

## 本地開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 手動測試 Firebase 同步（指定日期）
python -c "from firebase_sync import sync_all; sync_all('20260424')"

# 啟動完整伺服器（LINE Bot + 網站）
python linebot_test.py
```

**注意事項：**
- Python 版本需 3.9+
- 若使用 Python 3.9，確認 `post_Info.py` 第一行有 `from __future__ import annotations`
- `.env` 需設定好 Firebase 相關變數，否則 Firebase 寫入會失敗

---

## 部署到 Render

**首次部署步驟：**

1. 將專案推上 GitHub
2. Render → New Web Service → 選擇 repo
3. Start Command 設定：`python linebot_test.py`
4. Environment 填入所有環境變數（見上方表格）
5. Secret Files 上傳 `firebase_credentials.json`
   - Filename：`firebase_credentials.json`
   - 上傳後 `FIREBASE_CREDENTIAL_PATH` 設定為：`/etc/secrets/firebase_credentials.json`
6. 部署完成後看 Log 確認：
   ```
   ✅ Firebase 初始化成功
   ✅ 代碼清單：上市 XXXX 筆，上櫃 XXXX 筆
   ```

**盤後觀察 Render Log 重點：**
```
15:10 → [sync] 開始同步三大法人
        [twse_inst] 共 XXXX 筆 ✅
        [otc_inst] 共 XXXX 筆 ✅
        [firebase] 寫入 stock_data/... ✅
        [sync] 大盤同步完成 ✅
```

---

## 手動補跑資料

若某天排程失敗或資料漏同步，可用以下方式手動補跑：

**方式一：瀏覽器打開（在 Render 上執行）**
```
https://你的網址/api/sync_test?date=20260428&token=你的SYNC_SECRET
```

**方式二：本機執行**
```bash
python -c "from firebase_sync import sync_all; sync_all('20260428')"
```

---

## Firebase 安全規則

目前設定（測試階段，允許所有寫入）：
```json
{
  "rules": {
    ".read": false,
    ".write": true
  }
}
```

---

## 資料來源

- [台灣證券交易所 TWSE](https://www.twse.com.tw)
- [櫃買中心 TPEx](https://www.tpex.org.tw)

> 本專案資料僅供參考，不構成任何投資建議。
