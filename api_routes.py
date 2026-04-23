from flask import jsonify, request, send_from_directory
from flask_cors import CORS
from post_Info import stock_info, market_pnfo, get_today, twse_top50, otc_top50
from get_trading_holidays import get_trading_status
import re
import os
import requests as http_requests  # 避免與 flask request 衝突

# ── Supabase 設定 ──────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

def _supabase_headers():
    return {
        'apikey':        SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type':  'application/json',
        'Prefer':        'return=representation',
    }


def register_api(app):
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── 首頁 ───────────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory('.', 'index.html')

    # ── 靜態資源（images、音樂等）─────────────────────────────────────────────
    # 讓 Render 能正確提供 logo、背景圖等資源
    @app.route("/images/<path:filename>")
    def serve_images(filename):
        return send_from_directory('images', filename)

    @app.route("/music/<path:filename>")
    def serve_music(filename):
        return send_from_directory('music', filename)

    @app.route("/fonts/<path:filename>")
    def serve_fonts(filename):
        return send_from_directory('fonts', filename)

    # ── Legal 頁面（stock_site/legal/）────────────────────────────────────────
    @app.route("/stock_site/legal/about.html")
    def page_about():
        return send_from_directory('stock_site/legal', 'about.html')

    @app.route("/stock_site/legal/privacy.html")
    def page_privacy():
        return send_from_directory('stock_site/legal', 'privacy.html')

    @app.route("/stock_site/legal/disclaimer.html")
    def page_disclaimer():
        return send_from_directory('stock_site/legal', 'disclaimer.html')

    # ── Features 頁面（stock_site/features/）──────────────────────────────────
    @app.route("/stock_site/features/watchlist.html")
    def page_watchlist():
        return send_from_directory('stock_site/features', 'watchlist.html')

    @app.route("/stock_site/features/top50_twse.html")
    def page_top50_twse():
        return send_from_directory('stock_site/features', 'top50_twse.html')

    @app.route("/stock_site/features/top50_otc.html")
    def page_top50_otc():
        return send_from_directory('stock_site/features', 'top50_otc.html')

    # ── 交易日狀態 API ─────────────────────────────────────────────────────────
    @app.route("/api/trading_status")
    def api_trading_status():
        return jsonify(get_trading_status())

    # ── 上市三大法人買賣超前50 API ─────────────────────────────────────────────
    @app.route("/api/top50")
    def api_top50():
        return jsonify(twse_top50())

    # ── 上櫃三大法人買賣超前50 API ─────────────────────────────────────────────
    @app.route("/api/otc_top50")
    def api_otc_top50():
        return jsonify(otc_top50())

    # ── 個股查詢 API ───────────────────────────────────────────────────────────
    @app.route("/api/stock")
    def api_stock():
        keyword = request.args.get("keyword", "").strip()
        if not keyword:
            return jsonify({"error": "請輸入股票代碼或名稱"}), 400

        raw = stock_info(keyword)

        if raw.startswith("📢") or raw.startswith("❌"):
            return jsonify({"error": raw}), 200

        lines  = raw.split("\n")
        result = {
            "keyword":     keyword,
            "name":        lines[0].split("(")[0].strip() if lines else keyword,
            "date":        get_today(),
            "market":      None,
            "foreign":     None,
            "trust":       None,
            "proprietary": None,
            "short_sale":  None,
            "disposal":    None,
        }

        for line in lines[1:]:
            if line.startswith("外資"):
                result["foreign"]     = _extract_val(line)
            elif line.startswith("投信"):
                result["trust"]       = _extract_val(line)
            elif line.startswith("自營商"):
                result["proprietary"] = _extract_val(line)
            elif line.startswith("借卷賣出"):
                result["short_sale"]  = _extract_val(line)
            elif line.startswith("處置"):
                result["disposal"]    = line

        return jsonify(result)

    # ── 大盤資訊 API ───────────────────────────────────────────────────────────
    @app.route("/api/market")
    def api_market():
        raw    = market_pnfo()
        result = {
            "foreign":     None,
            "trust":       None,
            "proprietary": None,
            "total":       None,
            "margin_delta":None,
            "margin_level":None,
        }

        for line in raw.split("\n"):
            if "外資" in line:
                result["foreign"]      = _extract_float(line)
            elif "投信" in line:
                result["trust"]        = _extract_float(line)
            elif "自營商" in line:
                result["proprietary"]  = _extract_float(line)
            elif "合計" in line:
                result["total"]        = _extract_float(line)
            elif "融資金額增減" in line:
                result["margin_delta"] = _extract_float(line)
            elif "融資額金水位" in line or "融資水位" in line:
                result["margin_level"] = _extract_float(line)

        return jsonify(result)

    # ── 訪客統計 API ───────────────────────────────────────────────────────────
    @app.route("/api/visitor", methods=["POST"])
    def api_visitor():
        if not SUPABASE_URL or not SUPABASE_KEY:
            return jsonify({"error": "Supabase 未設定"}), 500

        from datetime import datetime, timezone, timedelta
        today   = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')
        headers = _supabase_headers()

        try:
            # ── 1. 今日訪客數 +1 ──────────────────────────────────────────
            check = http_requests.get(
                f"{SUPABASE_URL}/rest/v1/visitors_daily"
                f"?visit_date=eq.{today}&select=id,count",
                headers=headers
            )
            rows = check.json()

            if rows:
                row_id      = rows[0]['id']
                today_count = rows[0]['count'] + 1
                http_requests.patch(
                    f"{SUPABASE_URL}/rest/v1/visitors_daily?id=eq.{row_id}",
                    headers=headers,
                    json={"count": today_count}
                )
            else:
                today_count = 1
                http_requests.post(
                    f"{SUPABASE_URL}/rest/v1/visitors_daily",
                    headers=headers,
                    json={"visit_date": today, "count": 1}
                )

            # ── 2. 累積總訪客數 +1 ────────────────────────────────────────
            total_res  = http_requests.get(
                f"{SUPABASE_URL}/rest/v1/visitors_total?id=eq.1&select=count",
                headers=headers
            )
            total_rows = total_res.json()

            if total_rows:
                new_total = total_rows[0]['count'] + 1
                http_requests.patch(
                    f"{SUPABASE_URL}/rest/v1/visitors_total?id=eq.1",
                    headers=headers,
                    json={"count": new_total}
                )
            else:
                new_total = 1
                http_requests.post(
                    f"{SUPABASE_URL}/rest/v1/visitors_total",
                    headers=headers,
                    json={"id": 1, "count": 1}
                )

            return jsonify({"today": today_count, "total": new_total})

        except Exception as e:
            print(f"[Visitor] Supabase 錯誤: {e}")
            return jsonify({"error": str(e)}), 500


# ── 工具函式 ──────────────────────────────────────────────────────────────────
def _extract_val(line):
    # 同時支援「張」和「股」
    m = re.search(r"：\s*([^\s]+)\s*[張股]", line)
    return m.group(1) if m else None

def _extract_float(line):
    m = re.search(r":\s*(-?[\d.]+)", line)
    try:
        return float(m.group(1)) if m else None
    except Exception:
        return None