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

    # ── 公司重大訊息 API ──────────────────────────────────────────────────────────────
    @app.route("/api/news")
    def api_news():
        import requests as _req
        import urllib3 as _u3
        import datetime, re as _re
        _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)

        tz    = __import__("zoneinfo").ZoneInfo("Asia/Taipei")
        today = datetime.datetime.now(tz).strftime("%Y%m%d")

        hdrs = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Content-Type":    "application/x-www-form-urlencoded",
            "Referer":         "https://mopsov.twse.com.tw/mops/web/index",
            "Origin":          "https://mopsov.twse.com.tw",
        }

        def parse_html(html, extract_skey=False):
            """Parse MOPS HTML rows into list of dicts."""
            items = []
            rows = _re.findall(r"<tr[^>]*>(.*?)</tr>", html, _re.DOTALL)
            for row in rows:
                tds = _re.findall(r"<td[^>]*>(.*?)</td>", row, _re.DOTALL)
                if len(tds) < 5:
                    continue
                code  = _re.sub(r"<[^>]+>", "", tds[0]).strip()
                name  = _re.sub(r"<[^>]+>", "", tds[1]).strip()
                date  = _re.sub(r"<[^>]+>", "", tds[2]).strip()
                time_ = _re.sub(r"<[^>]+>", "", tds[3]).strip()
                tm    = _re.search(r'title="([^"]+)"', tds[4])
                if not tm:
                    tm = _re.search(r"title='([^']+)'", tds[4])
                title = tm.group(1).replace("\n"," ").replace("\r"," ").strip() if tm else _re.sub(r"<[^>]+>","",tds[4]).strip()
                if not (code and name and title):
                    continue
                skey = ""
                if extract_skey:
                    sm = _re.search(r"skey\.value='([^']+)'", tds[4])
                    if not sm:
                        sm = _re.search(r'skey\.value="([^"]+)"', tds[4])
                    skey = sm.group(1) if sm else ""
                try:
                    ci     = int(code)
                    is_otc = (4000<=ci<=4999) or (6000<=ci<=6999) or ci>=8000
                except ValueError:
                    is_otc = False
                items.append({
                    "source": "OTC"  if is_otc else "TWSE",
                    "label":  "上櫃" if is_otc else "上市",
                    "code": code, "name": name, "date": date, "time": time_,
                    "title": title[:60] + ("..." if len(title)>60 else ""),
                    "skey": skey,
                })
            return items

        # ── Step 1: ajax_index → 最新8筆，含正確 skey ─────────────────────────
        skey_map = {}  # key: (code, time) -> skey
        try:
            r = _req.post(
                "https://mopsov.twse.com.tw/mops/web/ajax_index",
                headers=hdrs, data="stp=1&TYPEK1=all",
                timeout=12, verify=False
            )
            if r.status_code == 200:
                for item in parse_html(r.text, extract_skey=True):
                    if item["skey"]:
                        skey_map[(item["code"], item["time"])] = item["skey"]
                print(f"[api/news] ajax_index skey_map: {len(skey_map)} entries")
        except Exception as e:
            print(f"[api/news] ajax_index 失敗: {e}")

        # ── Step 2: ajax_t05sr01_1 → 完整當日列表 ─────────────────────────────
        items = []
        try:
            r = _req.post(
                "https://mopsov.twse.com.tw/mops/web/ajax_t05sr01_1",
                headers=hdrs,
                data="TYPEK=all&step=0&stp=1&firstin=true&newstuff=1&off=1&keyword4=&code1=&TYPEK2=&checkbtn=",
                timeout=15, verify=False
            )
            if r.status_code == 200:
                parsed = parse_html(r.text, extract_skey=False)
                print(f"[api/news] ajax_t05sr01_1: {len(parsed)} rows")
                for item in parsed:
                    # 從 skey_map 補入 skey
                    skey = skey_map.get((item["code"], item["time"]), "")
                    item["skey"] = skey
                    item["link"] = f"https://mops.twse.com.tw/mops/#/web/t05sr01_1?co_id={item['code']}"
                    items.append(item)
        except Exception as e:
            print(f"[api/news] ajax_t05sr01_1 失敗: {e}")

        # ── Fallback: 若完整列表失敗，用 ajax_index 的8筆 ──────────────────────
        if not items and skey_map:
            try:
                r = _req.post(
                    "https://mopsov.twse.com.tw/mops/web/ajax_index",
                    headers=hdrs, data="stp=1&TYPEK1=all",
                    timeout=12, verify=False
                )
                if r.status_code == 200:
                    for item in parse_html(r.text, extract_skey=True):
                        item["link"] = f"https://mops.twse.com.tw/mops/#/web/t05sr01_1?co_id={item['code']}"
                        items.append(item)
            except Exception as e:
                print(f"[api/news] fallback 失敗: {e}")

        return jsonify({"date": today, "count": len(items), "data": items})

    # ── 公司重大訊息頁 ───────────────────────────────────────────────────────────────
    @app.route("/stock_site/news/news.html")
    def page_news():
        return send_from_directory('stock_site/news', 'news.html')

    # ── 注意股查詢頁 ─────────────────────────────────────────────────────────────────
    @app.route("/stock_site/news/notice.html")
    def page_notice():
        return send_from_directory('stock_site/news', 'notice.html')

    # ── 注意股 API proxy ──────────────────────────────────────────────────────────────
    @app.route("/api/notice")
    def api_notice():
        import requests as _req
        import time as _time
        import urllib3 as _u3
        _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)

        ts = int(_time.time() * 1000)
        url = f"https://www.twse.com.tw/rwd/zh/announcement/notice?response=json&_={ts}"
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer": "https://www.twse.com.tw/",
        }
        try:
            r = _req.get(url, headers=hdrs, timeout=10, verify=False)
            r.raise_for_status()
            return jsonify(r.json())
        except Exception as e:
            print(f"[api/notice] 失敗: {e}")
            return jsonify({"stat": "error", "error": str(e), "data": []}), 200

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

    # ── 波浪走勢分析頁面 ────────────────────────────────────────────────────────
    @app.route("/stock_site/tools/wave_chart.html")
    def page_wave_chart():
        return send_from_directory('stock_site/tools', 'wave_chart.html')

    # ── 波浪走勢資料 Proxy API ──────────────────────────────────────────────────
    # 用法：/api/wave_data?keyword=2313&months=3
    # 解決瀏覽器端 CORS 限制，由後端呼叫 TWSE 再回傳
    @app.route("/api/wave_data")
    def api_wave_data():
        import requests as _req
        import time as _time
        import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        keyword = request.args.get("keyword", "").strip()
        months  = int(request.args.get("months", 2))
        months  = max(1, min(12, months))

        if not keyword:
            return jsonify({"error": "請輸入股票代碼或名稱"}), 400

        stock_no   = ""
        stock_name = ""

        if re.match(r"^\d{4,6}$", keyword):
            stock_no = keyword
        else:
            stock_no   = keyword
            stock_name = keyword

        tz    = _ZI("Asia/Taipei")
        now   = _dt.datetime.now(tz)
        rows  = []
        name_from_api = ""

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        hdrs = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer":         "https://www.twse.com.tw/",
        }

        for i in range(months - 1, -1, -1):
            d      = _dt.date(now.year, now.month, 1) - _dt.timedelta(days=i*28)
            yyyymm = f"{d.year}{d.month:02d}"
            url    = (
                f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
                f"?response=json&date={yyyymm}01&stockNo={stock_no}"
            )
            try:
                r = _req.get(url, headers=hdrs, timeout=12, verify=False)
                j = r.json()
                if j.get("stat") == "OK" and j.get("data"):
                    if not name_from_api and j.get("title"):
                        import re as _re2
                        m = _re2.search(r"\d{4}\s+(.+?)\s+個股", j["title"])
                        if m:
                            name_from_api = m.group(1).strip()
                    for row in j["data"]:
                        try:
                            open_  = float(row[3].replace(",", ""))
                            high   = float(row[4].replace(",", ""))
                            low    = float(row[5].replace(",", ""))
                            close  = float(row[6].replace(",", ""))
                            vol    = int(row[1].replace(",", ""))
                            if close > 0:
                                rows.append({
                                    "date":   row[0],
                                    "open":   open_,
                                    "high":   high,
                                    "low":    low,
                                    "close":  close,
                                    "volume": vol,
                                })
                        except Exception:
                            continue
            except Exception as e:
                print(f"[wave_data] {yyyymm} 抓取失敗: {e}")
                continue

        # OTC 備援
        if not rows:
            for i in range(months - 1, -1, -1):
                d   = _dt.date(now.year, now.month, 1) - _dt.timedelta(days=i*28)
                url = (
                    f"https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"
                    f"?l=zh-tw&d={d.year-1911}/{d.month:02d}&stkno={stock_no}&_={int(_time.time()*1000)}"
                )
                try:
                    r = _req.get(url, headers=hdrs, timeout=12, verify=False)
                    j = r.json()
                    if j.get("iTotalRecords", 0) > 0:
                        for row in j.get("aaData", []):
                            try:
                                close = float(row[6].replace(",", ""))
                                open_ = float(row[3].replace(",", ""))
                                high  = float(row[4].replace(",", ""))
                                low   = float(row[5].replace(",", ""))
                                vol   = int(row[1].replace(",", "").replace(" ", ""))
                                if close > 0:
                                    rows.append({
                                        "date":   row[0],
                                        "open":   open_,
                                        "high":   high,
                                        "low":    low,
                                        "close":  close,
                                        "volume": vol,
                                    })
                            except Exception:
                                continue
                except Exception as e:
                    print(f"[wave_data/OTC] {d.year}/{d.month} 失敗: {e}")
                    continue

        if not rows:
            return jsonify({"error": f"查無「{keyword}」的股價資料，請確認代碼正確"}), 200

        final_name = name_from_api or stock_name or keyword
        return jsonify({
            "name":    final_name,
            "stockNo": stock_no,
            "months":  months,
            "count":   len(rows),
            "data":    rows,
        })

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

    # ── 訪客統計 API ──────────────────────────────────────────────────────────
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