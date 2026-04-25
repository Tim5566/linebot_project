from flask import jsonify, request, send_from_directory
from flask_cors import CORS
from post_Info import stock_info, market_pnfo, get_today, twse_top50, otc_top50
from get_trading_holidays import get_trading_status
import re
import os
from firebase_admin import db as firebase_db


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

    # ── 手動觸發 Firebase 同步（測試用）────────────────────────────────────────
    # 用法：瀏覽器打開 /api/sync_test?date=20250424&token=你設定的SECRET
    @app.route("/api/sync_test")
    def api_sync_test():
        token = request.args.get("token", "")
        secret = os.environ.get("SYNC_SECRET", "")
        if not secret or token != secret:
            return jsonify({"error": "未授權"}), 403

        date = request.args.get("date", get_today())

        try:
            import firebase_sync
            firebase_sync.sync_all(date)
            return jsonify({"status": "ok", "date": date, "message": f"{date} 同步完成"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

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
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')

        try:
            # ── 1. 今日訪客數 +1 ──────────────────────────────────────────
            daily_ref   = firebase_db.reference(f"visitors/daily/{today}")
            today_count = (daily_ref.get() or 0) + 1
            daily_ref.set(today_count)

            # ── 2. 累積總訪客數 +1 ────────────────────────────────────────
            total_ref = firebase_db.reference("visitors/total")
            new_total = (total_ref.get() or 0) + 1
            total_ref.set(new_total)

            return jsonify({"today": today_count, "total": new_total})

        except Exception as e:
            print(f"[Visitor] Firebase 錯誤: {e}")
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