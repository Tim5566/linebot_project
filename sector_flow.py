"""
sector_flow.py — 類股資金流向熱力圖（上市＋上櫃整合）

概念：
  把「三大法人（外資＋投信＋自營商）淨買超股數 × 收盤價」按產業別加總，
  得到每個交易日每個類股的「法人淨買賣超金額」（億元，正=資金流入）。
  再以「當日全部類股淨買賣超金額絕對值總和」為分母，算出各類股當日「資金占比」。
  比對最近 3 個交易日的方向，找出「連續流入 / 連續流出」的類股。

資料來源：
  法人買賣超股數 → Firebase 現有 stock_data/{date}/{twse|otc}
                    （sync_institutional / sync_otc_institutional 每日同步）
  收盤價         → Firebase stock_data/{date}/price_all/{twse|otc}
                    （缺就用 firebase_sync._fetch_price_all_* 現場補抓一次）
  產業別對照     → openapi.twse.com.tw t187ap03_L（產業別）
                    + tpex.org.tw mopsfin_t187ap03_O（SecuritiesIndustryCode）
                    兩邊都是 MOPS 同一組產業代碼，寫入 industry_map/{twse|otc}

Firebase 路徑：
  industry_map/twse/{代碼} = 產業代碼          （每週更新一次即可）
  industry_map/otc/{代碼}  = 產業代碼
  industry_map/meta        = {updated_at, twse_count, otc_count}
  sector_flow_history/{YYYYMMDD} = {trade_date, updated, markets, total_abs, sectors:{代碼:{amt,share}}}
                                    只保留最近 3 個交易日

排程：
  每個交易日 18:10 由 push_service._sync_sector_flow_daily() 呼叫 sync_sector_flow()。
  另外 /api/sector_heatmap 在今日快照尚未產生時會現場補算一次。
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from firebase_admin import db as firebase_db
from firebase_sync import (
    _fetch, _write_batch, _init_firebase, get_today,
    _fetch_price_all_twse, _fetch_price_all_otc, _STOCK_CODE_RE,
)

# ── MOPS 產業代碼 → 顯示名稱（上市／上櫃共用同一組代碼）────────────────────────
INDUSTRY_NAMES = {
    "01": "水泥",       "02": "食品",       "03": "塑膠",       "04": "紡織纖維",
    "05": "電機機械",   "06": "電器電纜",   "08": "玻璃陶瓷",   "09": "造紙",
    "10": "鋼鐵",       "11": "橡膠",       "12": "汽車",       "14": "建材營造",
    "15": "航運",       "16": "觀光餐旅",   "17": "金融保險",   "18": "貿易百貨",
    "19": "綜合",       "20": "其他",       "21": "化學工業",   "22": "生技醫療",
    "23": "油電燃氣",   "24": "半導體",     "25": "電腦及週邊", "26": "光電",
    "27": "通信網路",   "28": "電子零組件", "29": "電子通路",   "30": "資訊服務",
    "31": "其他電子",   "32": "文化創意",   "33": "農業科技",   "34": "電子商務",
    "35": "綠能環保",   "36": "數位雲端",   "37": "運動休閒",   "38": "居家生活",
    "OTHER": "其他未分類",
}

# 管理股票(80) / 存託憑證 TDR(91) / 空值 → 併入「其他未分類」
_MERGE_CODE = {"80": "OTHER", "91": "OTHER", "": "OTHER"}

_IND_TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
_IND_OTC_URL  = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

_HISTORY_KEEP = 3   # 只保留最近 3 個交易日快照（只需判斷「連續三天」）


def _fmt_date(raw) -> str:
    """'20260904' → '2026-09-04'；已有分隔或非預期格式原樣回傳。"""
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else str(raw or "")


# ══════════════════════════════════════════════════════════════════════════════
# 產業別對照表
# ══════════════════════════════════════════════════════════════════════════════
def _sync_industry_map():
    """抓上市＋上櫃公司產業別，寫入 industry_map/{twse|otc}。回傳 (twse_dict, otc_dict)。"""
    _init_firebase()
    twse, otc = {}, {}

    try:
        data = _fetch(_IND_TWSE_URL)
        for row in (data or []):
            code = str(row.get("公司代號", "")).strip()
            ind  = str(row.get("產業別", "")).strip()
            if _STOCK_CODE_RE.match(code) and ind:
                twse[code] = ind
        print(f"[industry_map] 上市抓到 {len(twse)} 筆")
    except Exception as e:
        print(f"[industry_map] 上市抓取失敗: {e} ⚠️")

    try:
        data = _fetch(_IND_OTC_URL)
        for row in (data or []):
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            ind  = str(row.get("SecuritiesIndustryCode", "")).strip()
            if _STOCK_CODE_RE.match(code) and ind:
                otc[code] = ind
        print(f"[industry_map] 上櫃抓到 {len(otc)} 筆")
    except Exception as e:
        print(f"[industry_map] 上櫃抓取失敗: {e} ⚠️")

    if twse:
        _write_batch("industry_map/twse", twse)
    if otc:
        _write_batch("industry_map/otc", otc)
    if twse or otc:
        firebase_db.reference("industry_map/meta").set({
            "updated_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
            "twse_count": len(twse),
            "otc_count":  len(otc),
        })
    print(f"[industry_map] 完成：上市 {len(twse)} + 上櫃 {len(otc)} 筆")
    return twse, otc


def _get_industry_map() -> dict:
    """回傳 {股票代碼: 產業代碼}（上市＋上櫃合併）。"""
    _init_firebase()
    merged = {}
    for mk in ("twse", "otc"):
        merged.update(firebase_db.reference(f"industry_map/{mk}").get() or {})
    return merged


def _ensure_industry_map(max_age_days: int = 6):
    """產業別對照表不存在或超過 max_age_days 天沒更新 → 重抓一次。"""
    meta = firebase_db.reference("industry_map/meta").get() or {}
    ts = meta.get("updated_at")
    fresh = False
    if ts:
        try:
            age = datetime.now(ZoneInfo("Asia/Taipei")) - datetime.fromisoformat(ts)
            fresh = age < timedelta(days=max_age_days)
        except Exception:
            fresh = False
    if not fresh:
        print("[industry_map] 對照表過期或不存在，重新同步")
        _sync_industry_map()


# ══════════════════════════════════════════════════════════════════════════════
# 每日類股資金流向計算
# ══════════════════════════════════════════════════════════════════════════════
def _load_price(date_d: str, market: str) -> dict:
    """讀 Firebase price_all；缺就現場補抓一次（含來源日期比對）。回傳 {代碼:{c,d}}。"""
    ref = firebase_db.reference(f"stock_data/{date_d}/price_all/{market}")
    px = ref.get() or {}
    if px:
        return px
    try:
        print(f"[sector_flow] price_all 無資料，現場補抓 market={market} date={date_d}")
        if market == "twse":
            src_date, data = _fetch_price_all_twse(date_d)
        else:
            src_date, data = _fetch_price_all_otc()
        if data and src_date == date_d:
            _write_batch(f"stock_data/{date_d}/price_all/{market}", data)
            return data
        if data:
            print(f"[sector_flow] {market} 收盤價來源日期 {src_date} ≠ {date_d}，不採用 ⚠️")
    except Exception as e:
        print(f"[sector_flow] {market} 收盤價補抓失敗: {e} ⚠️")
    return {}


def compute_sector_flow(date_d: str = None) -> dict:
    """
    計算指定交易日的類股法人資金流向。
    回傳：
      {
        "trade_date": "20260904",
        "updated":    ISO 時間字串,
        "markets":    ["twse", "otc"],   # 實際納入計算的市場
        "total_abs":  當日全部類股淨買賣超金額絕對值總和（億）,
        "sectors": { "24": {"amt": 淨買賣超億元, "share": 占比 0~1（帶正負號）}, ... }
      }
    """
    if date_d is None:
        date_d = get_today()
    date_d = "".join(ch for ch in str(date_d) if ch.isdigit())
    _init_firebase()

    ind_map = _get_industry_map()
    if not ind_map:
        print("[sector_flow] 產業別對照表為空，先同步一次")
        _sync_industry_map()
        ind_map = _get_industry_map()

    sectors: dict = {}
    markets: list = []

    for market in ("twse", "otc"):
        inst = firebase_db.reference(f"stock_data/{date_d}/{market}").get() or {}
        if not inst:
            print(f"[sector_flow] {market} 當日法人資料尚未就緒，略過")
            continue
        price = _load_price(date_d, market)
        if not price:
            print(f"[sector_flow] {market} 當日收盤價無法取得，略過")
            continue
        markets.append(market)

        for sid, info in inst.items():
            if not sid or not _STOCK_CODE_RE.match(sid):
                continue
            px = price.get(sid)
            if not px:
                continue
            close = px.get("c")
            if not close or close <= 0:
                continue

            net_shares = 0
            has_val = False
            for key in ("foreign", "trust", "proprietary"):
                raw = info.get(key)
                if raw is None or raw == "":
                    continue
                try:
                    net_shares += int(str(raw).replace(",", ""))
                    has_val = True
                except (ValueError, TypeError):
                    continue
            if not has_val:
                continue

            code = ind_map.get(sid, "OTHER")
            code = _MERGE_CODE.get(code, code)
            if code not in INDUSTRY_NAMES:
                code = "OTHER"
            sectors[code] = sectors.get(code, 0.0) + net_shares * close / 1e8

    total_abs = sum(abs(v) for v in sectors.values())
    return {
        "trade_date": date_d,
        "updated": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "markets": markets,
        "total_abs": round(total_abs, 4),
        "sectors": {
            code: {
                "amt":   round(v, 4),
                "share": round(v / total_abs, 6) if total_abs else 0.0,
            }
            for code, v in sectors.items()
        },
    }


def _cleanup_sector_flow_history(keep: int = _HISTORY_KEEP):
    """只保留最近 keep 個日期快照，其餘刪除。"""
    try:
        ref = firebase_db.reference("sector_flow_history")
        keys = sorted(ref.get(shallow=True) or {}, reverse=True)
        for old in keys[keep:]:
            ref.child(old).delete()
            print(f"[sector_flow] 清除舊快照 {old}")
    except Exception as e:
        print(f"[sector_flow] 清除舊快照失敗: {e} ⚠️")


def sync_sector_flow(date_d: str = None) -> dict:
    """計算當日類股資金流向並寫入 sector_flow_history/{date}。供每日排程與 API 現場補算共用。"""
    if date_d is None:
        date_d = get_today()
    date_d = "".join(ch for ch in str(date_d) if ch.isdigit())

    data = compute_sector_flow(date_d)
    if not data["sectors"]:
        print(f"[sector_flow] {date_d} 無資料可算，未寫入")
        return data

    _init_firebase()
    firebase_db.reference(f"sector_flow_history/{date_d}").set(data)
    _cleanup_sector_flow_history()
    print(f"[sector_flow] {date_d} 已寫入 {len(data['sectors'])} 個類股"
          f"（市場 {data['markets']}，總量 {data['total_abs']} 億）✅")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# 熱力圖 API payload
# ══════════════════════════════════════════════════════════════════════════════
def build_heatmap_payload() -> dict:
    """
    讀最近 3 個交易日的類股資金流向快照，組出熱力圖 + 連續流入/流出榜。
    """
    _init_firebase()
    today_d = get_today()
    hist_ref = firebase_db.reference("sector_flow_history")
    keys = sorted(hist_ref.get(shallow=True) or {}, reverse=True)

    # 今日快照還沒產生（排程未跑或首位訪客）→ 若當日法人資料已就緒就現場補算一次
    if today_d not in keys:
        if firebase_db.reference(f"stock_data/{today_d}/twse").get(shallow=True):
            try:
                sync_sector_flow(today_d)
                keys = sorted(hist_ref.get(shallow=True) or {}, reverse=True)
            except Exception as e:
                print(f"[sector_flow] 現場補算失敗: {e} ⚠️")

    if not keys:
        return {"status": "nodata", "message": "目前尚無類股資金流向資料。"}

    snaps = []
    for k in keys[:_HISTORY_KEEP]:
        s = hist_ref.child(k).get()
        if s and s.get("sectors"):
            snaps.append(s)
    if not snaps:
        return {"status": "nodata", "message": "目前尚無類股資金流向資料。"}

    latest = snaps[0]

    codes = set()
    for s in snaps:
        codes.update((s.get("sectors") or {}).keys())

    tiles = []
    for code in codes:
        cur = (latest.get("sectors") or {}).get(code, {"amt": 0.0, "share": 0.0})

        streak = 0
        direction = 0
        cum_amt = 0.0
        cum_base = 0.0
        for s in snaps:
            sec = (s.get("sectors") or {}).get(code)
            if not sec:
                break
            amt = sec.get("amt", 0.0) or 0.0
            sgn = 1 if amt > 0 else (-1 if amt < 0 else 0)
            if sgn == 0:
                break
            if direction == 0:
                direction = sgn
            elif sgn != direction:
                break
            streak += 1
            cum_amt += amt
            cum_base += s.get("total_abs", 0.0) or 0.0

        tiles.append({
            "code": code,
            "name": INDUSTRY_NAMES.get(code, code),
            "amt": round(cur.get("amt", 0.0) or 0.0, 2),
            "share": round((cur.get("share", 0.0) or 0.0) * 100, 2),
            "streak": streak,
            "direction": direction,
            "cum_amt": round(cum_amt, 2),
            "cum_share": round(cum_amt / cum_base * 100, 2) if cum_base else 0.0,
        })

    tiles.sort(key=lambda t: t["share"], reverse=True)

    inflow = sorted(
        [t for t in tiles if t["direction"] == 1 and t["streak"] >= 2],
        key=lambda t: (t["streak"], t["cum_amt"]), reverse=True,
    )
    outflow = sorted(
        [t for t in tiles if t["direction"] == -1 and t["streak"] >= 2],
        key=lambda t: (t["streak"], -t["cum_amt"]), reverse=True,
    )

    return {
        "status": "ok",
        "trade_date": _fmt_date(latest.get("trade_date")),
        "updated": latest.get("updated"),
        "days": [_fmt_date(s.get("trade_date")) for s in snaps],
        "markets": latest.get("markets", []),
        "tiles": tiles,
        "inflow": inflow,
        "outflow": outflow,
    }
