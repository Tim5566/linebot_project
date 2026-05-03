from flask import jsonify, request, send_from_directory
from flask_cors import CORS
from post_Info import stock_info, market_pnfo, get_today, twse_top50, otc_top50
from get_trading_holidays import get_trading_status
import re
import os
from firebase_admin import db as firebase_db


def register_api(app):
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── HTTP 安全 Headers ──────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        # 防止 iframe 嵌入（點擊劫持攻擊）
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # 防止瀏覽器猜測 MIME 類型（內容注入攻擊）
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # 控制 Referer 資訊洩漏
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # 防止 XSS 攻擊（限制資源來源）
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://cdnjs.cloudflare.com "
                "https://pagead2.googlesyndication.com "
                "https://adservice.google.com "
                "https://www.googletagservices.com "
                "https://partner.googleadservices.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' "
                "https://pagead2.googlesyndication.com "
                "https://adservice.google.com; "
            "frame-src https://googleads.g.doubleclick.net "
                "https://tpc.googlesyndication.com; "
            "media-src 'self'; "
            "frame-ancestors 'self';"
        )
        # 強制 HTTPS（Render 部署後才有效）
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

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

    # ── 技術分析教學章節 ────────────────────────────────────────────────────────
    @app.route("/stock_site/features/chapter1.html")
    def page_chapter1():
        return send_from_directory('stock_site/features', 'chapter1.html')

    @app.route("/stock_site/features/chapter2.html")
    def page_chapter2():
        return send_from_directory('stock_site/features', 'chapter2.html')
    
    @app.route("/stock_site/features/chapter3.html")
    def page_chapter3():
        return send_from_directory('stock_site/features', 'chapter3.html')
    
    @app.route("/stock_site/features/chapter4.html")
    def page_chapter4():
        return send_from_directory('stock_site/features', 'chapter4.html')
    
    @app.route("/stock_site/features/chapter5.html")
    def page_chapter5():
        return send_from_directory('stock_site/features', 'chapter5.html')
    
    @app.route("/stock_site/features/chapter6.html")
    def page_chapter6():
        return send_from_directory('stock_site/features', 'chapter6.html')
    
    @app.route("/stock_site/features/chapter7.html")
    def page_chapter7():
        return send_from_directory('stock_site/features', 'chapter7.html')
    
    @app.route("/stock_site/features/chapter8.html")
    def page_chapter8():
        return send_from_directory('stock_site/features', 'chapter8.html')
    
    @app.route("/stock_site/features/chapter9.html")
    def page_chapter9():
        return send_from_directory('stock_site/features', 'chapter9.html')
    
    @app.route("/stock_site/features/chapter10.html")
    def page_chapter10():
        return send_from_directory('stock_site/features', 'chapter10.html')

    # ── 財經新聞頁 ───────────────────────────────────────────────────────────────
    @app.route("/stock_site/news/news.html")
    def page_news():
        return send_from_directory('stock_site/news', 'news.html')

    # ── 交易日狀態 API ─────────────────────────────────────────────────────────
    @app.route("/api/trading_status")
    def api_trading_status():
        return jsonify(get_trading_status())

    # ── 手動觸發 Firebase 同步（測試用）────────────────────────────────────────
    # 用法：瀏覽器打開 /api/sync_test?date=20260424&token=你設定的SECRET
    @app.route("/api/sync_test")
    def api_sync_test():
        token = request.args.get("token", "")
        secret = os.environ.get("SYNC_SECRET", "")
        if not secret or token != secret:
            return jsonify({"error": "未授權"}), 403

        date = request.args.get("date", get_today())

        import threading
        import firebase_sync

        def run():
            try:
                firebase_sync.sync_all(date)
                print(f"[sync_test] {date} 同步完成 ✅")
            except Exception as e:
                import traceback
                print(f"[sync_test ERROR]\n{traceback.format_exc()}")

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"status": "started", "date": date, "message": f"{date} 同步已在背景執行，請看 Render Log"})

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