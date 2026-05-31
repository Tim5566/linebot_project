from flask import jsonify, request, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from post_Info import stock_info, market_pnfo, get_today, twse_top50, otc_top50
from get_trading_holidays import get_trading_status
import re
import os
import threading
from firebase_admin import db as firebase_db






def register_api(app):
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    limiter.init_app(app)

    # ── HTTP 安全 Headers ──────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://cdnjs.cloudflare.com "
                "https://accounts.google.com "
                "https://apis.google.com "
                "https://pagead2.googlesyndication.com "
                "https://adservice.google.com "
                "https://www.googletagservices.com "
                "https://partner.googleadservices.com; "
            "style-src 'self' 'unsafe-inline' "
                "https://fonts.googleapis.com "
                "https://accounts.google.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' "
                "https://accounts.google.com "
                "https://oauth2.googleapis.com "
                "https://www.googleapis.com "
                "https://*.googleapis.com "
                "https://*.firebaseio.com "
                "https://firestore.googleapis.com "
                "https://pagead2.googlesyndication.com "
                "https://adservice.google.com; "
            "frame-src 'self' "
                "https://accounts.google.com "
                "https://googleads.g.doubleclick.net "
                "https://tpc.googlesyndication.com; "
            "media-src 'self'; "
            "frame-ancestors 'self';"
        )
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # ── 超過 Rate Limit 時回傳 JSON（前端好處理）─────────────────────────────
    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({
            "error": "查詢太頻繁，請稍後再試",
            "retry_after": str(e.description),
        }), 429

    # ── 首頁 ───────────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory('.', 'index.html')

    @app.route("/ads.txt")
    def ads_txt():
        return send_from_directory('.', 'ads.txt', mimetype='text/plain')

    @app.route("/sitemap.xml")
    def sitemap():
        return send_from_directory('.', 'sitemap.xml', mimetype='application/xml')

    @app.route("/images/<path:filename>")
    def serve_images(filename):
        return send_from_directory('images', filename)

    @app.route("/music/<path:filename>")
    def serve_music(filename):
        return send_from_directory('music', filename)

    @app.route("/fonts/<path:filename>")
    def serve_fonts(filename):
        return send_from_directory('fonts', filename)

    # ── Legal 頁面 ─────────────────────────────────────────────────────────────
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

    # ── 籌碼分析教學章節 ────────────────────────────────────────────────────────
    @app.route("/stock_site/chips/chips_chapter1.html")
    def page_chips_chapter1():
        return send_from_directory('stock_site/chips', 'chips_chapter1.html')

    @app.route("/stock_site/chips/chips_chapter2.html")
    def page_chips_chapter2():
        return send_from_directory('stock_site/chips', 'chips_chapter2.html')

    @app.route("/stock_site/chips/chips_chapter3.html")
    def page_chips_chapter3():
        return send_from_directory('stock_site/chips', 'chips_chapter3.html')

    @app.route("/stock_site/chips/chips_chapter4.html")
    def page_chips_chapter4():
        return send_from_directory('stock_site/chips', 'chips_chapter4.html')

    @app.route("/stock_site/chips/chips_chapter5.html")
    def page_chips_chapter5():
        return send_from_directory('stock_site/chips', 'chips_chapter5.html')

    @app.route("/stock_site/chips/chips_chapter6.html")
    def page_chips_chapter6():
        return send_from_directory('stock_site/chips', 'chips_chapter6.html')

    @app.route("/stock_site/chips/chips_chapter7.html")
    def page_chips_chapter7():
        return send_from_directory('stock_site/chips', 'chips_chapter7.html')

    @app.route("/stock_site/chips/chips_chapter8.html")
    def page_chips_chapter8():
        return send_from_directory('stock_site/chips', 'chips_chapter8.html')

    @app.route("/stock_site/chips/chips_chapter9.html")
    def page_chips_chapter9():
        return send_from_directory('stock_site/chips', 'chips_chapter9.html')

    @app.route("/stock_site/chips/chips_chapter10.html")
    def page_chips_chapter10():
        return send_from_directory('stock_site/chips', 'chips_chapter10.html')

    # ── 公司重大訊息 API ───────────────────────────────────────────────────────
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

        skey_map = {}
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
        except Exception as e:
            print(f"[api/news] ajax_index 失敗: {e}")

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
                for item in parsed:
                    item["skey"] = skey_map.get((item["code"], item["time"]), "")
                    item["link"] = f"https://mops.twse.com.tw/mops/#/web/t05sr01_1?co_id={item['code']}"
                    items.append(item)
        except Exception as e:
            print(f"[api/news] ajax_t05sr01_1 失敗: {e}")

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

    # ── 公司重大訊息頁 ─────────────────────────────────────────────────────────
    @app.route("/stock_site/news/news.html")
    def page_news():
        return send_from_directory('stock_site/news', 'news.html')

    # ── 注意股查詢頁 ───────────────────────────────────────────────────────────
    @app.route("/stock_site/news/notice.html")
    def page_notice():
        return send_from_directory('stock_site/news', 'notice.html')

    # ── 注意股 API proxy（上市 TWSE + 上櫃 TPEX 合併）─────────────────────────
    @app.route("/api/notice")
    def api_notice():
        import requests as _req
        import time as _time
        import urllib3 as _u3
        import concurrent.futures as _cf
        _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)

        twse_hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer": "https://www.twse.com.tw/",
        }
        otc_hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer": "https://www.tpex.org.tw/",
        }

        # ── 抓上市 TWSE ──────────────────────────────────────────────────────
        def fetch_twse():
            ts  = int(_time.time() * 1000)
            url = f"https://www.twse.com.tw/rwd/zh/announcement/notice?response=json&_={ts}"
            try:
                r    = _req.get(url, headers=twse_hdrs, timeout=10, verify=False)
                data = r.json()
                items = []
                if data.get("stat") in ("OK", "ok"):
                    fields = data.get("fields", [])
                    rows   = data.get("data", [])
                    # 若 tables 結構
                    if not rows and data.get("tables"):
                        for t in data["tables"]:
                            fields = t.get("fields", fields)
                            rows.extend(t.get("data", []))
                    for row in rows:
                        if isinstance(row, list):
                            obj = {fields[i]: str(row[i]).strip() for i in range(min(len(fields), len(row)))}
                        else:
                            obj = {k: str(v).strip() for k, v in row.items()}
                        code = obj.get("證券代號") or obj.get("股票代號") or ""
                        if not code:
                            continue
                        items.append({
                            "market":  "上市",
                            "code":    code,
                            "name":    obj.get("證券名稱") or obj.get("股票簡稱") or "",
                            "count":   obj.get("累計次數") or obj.get("累計") or "",
                            "reason":  obj.get("注意交易資訊") or obj.get("注意原因") or "",
                            "date":    obj.get("日期") or obj.get("公告日期") or data.get("date", ""),
                            "close":   obj.get("收盤價") or "",
                            "per":     obj.get("本益比") or "",
                        })
                return items, data.get("date", "")
            except Exception as e:
                print(f"[api/notice] TWSE 失敗: {e}")
                return [], ""

        # ── 抓上櫃 TPEX ──────────────────────────────────────────────────────
        def fetch_otc():
            url = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention?response=json"
            try:
                r    = _req.get(url, headers=otc_hdrs, timeout=10, verify=False)
                data = r.json()
                items = []
                otc_date = data.get("date", "")
                for table in data.get("tables", []):
                    fields = table.get("fields", [])
                    for row in table.get("data", []):
                        if isinstance(row, list):
                            obj = {fields[i]: str(row[i]).strip() for i in range(min(len(fields), len(row)))}
                        else:
                            obj = {k: str(v).strip() for k, v in row.items()}
                        code = obj.get("證券代號") or obj.get("股票代號") or ""
                        if not code:
                            continue
                        items.append({
                            "market":  "上櫃",
                            "code":    code,
                            "name":    obj.get("證券名稱") or obj.get("股票簡稱") or "",
                            "count":   obj.get("累計次數") or obj.get("累計") or "",
                            "reason":  obj.get("注意交易資訊") or obj.get("注意原因") or "",
                            "date":    obj.get("日期") or obj.get("公告日期") or "",
                            "close":   obj.get("收盤價") or "",
                            "per":     obj.get("本益比") or "",
                        })
                return items, otc_date
            except Exception as e:
                print(f"[api/notice] TPEX 失敗: {e}")
                return [], ""

        # ── 並行抓取，合併回傳 ────────────────────────────────────────────────
        with _cf.ThreadPoolExecutor(max_workers=2) as ex:
            ft = ex.submit(fetch_twse)
            fo = ex.submit(fetch_otc)
            twse_items, twse_date = ft.result()
            otc_items,  otc_date  = fo.result()

        all_items = twse_items + otc_items
        # 合併日期取最新
        merged_date = twse_date or otc_date

        return jsonify({
            "stat":       "OK" if all_items else "error",
            "date":       merged_date,
            "twse_count": len(twse_items),
            "otc_count":  len(otc_items),
            "count":      len(all_items),
            "data":       all_items,
        })

    # ── 處置股 API ─────────────────────────────────────────────────────────────
    @app.route("/api/disposal")
    def api_disposal():
        import requests as _req
        import re as _re
        import urllib3 as _u3
        import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)

        def s(v):
            """安全轉字串並去空白，避免 int.strip() 錯誤"""
            return str(v).strip() if v is not None else ""

        today = _dt.datetime.now(_ZI("Asia/Taipei")).strftime("%Y%m%d")
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer": "https://www.twse.com.tw/",
        }
        results = []

        # ── TWSE 上市處置股 ──────────────────────────────────────────────────────
        # 欄位：[0]編號 [1]公布日期 [2]證券代號 [3]證券名稱 [4]累計
        #        [5]處置條件 [6]處置起迄時間 [7]處置措施 [8]處置內容 [9]備註
        try:
            url = f"https://www.twse.com.tw/rwd/zh/announcement/punish?startDate={today}&endDate={today}&queryType=3&response=json"
            r = _req.get(url, headers=hdrs, timeout=10, verify=False)
            data = r.json()
            seen_twse = set()
            for row in data.get("data", []):
                if len(row) < 8: continue
                sid = s(row[2])
                if not sid: continue
                period_raw = s(row[6])
                parts = period_raw.replace('～', '~').split('~')
                start = parts[0].strip() if parts else ""
                end   = parts[1].strip() if len(parts) > 1 else ""
                key = (sid, start)
                if key in seen_twse: continue
                seen_twse.add(key)
                results.append({
                    "code":      sid,
                    "name":      s(row[3]),
                    "market":    "上市",
                    "pub_date":  s(row[1]),
                    "count":     s(row[4]),
                    "condition": s(row[5]),
                    "start":     start,
                    "end":       end,
                    "measure":   s(row[7]),
                })
        except Exception as e:
            print(f"[api/disposal] TWSE 失敗: {e}")

        # ── OTC 上櫃處置股 ───────────────────────────────────────────────────────
        # 欄位：[0]編號 [1]公布日期 [2]證券代號 [3]證券名稱(含href) [4]累計
        #        [5]處置起訖時間 [6]處置原因 [7]處置內容 [8]收盤價 [9]本益比 [10]連結
        try:
            url = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?response=json"
            r = _req.get(url, headers=hdrs, timeout=10, verify=False)
            data = r.json()
            seen_otc = set()
            for table in data.get("tables", []):
                for row in table.get("data", []):
                    if len(row) < 7: continue
                    sid = s(row[2])
                    if not sid: continue
                    name = _re.sub(r'\([^)]*\)', '', s(row[3])).strip()
                    period_raw = s(row[5])
                    parts = period_raw.replace('～', '~').split('~')
                    start = parts[0].strip() if parts else ""
                    end   = parts[1].strip() if len(parts) > 1 else ""
                    key = (sid, start)
                    if key in seen_otc: continue
                    seen_otc.add(key)
                    results.append({
                        "code":      sid,
                        "name":      name,
                        "market":    "上櫃",
                        "pub_date":  s(row[1]),
                        "count":     s(row[4]),
                        "condition": s(row[6]),
                        "start":     start,
                        "end":       end,
                        "measure":   "",
                    })
        except Exception as e:
            print(f"[api/disposal] OTC 失敗: {e}")

        results.sort(key=lambda x: x.get("pub_date", ""), reverse=True)
        return jsonify({"date": today, "count": len(results), "data": results})

    # ── 處置股頁面 ─────────────────────────────────────────────────────────────
    @app.route("/stock_site/news/disposal.html")
    def page_disposal():
        return send_from_directory('stock_site/news', 'disposal.html')

    # ── 交易日狀態 API ─────────────────────────────────────────────────────────
    @app.route("/api/trading_status")
    def api_trading_status():
        return jsonify(get_trading_status())

    # ── 手動觸發 Firebase 同步（支援 label 精確同步）──────────────────────────
    @app.route("/api/sync_test")
    def api_sync_test():
        token  = request.args.get("token", "")
        secret = os.environ.get("SYNC_SECRET", "")
        if not secret or token != secret:
            return jsonify({"error": "未授權"}), 403

        date  = request.args.get("date", get_today())
        label = request.args.get("label", None)   # 排程 label；None = 手動全量同步
        if label is not None:
            try:
                label = int(label)
            except ValueError:
                label = None

        import threading

        def run():
            import traceback
            print(f"[sync_test] background thread 啟動 label={label} date={date}")
            try:
                import firebase_sync
                print(f"[sync_test] import firebase_sync 成功，開始呼叫 sync_all label={label}")
                firebase_sync.sync_all(date, label=label)
                tag = f"label={label}" if label is not None else "全量"
                print(f"[sync_test] {date} {tag} 同步完成 ✅")
            except Exception as e:
                print(f"[sync_test ERROR] label={label}\n{traceback.format_exc()}")

        threading.Thread(target=run, daemon=True).start()
        tag = f"label={label}" if label is not None else "全量"
        return jsonify({"status": "started", "date": date, "label": label,
                        "message": f"{date} {tag} 同步已在背景執行"})

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

        return jsonify(result)



    @app.route("/stock_site/tools/ma_finder.html")
    def page_ma_finder():
        return send_from_directory('stock_site/tools', 'ma_finder.html')


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
            daily_ref   = firebase_db.reference(f"visitors/daily/{today}")
            today_count = (daily_ref.get() or 0) + 1
            daily_ref.set(today_count)

            total_ref = firebase_db.reference("visitors/total")
            new_total = (total_ref.get() or 0) + 1
            total_ref.set(new_total)

            return jsonify({"today": today_count, "total": new_total})

        except Exception as e:
            print(f"[Visitor] Firebase 錯誤: {e}")
            return jsonify({"error": str(e)}), 500

    # ── 維護模式 API ──────────────────────────────────────────────────────────
    # 安全設計：
    #   1. 管理員 email 只存在後端環境變數，前端永遠看不到
    #   2. 用 Google token 向 Google 驗證身份，無法偽造
    #   3. Firebase 的維護狀態只有後端可寫入（Security Rules 鎖住）
    ADMIN_EMAILS = set(
        e.strip() for e in
        os.environ.get("ADMIN_EMAILS", "llomoll5566@gmail.com").split(",")
        if e.strip()
    )

    def _verify_admin_token(token: str):
        """向 Google 驗證 Access Token，回傳 email 或 None（驗證失敗）"""
        import requests as _req
        try:
            r = _req.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if r.status_code != 200:
                return None
            email = r.json().get("email", "")
            return email if email in ADMIN_EMAILS else None
        except Exception as e:
            print(f"[Admin] token 驗證失敗: {e}")
            return None

    @app.route("/api/maintenance", methods=["GET"])
    def api_maintenance_get():
        """任何人都可以查詢目前維護狀態（前端需要知道要不要顯示維護畫面）"""
        try:
            ref  = firebase_db.reference("maintenance")
            data = ref.get() or {}
            return jsonify({
                "enabled": bool(data.get("enabled", False)),
                "message": data.get("message", "本網站暫時維護中，請稍後再試。"),
            })
        except Exception as e:
            print(f"[Maintenance] 讀取失敗: {e}")
            # Firebase 讀取失敗時預設不維護（不影響一般用戶）
            return jsonify({"enabled": False, "message": ""})

    @app.route("/api/maintenance", methods=["POST"])
    def api_maintenance_set():
        """只有管理員可以開關維護模式，需附上 Google Access Token 驗證"""
        token = request.headers.get("X-Admin-Token", "")
        if not token:
            return jsonify({"error": "未提供驗證 Token"}), 401

        email = _verify_admin_token(token)
        if not email:
            return jsonify({"error": "身份驗證失敗，無管理員權限"}), 403

        body    = request.get_json(silent=True) or {}
        enabled = bool(body.get("enabled", False))
        message = str(body.get("message", "本網站暫時維護中，請稍後再試。"))[:200]

        try:
            from datetime import datetime, timezone, timedelta
            firebase_db.reference("maintenance").set({
                "enabled":    enabled,
                "message":    message,
                "updated_by": email,
                "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            })
            print(f"[Maintenance] {'開啟' if enabled else '關閉'} by {email}")
            return jsonify({"ok": True, "enabled": enabled})
        except Exception as e:
            print(f"[Maintenance] 寫入失敗: {e}")
            return jsonify({"error": str(e)}), 500


# ── 工具函式 ──────────────────────────────────────────────────────────────────
def _extract_val(line):
    m = re.search(r"：\s*([^\s]+)\s*[張股]", line)
    return m.group(1) if m else None

def _extract_float(line):
    m = re.search(r":\s*(-?[\d.]+)", line)
    try:
        return float(m.group(1)) if m else None
    except Exception:
        return None