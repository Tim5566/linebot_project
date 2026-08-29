# JellyStock 專案架構文件

> 給未來接手這個專案的 AI / 工程師看的完整導覽。目的是讓你不用重新爬過所有程式碼，
> 5 分鐘內就能搞懂「這個系統長什麼樣子、資料怎麼流動、要改東西該去哪個檔案」。

---

## 1. 專案是什麼

**JellyStock（jellystockdata.com）** 是一個台股盤後資訊網站 + LINE Bot，核心功能：

- 每天盤後自動抓取台股（TWSE 上市、TPEx 上櫃）的三大法人買賣超、融資融券、借券賣出等公開資料
- 把資料寫進 Firebase Realtime Database 當快取層
- 提供網頁版查詢介面（法人買賣超排行、均線雷達、注意股/處置股查詢等工具）
- 同時提供 LINE Bot，使用者可以直接在 LINE 裡查個股資料，並在固定時段收到盤後資料更新的廣播推播
- 網站另外有 20 篇原創教學文章（技術分析 10 篇 + 籌碼分析 10 篇），做內容行銷 / SEO，目標是申請 Google AdSense 廣告營利

**目前狀態（2026/08）**：內容與後端架構已經穩定，AdSense 廣告已埋碼但尚未通過審核，正在累積 Google 搜尋流量與網站信任度。

---

## 2. 技術棧

| 分類 | 技術 |
|---|---|
| 後端框架 | Flask |
| 部署平台 | Render（免費方案，有休眠機制，用 self-ping 保活） |
| 排程 | APScheduler（`BackgroundScheduler`，時區 Asia/Taipei） |
| 資料庫 | Firebase **Realtime Database**（不是 Firestore，注意這點） |
| LINE 串接 | `line-bot-sdk`（舊版 API：`LineBotApi` / `WebhookHandler`，不是 v3 SDK） |
| 資料來源 | TWSE、TPEx（櫃買中心）官方公開 JSON API（爬蟲式定時抓取） |
| 前端 | 純 HTML/CSS/JS 靜態頁面（無框架），由 Flask 路由直接回傳檔案 |
| 廣告 | Google AdSense（審核中） |
| 依賴套件 | 見 `requirements.txt`：flask, line-bot-sdk, apscheduler, pytz, pandas, flask_cors, flask-limiter, python-dotenv, firebase-admin |

---

## 3. 目錄結構

```
專案根目錄/
├── .env                        # 環境變數（LINE token、Firebase 憑證路徑、SYNC_SECRET 等，不進版控）
├── .gitignore
├── ads.txt                     # AdSense 網站擁有權驗證檔（根目錄靜態檔）
├── api_routes.py               # 【核心】所有 Flask 路由：頁面路由 + API 路由
├── firebase_credentials.json   # Firebase 服務帳戶金鑰（機密，不進版控）
├── firebase_sync.py            # 【核心】抓取 TWSE/OTC 官方資料 → 寫入 Firebase
├── get_trading_holidays.py     # 判斷今天是否為交易日（含休市日快取）
├── index.html                  # 網站首頁（根目錄，AdSense 程式碼已埋）
├── linebot_test.py             # 【入口檔】Flask app 啟動點 + LINE webhook 處理
├── post_Info.py                # 【核心】組裝查詢結果文字（給 LINE Bot 回覆 & 網頁用）
├── Procfile                    # Render 部署啟動指令（gunicorn）
├── push_service.py             # 【核心】排程廣播邏輯（幾點該做什麼、該推播什麼）
├── README.md
├── requirements.txt
├── robots.txt                  # 爬蟲規則，指向 sitemap.xml
├── sitemap.xml                 # 30 個頁面的 SEO sitemap
├── tools.py                    # 小工具（民國年轉換等）
├── music/                      # 靜態音樂檔（網站音效用）
└── stock_site/                 # 【前端頁面】依功能分資料夾
    ├── assets/
    │   └── site.css           # 【全站共用樣式】設計 token + 共用元件，改風格改這一處
    ├── tools/                  # 資料查詢工具頁
    │   ├── twse_top100.html    # 上市法人買賣超前100
    │   ├── otc_top100.html     # 上櫃法人買賣超前100
    │   └── ma_finder.html      # 均線雷達
    ├── news/                   # 公告/警示類頁面
    │   ├── news.html           # 重大訊息
    │   ├── notice.html         # 注意股查詢
    │   └── disposal.html       # 處置股查詢
    ├── features/                # 技術分析教學（10 章）
    │   └── chapter1.html ~ chapter10.html
    ├── chips/                   # 籌碼分析教學（10 章）
    │   └── chips_chapter1.html ~ chips_chapter10.html
    └── legal/                   # 法律頁面
        ├── about.html
        ├── privacy.html
        └── disclaimer.html
```

> ⚠️ **重要對應關係**：`stock_site/` 底下的實體檔案路徑，跟 `api_routes.py` 裡定義的
> URL 路由是「一對一手動對應」的（見下方第 5 節），不是用 Flask 的 `static_folder`
> 自動掃描。**新增網頁一定要同時去 `api_routes.py` 補一條路由**，否則網頁存在但打
> 不開（404）。

---

## 4. 系統架構圖（文字版資料流）

```
┌─────────────────┐     每日排程 (APScheduler)      ┌──────────────────┐
│  TWSE / TPEx     │ ───────────────────────────────▶│ firebase_sync.py  │
│  官方公開 API     │   09:00 / 15:00 / 15:10 / 16:00  │  抓資料→清洗→寫入  │
└─────────────────┘   16:15 / 21:10 / 21:30           └────────┬─────────┘
                                                                 │ 寫入
                                                                 ▼
                                                    ┌────────────────────────┐
                                                    │ Firebase Realtime DB   │
                                                    │ stock_data/{date}/...  │
                                                    │ top100_cache/{date}/.. │
                                                    │ stock_list/twse|otc    │
                                                    └────────┬───────────────┘
                                                              │ 讀取
                        ┌─────────────────────────────────────┼───────────────┐
                        ▼                                     ▼               ▼
              ┌──────────────────┐                ┌────────────────────┐  ┌────────────┐
              │ post_Info.py     │                │  api_routes.py      │  │push_service│
              │ 組裝查詢文字      │◀───────────────│  /api/* 端點         │  │.py 廣播邏輯 │
              └────────┬─────────┘                └──────────┬──────────┘  └─────┬──────┘
                       │                                      │ 回傳 JSON          │
                       ▼                                      ▼                   ▼
              ┌──────────────────┐                ┌────────────────────┐  ┌────────────┐
              │ LINE Bot 使用者   │                │ 網頁前端(fetch)     │  │LINE 群組/好友│
              │ 傳文字查個股      │                │ twse_top100.html 等 │  │ 收到廣播訊息 │
              └──────────────────┘                └────────────────────┘  └────────────┘
```

**關鍵設計**：Firebase 是整個系統的「單一資料真相來源」。前端網頁跟 LINE Bot **都不會**
直接去打 TWSE/TPEx 的 API，而是統一從 Firebase 讀已經同步好的快取資料，只有
`firebase_sync.py` 這支排程負責跟外部官方 API 打交道。這樣設計是為了避免每個使用者
查詢都重打一次官方 API（被官方限流/擋掉的風險）。

---

## 5. 各檔案職責詳解

### 5.1 `linebot_test.py`（程式進入點）
- Flask app 建立、`.env` 載入
- 呼叫 `register_api(app)`（來自 `api_routes.py`）把所有網頁/API 路由掛上去
- 呼叫 `start_scheduler(line_bot_api)`（來自 `push_service.py`）啟動排程
- 處理 LINE webhook（`/callback`），使用者傳訊息 → 呼叫 `post_Info.py` 的 `stock_info()` → 回覆
- 有一個 **self-ping 機制**：因為 Render 免費方案閒置 15 分鐘會休眠，這裡用背景執行緒
  每 10 分鐘打自己的 `/ping` 一次，避免休眠。**如果之後換付費方案或別的平台，這段可以拿掉**

### 5.2 `api_routes.py`（1200 行，所有路由的家）
分兩種路由：

**(a) 頁面路由**：回傳 `stock_site/` 底下對應的靜態 HTML 檔案，例如：
```python
@app.route("/stock_site/tools/twse_top100.html")
def twse_top100_page():
    return send_from_directory(...)
```
共涵蓋：首頁、20 篇教學文、3 個工具頁、3 個公告頁、3 個法律頁 = 30 頁，跟 `sitemap.xml` 完全對應。

另有靜態資源路由（仿 `/images`、`/music`、`/fonts` 寫法，純檔案服務）：
```python
@app.route("/stock_site/assets/<path:filename>")
def serve_stock_assets(filename):
    return send_from_directory('stock_site/assets', filename)
```
目前只服務 `site.css`（全站共用樣式表）。

**(b) API 路由**（前端 JS 用 fetch 呼叫，回傳 JSON），主要端點：

| 路由 | 用途 |
|---|---|
| `/api/top100` | 上市法人買賣超前 100（讀 `top100_cache`） |
| `/api/otc_top100` | 上櫃法人買賣超前 100 |
| `/api/stock` | 查詢單一個股資料 |
| `/api/stock_name` | 股票代碼查名稱 |
| `/api/news` | 重大訊息 |
| `/api/notice` | 注意股清單 |
| `/api/disposal` | 處置股清單 |
| `/api/market` | 大盤總覽數據 |
| `/api/wave_data` | 均線雷達運算邏輯（最大宗，`ma_finder.html` 用） |
| `/api/trading_status` | 今天是否為交易日 |
| `/api/sync_test?label=N&token=` | **手動觸發指定 label 的同步任務**（給 `push_service.py` 內部呼叫，也可以人工測試用，需要 `SYNC_SECRET` token 驗證） |
| `/api/visitor` (POST) | 訪客紀錄（用途待確認，可能是簡易流量統計） |
| `/api/maintenance` (GET/POST) | 維護模式開關 |

檔案開頭有 `_throttled_get()` 和 `_get_stock_lock()`：對外部 API 呼叫做**節流 + 鎖**，
避免同一時間大量請求打爆 TWSE/TPEx 官方伺服器（很重要，改動這段要小心，這是避免被
官方 IP 封鎖的防護機制）。

### 5.3 `firebase_sync.py`（1106 行，資料同步引擎）
負責「向外抓資料 → 清洗 → 寫進 Firebase」，重要函式：

| 函式 | 功能 |
|---|---|
| `sync_institutional()` | 同步 TWSE 三大法人買賣超 |
| `sync_otc_institutional()` | 同步 OTC 三大法人買賣超 |
| `sync_short_sale()` | 同步借券賣出（TWSE + OTC） |
| `sync_market()` | 同步大盤總覽（融資融券水位等） |
| `sync_stock_list()` | 同步全市場股票代碼清單（**每週日跑一次**，因為只有新股上市才會變動） |
| `sync_top100()` / `_calc_top100()` | 從法人資料算出買賣超前 100 名並快取 |
| `sync_all(label=N)` | **總入口**，依 `label` 決定要跑上面哪一組任務（label 對應表見 5.4） |
| `_check_data_missing()` / `schedule_retry_if_missing()` | 資料檢查與補跑機制，避免官方 API 當天資料還沒更新時抓到空值 |

Firebase 資料庫路徑結構（Realtime DB，非 Firestore）：
```
stock_data/{YYYY-MM-DD}/twse           # 當天 TWSE 法人資料
stock_data/{YYYY-MM-DD}/otc            # 當天 OTC 法人資料
stock_data/{YYYY-MM-DD}/market         # 當天大盤總覽
stock_data/{YYYY-MM-DD}/meta           # 當天同步狀態 metadata（成功/失敗/時間戳）
top100_cache/{YYYY-MM-DD}/twse         # 當天 TWSE 買賣超前100快取
top100_cache/{YYYY-MM-DD}/otc          # 當天 OTC 買賣超前100快取
stock_list/twse/{股票代碼} = 股票名稱    # 全市場代碼對照表（上市）
stock_list/otc/{股票代碼}  = 股票名稱    # 全市場代碼對照表（上櫃）
stock_list/meta                        # 代碼清單最後更新時間
```
`cleanup_old_stock_data()` / `_cleanup_old_top100_cache()`：定期清掉太舊的歷史資料，避免資料庫無限膨脹。

### 5.4 `push_service.py`（排程與 LINE 廣播邏輯）
`SCHEDULE` 這個 list 是**整個排程系統的中樞設定**，改排程時間只需要改這裡：

| label | 時間 | 任務 | 是否廣播 |
|---|---|---|---|
| 0 | 09:00 | 休市通知檢查 | 是（僅假日） |
| 2 | 15:00 | 投信買賣超(TWSE) | 是（發時間表） |
| 1 | 15:10 | 法人總買賣金額(TWSE) | 是（發大盤數據） |
| 9 | 16:00 | 三大法人(OTC) | 否，背景同步 |
| 3 | 16:15 | 外資、自營商(TWSE) | 否，背景同步 |
| 7 | 21:10 | 大盤融資金額 | 是（發大盤數據） |
| 8 | 21:30 | 借券賣出(TWSE、OTC) | 否，背景同步 |

執行方式：`broadcast_post_inf()` 會先判斷 `is_trading_day()`（非交易日就跳過，只在
label=0 時發休市通知）→ 呼叫 `_call_sync_test(label)` 打自己的 `/api/sync_test` 端點
（用 HTTP 自己呼叫自己，而非直接 import 呼叫 `sync_all`，這樣做的好處是可以在正式環境
上直接用瀏覽器打這個網址手動補跑某個 label）→ 依 label 決定要不要對 LINE 使用者廣播。

另外每週日 08:00 有獨立排程跑 `_sync_stock_list_weekly()`。

### 5.5 `post_Info.py`（917 行，查詢結果組裝）
LINE Bot 使用者輸入關鍵字（股票代碼或名稱）→ `stock_info(keyword)` 是主入口函式，
內部邏輯大致是：
1. 先嘗試從 Firebase 當天資料組出回覆（`_build_reply_from_firebase`）
2. 如果 Firebase 沒資料（例如太早查、還沒同步），會 fallback 直接打 TWSE/OTC API
   （`_fallback_twse` / `_fallback_otc`）
3. 找不到完全符合的代碼時會做模糊搜尋（`_fallback_search`）

`market_pnfo()`：組裝大盤總覽文字（推播用）。
`twse_top100()` / `otc_top100()`：這裡也有一份 top100 邏輯，注意跟 `firebase_sync.py`
裡的 `_calc_top100()` **可能是重複邏輯的兩份實作**，如果之後要改買賣超前100的計算規則，
**兩個檔案都要記得改**，或考慮重構成共用函式。

### 5.6 `get_trading_holidays.py`
向 TWSE 官方 API 拿假日清單，判斷今天是否為交易日。有做**記憶體快取**（一天內最多打一次
TWSE，冷卻時間 1 小時），避免每次查詢都重打外部 API。`is_trading_day()` 和
`get_trading_status()` 是對外主要介面，`push_service.py` 跟前端 `/api/trading_status`
都靠這個判斷。

### 5.7 `tools.py`
單純工具函式，目前只有 `to_minguo()`（西元轉民國年），供其他檔案需要處理台灣官方
API 常用的民國年格式時使用。

---

## 6. 前端頁面說明

### 6.0 全站共用樣式 `stock_site/assets/site.css`（風格統一，改一處全站生效）
- **唯一固定風格：機構淺色**（券商研究報告風）。不做深色、不做主題切換。
- 第一層是 `:root` 設計 token（顏色 / 字體 / 圓角 / 間距 / 陰影）＋ `color-scheme: light`，
  **改風格＝改這裡一處**，30 頁同步生效。字體用檔案最上方的 `@import` 載入（Noto Serif TC
  標題 / Noto Sans TC 內文 / JetBrains Mono 數字），各頁 `<head>` 不再各自放 Google Fonts `<link>`。
- 第二層是共用元件：`header` / `footer` / `.btn-back` / `.doc-card` / `.data-table` /
  `.page-hero` / 各式提示框 / `.disclaimer` / 廣告容器 `.ad-*` / 維護遮罩 `.maint-overlay`。
- **無障礙基線**（依 web-interface-guidelines 稽核補上）：全域 `:focus-visible` 外框、
  `touch-action` / `-webkit-tap-highlight-color`、`.skip-link`、彈窗/抽屜 `overscroll-behavior:
  contain`、標題 `scroll-margin-top`；各頁 `<meta theme-color>`、主容器 `id="main-content"`、
  每頁一個 `<h1>`（首頁/工具頁用視覺隱藏）、icon-only 按鈕 `aria-label`、動態結果區
  `aria-live="polite"`、載入文字結尾 `…`。
- 各頁只在自己 `<style>` 保留「該頁真正獨有」的版面（例：`ma_finder.html` 圖表畫布、
  教學章節的一次性互動小工具），且一律引用 `site.css` 的 token，不寫死顏色。
- **歷史背景**：舊版每頁內嵌 500～8000 行 CSS、還帶一整段 `body.theme-day{}` 白天模式
  覆寫與 2～3 段主題同步 `<script>`（`jelly_global_theme` / `BroadcastChannel`）。
  已全數移除，改為單一 `site.css`。
- **導入進度**：全 30 頁已轉換（法律 3、公告 3、工具 3、首頁、技術分析教學 10、籌碼分析教學 10）。
  教學文轉換方式：固定 `<body class="theme-day">` ＋ 全站色票統一（用色相分桶把日間主題所有
  顏色收斂成 4 個語意色：機構藍 / 綠(漲跌) / 紅(錯誤) / 琥珀(提醒)＋灰階），移除星空/藍天/雲/太陽
  背景動畫，接 site.css。AdSense `<ins>` 與 SVG 圖表「日間修色」script 保留。
  `index.html` 因 CSS 龐大（4000+ 行、300+ 條 `body.theme-day` 規則），採「固定
  `<body class="theme-day">` ＋ 全域把日間主題的亮藍數值換成機構藍 ＋ 移除設定裡的
  主題切換 UI 與星空/天空 canvas」的方式轉換，頁首/頁尾/字體走 site.css。

### 6.1 首頁 `index.html`
單一長頁式儀表板，包含大盤總覽、快速導覽到各工具頁/教學文、drawer 側欄選單、
Google 帳號登入、大盤即時數據、設定彈窗（僅保留管理員維護模式開關）。
- **主題切換功能已移除**：原本設定彈窗有「太空星際／白天晴空」切換，現全站固定機構
  淺色，`setTheme()` 已改為空函式，`applyTheme()` 只負責把 inline-style 寫死的 SEO
  靜態內容改成淺色。
- **已移除**頁尾兩支非 Google AdSense 腳本：`cdn.adotone.com`（affiliates.one 聯盟行銷
  連結腳本）與 `ConverlyCustomData`（搭配的轉換追蹤）。index.html 本身沒有 AdSense
  版位程式碼（只有 gtag），與其他 29 頁不同。
- **drawer 被頁尾遮住的修正**：`.page-body` 原本 `z-index:1`，與同層的 `<footer>`（site.css
  也是 `z-index:1`）相同、且 footer 在 DOM 後方，導致捲動到底時 footer 蓋過 `position:fixed`
  的 drawer（drawer 的 `z-index:160` 被關在 `.page-body` 的堆疊環境內失效）。已把
  `.page-body` 改為 `z-index:2`，drawer / modal 一律蓋在 footer 之上。

### 6.2 資料查詢工具（`stock_site/tools/`）
- **twse_top100.html / otc_top100.html**：法人買賣超排行榜，支援外資/投信/自營商切換，
  以及「共振篩選」（找出多個法人同步買超/賣超的股票），資料來源是 `/api/top100` 或
  `/api/otc_top100`
- **ma_finder.html**：均線雷達，核心運算在後端 `/api/wave_data`

### 6.3 公告類（`stock_site/news/`）
- **news.html**：重大訊息（`/api/news`）
- **notice.html**：注意股查詢（`/api/notice`）
- **disposal.html**：處置股查詢（`/api/disposal`）

### 6.4 教學文章（`stock_site/features/` + `stock_site/chips/`）
20 篇原創教學（技術分析 10 篇 + 籌碼分析 10 篇），特色：
- 側邊欄有章節導覽（真正的 `<a href>`，SEO 友善，不是純 JS）
- 每章結尾有「下一章」按鈕（同樣是真連結）
- 每頁底部統一有免責聲明（非官方網站、僅供參考、不構成投資建議）
- 章節內有 K線示意、圓餅圖、compare-table 等圖表元件，SVG 圖表靠每頁一段「日間修色」
  `<script>` 在淺底下正常顯示（body 固定 `theme-day`，該 script 一律走淺色分支）
- **2026/08 教學文互動元件靜態化**（全 20 章）：原本每章章末的「章節小測驗」是 JS 互動
  quiz（點選項→判定對錯→顯示解析→算總分），已全部改成靜態題目：選項一律 `class="quiz-opt
  disabled"` 不可點，正解與解析收在原生 `<details class="quiz-answer">`（點「看解答與解析」
  展開）。解析文字原本存在 JS 物件（`feedbackMap` / `answers` / `feedbacks` / `advAnswers`）
  裡、爬蟲讀不到，現已寫進 HTML 內文。相關 quiz JS（`answer()` / `answerQ()` /
  `showFinalScore()` 等）已無 onclick 觸發、成為未使用的死碼（暫留，不影響頁面）；
  進度條 `updateProgress()` 已與 quiz 分數脫鉤、只跟捲動百分比。
  **Step 2（已完成，全 20 章）**：計算機 / 滑桿模擬器 / 分頁切換 / 翻牌卡 / 心理測驗 / 點選解析器 /
  canvas 畫線 等所有互動元件全部改為靜態——把原本「點了才顯示」的內容全部平鋪展開（或收進
  原生 `<details>`），計算機改成「用範例數字的計算表」，canvas 畫線改成靜態練習圖 + `<details>` 解答，
  並移除對應 JS 與 JS 填充的空容器。各章 JS 都通過 `node --check` 語法檢查，無殘留 onclick/oninput。
  部分未觸發的舊 quiz JS（`answer()` / `feedbackMap` / 隱藏的 `#finalScore` 計分卡）暫留，不影響畫面。
  - 全 20 章測驗樣式已用**實色**統一並置於最後一個 `<style>`：`.quiz-section`（技ch2/7/10）為白卡＋
    標題列，內層題目淡藍底內縮卡；獨立 `.quiz-block` / `.quiz-wrap` 為白卡。`.compare-table` 也補上
    統一字級規則。題號分母已校正（技ch2/3/4/6）。
  - 技ch1 台灣50 圓餅圖：11 扇形改為各自不同顏色、移除 hover。
  - 技ch2 SEC6 常見型態 12 張卡補上 SVG K棒示意圖；`.pattern-badge` 加 `flex-shrink:0` 修正跑版。
  - 技ch4 SEC6「角色轉換示意圖」重畫（原折線 x 座標來回、自我交叉）。
- **捲動淡入效果已移除**：`.reveal` / `.section-card.reveal` 原本 `opacity:0` 靠 JS
  捲動才顯示，已改為一律 `opacity:1`（避免 JS 失敗時內文空白，對 SEO 較安全）。
  `revealObserver` 仍在但已是 no-op。
- **章節側邊導覽 `.chapter-sidenav`** 全 20 章統一：原本 `top:50%` 垂直置中，螢幕較矮時
  上緣會被 sticky 進度條蓋住，已改為 `top:104px` 起、`max-height:calc(100vh - 128px)`
  可捲動。
- JELLY 說 / JELLY 提醒 提示框（`.jelly-tip-bubble`）白天模式的內層白底已改為透明
  （只留外層 `.jelly-tip` 淡藍框），並隱藏 `::before` 小箭頭。
- **目前已移除**所有第三方聯盟廣告（原本有船井 funaicare 聯盟行銷）與第三方廣告聯播網
  （原本有 revolthem.com；2026/08 又清掉 index.html 的 adotone / affiliates.one 聯盟腳本），
  全站現在只保留 Google AdSense 一種廣告系統（審核通過前以 HTML 註解關閉，等審核過再手動打開）

### 6.5 法律頁面（`stock_site/legal/`）
about.html（關於本站）、privacy.html（隱私政策）、disclaimer.html（免責聲明），
AdSense 審查必備的三頁，內容已確認齊全。

---

## 7. 部署與環境變數

**部署平台**：Render，用 `Procfile` 定義啟動指令（gunicorn 跑 `linebot_test.py` 的 `app`）。

**必要環境變數（`.env`，不進版控）**：
```
LINE_CHANNEL_ACCESS_TOKEN=   # LINE Bot 存取權杖
LINE_CHANNEL_SECRET=          # LINE Bot 密鑰
RENDER_EXTERNAL_URL=          # 自己的正式網址（self-ping 和 sync_test 內部呼叫都要用）
SYNC_SECRET=                  # /api/sync_test 等內部端點的驗證 token
```
另外還需要 `firebase_credentials.json`（Firebase 服務帳戶金鑰檔，機密檔案）。

**Render 免費方案限制**：閒置 15 分鐘會休眠，目前用 `linebot_test.py` 裡的自我 ping
機制（每 10 分鐘打一次 `/ping`）保持喚醒。如果流量成長到需要穩定性更高的方案，
可以考慮升級付費方案並移除這段 self-ping 邏輯。

---

## 8. SEO / AdSense 現況（截至 2026/08）

- **ads.txt**：已設定於根目錄，內容 `google.com, pub-8975741363002226, DIRECT, f08c47fec0942fa0`
- **AdSense 程式碼片段**：已埋在 29 個頁面的 `<head>`（**index.html 沒有**，只有 gtag）
- **robots.txt / sitemap.xml**：設定正確，30 個頁面都在 sitemap 中
- **Google Search Console**：已驗證，近 3 個月自然搜尋點擊 240 次且持續成長，
  已索引頁面 30 頁
- **GA4**：已安裝（2026/08/23 起才開始追蹤，之前沒有數據）
- **廣告聯播網清理**：已移除全部第三方聯盟廣告（funaicare、adotone / affiliates.one）與
  廣告聯播網（revolthem），現在全站僅有 Google AdSense 一種廣告系統
- **全站視覺**：2026/08 統一成單一「機構淺色」風格（見第 6.0 節）。原本的「太空星際／
  白天晴空」主題切換已移除，`notice.html` 的獨立日間模式也併入 site.css。
- **視覺統一收尾清理**（2026/08）：移除 `index.html` 中已無 DOM 對應的星空／藍天／山脈
  canvas CSS 與三段動畫 `<script>`（`initGalaxy` 等，共約 1600 行）；移除全 20 個教學章節
  `<style>` 內沒有 DOM 對應的死規則（`.bg-nebula` / `.bg-scanlines` / `.bg-stars` /
  `@keyframes nebulaFloat` / `starTwinkle`）；移除頁首 `header::after` 的 `headerSweep`
  掃光動畫宣告與 `@keyframes`（細線本身保留，改為靜態）。
- **AdSense 審核歷史**：第一次送審時（網站剛架好不久）被判定「低品質/低價值內容」，
  推測主因是網站太新、索引量與自然流量都接近零，導致系統無法判斷網站可信度，
  而非內容品質問題。目前正在累積流量與索引時間，計畫流量與索引穩定成長一段時間後
  再次送審。

---

## 9. 已知需要注意 / 可以改善的地方（給接手者的提醒）

1. **top100 計算邏輯疑似有兩份**：`firebase_sync.py` 的 `_calc_top100()` 和
   `post_Info.py` 的 `twse_top100()` / `otc_top100()`，功能上看起來重疊，建議未來
   重構成共用模組，避免改一邊忘記改另一邊造成資料不一致。
2. **頁面路由是手動一條條寫在 `api_routes.py`**，沒有用動態路由或自動掃描資料夾。
   新增網頁時務必記得同步在這裡加路由，並更新 `sitemap.xml`。
3. **`.env` / `firebase_credentials.json`** 是機密檔案，確認 `.gitignore` 有排除，
   不要不小心 commit 進版控或上傳分享。
4. **Render 免費方案的 self-ping 機制**是權宜設計，如果之後升級方案記得清掉，
   否則會浪費資源。
5. **AdSense 廣告版位程式碼目前用 HTML 註解關閉**（寫著「AdSense 審核通過後啟用」），
   審核通過後記得手動去每個教學文章頁面把註解拿掉才會真的顯示廣告。
6. **`/api/visitor`、`/api/maintenance` 這兩個端點的實際用途** 尚待確認/補充文件，
   目前只從路由名稱推測功能，建議之後補上詳細註解或使用說明。
7. **教學文章仍各自內嵌大量專屬 CSS**（互動元件、SVG 圖表樣式）。這次風格統一是用
   「固定 `theme-day` ＋ 色相分桶把所有顏色收斂成 4 語意色」的方式做的，共用的頁首/
   頁尾/字體已抽到 `site.css`，但各章的版面樣式還沒抽共用模組。未來若要再改教學文
   版面，仍需逐檔處理。
8. **`site.css` 的 `?v=` 版本字串是手動維護**（目前 `2026-08-29`）。每次改 `site.css`
   要記得更新所有頁面 `<link>` 的這個字串才能讓 Render 上的瀏覽器抓到新版，之後可考慮
   寫成 build step。
9. **教學章節大標題語意標籤已統一**：原本約 14 個章節用 `<div class="hero-title">`，
   已全部改為 `<h1 class="hero-title">`（每頁一個 `<h1>`，SEO / 無障礙）。其餘章節本來
   就是 `<h1>`。
