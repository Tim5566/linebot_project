from flask import jsonify, request
from flask_cors import CORS
from post_Info import stock_info, market_pnfo
import re


def register_api(app):
    # ── 允許靜態網站跨域呼叫 ──────────────────────────────────────────
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── 個股查詢 API ───────────────────────────────────────────────────
    @app.route("/api/stock")
    def api_stock():
        keyword = request.args.get("keyword", "").strip()
        if not keyword:
            return jsonify({"error": "請輸入股票代碼或名稱"}), 400

        raw = stock_info(keyword)   # 你原本的函式，回傳純文字

        # ── 解析純文字 → JSON ──────────────────────────────────────────
        if raw.startswith("📢") or raw.startswith("❌"):
            return jsonify({"error": raw}), 200

        lines = raw.split("\n")
        result = {
            "keyword": keyword,
            "name":    lines[0].split("(")[0].strip() if lines else keyword,
            "date":    _today_str(),
            "market":  None,
            "foreign":    None,
            "trust":      None,
            "proprietary":None,
            "short_sale": None,
            "disposal":   None,
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

    # ── 大盤資訊 API ───────────────────────────────────────────────────
    @app.route("/api/market")
    def api_market():
        raw = market_pnfo()   # 你原本的函式，回傳純文字

        result = {
            "foreign":     None,
            "trust":       None,
            "proprietary": None,
            "total":       None,
            "margin_delta":None,
            "margin_level":None,
        }

        for line in raw.split("\n"):
            lc = line.lower()
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


# ── 工具函式 ──────────────────────────────────────────────────────────────────
def _extract_val(line):
    """外資：123,456 股  →  '123,456'"""
    m = re.search(r"：\s*([^\s]+)\s*股", line)
    return m.group(1) if m else None

def _extract_float(line):
    """合計金額 : -12.34億  →  -12.34"""
    m = re.search(r":\s*(-?[\d.]+)", line)
    try:
        return float(m.group(1)) if m else None
    except Exception:
        return None

def _today_str() -> str:
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
