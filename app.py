#!/usr/bin/env python3
"""Tiny uptime watchdog for Deplexo's free tier (128 MB RAM).

Standard library only. Serves a small status page on $PORT and checks
a list of URLs every few minutes. When a site goes down (2 consecutive
failures) or recovers, it posts to a Discord webhook.

Configuration (environment variables):
  PORT                port to listen on (default 8000)
  CHECK_URLS          comma-separated URLs to watch
                      (default: the user's public pages)
  CHECK_INTERVAL_SEC  seconds between check rounds (default 300)
  DISCORD_WEBHOOK_URL Discord webhook for down/recovery alerts
                      (optional; without it alerts are only logged)
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JST = timezone(timedelta(hours=9))

PORT = int(os.environ.get("PORT", "8000"))
CHECK_URLS = [
    u.strip()
    for u in os.environ.get(
        "CHECK_URLS",
        "https://varelser.github.io/,"
        "https://monosphere.pages.dev/,"
        "https://varelser.github.io/nurse-news.html",
    ).split(",")
    if u.strip()
]
INTERVAL = int(os.environ.get("CHECK_INTERVAL_SEC", "300"))
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
UA = {"User-Agent": "varelser-watchdog/1.0 (+https://varelser.github.io/)"}

STARTED = time.time()
state = {
    url: {"up": None, "fails": 0, "code": None, "checked_at": None, "alerted": False}
    for url in CHECK_URLS
}
lock = threading.Lock()
rounds = 0


def now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def notify(text: str) -> None:
    print(f"[notify] {text}", flush=True)
    if not WEBHOOK:
        print("[notify] DISCORD_WEBHOOK_URL not set; skipping webhook", flush=True)
        return
    try:
        req = urllib.request.Request(
            WEBHOOK,
            data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json", **UA},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[notify] webhook -> HTTP {resp.status}", flush=True)
    except Exception as e:  # noqa: BLE001 - alerting must never kill the bot
        print(f"[notify] webhook failed: {e}", flush=True)


def check_one(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers=UA, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read(1024)
            return 200 <= resp.status < 400, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def check_loop() -> None:
    global rounds
    while True:
        for url in CHECK_URLS:
            ok, detail = check_one(url)
            event = None
            with lock:
                st = state[url]
                st["checked_at"] = now_jst()
                st["code"] = detail
                if ok:
                    if st["alerted"]:
                        event = f"✅ 復旧しました: {url} ({detail})"
                    st["up"] = True
                    st["fails"] = 0
                    st["alerted"] = False
                else:
                    st["fails"] += 1
                    st["up"] = False
                    if st["fails"] >= 2 and not st["alerted"]:
                        st["alerted"] = True
                        event = f"🔴 ダウン検知: {url} ({detail}) 2回連続で失敗しました"
            if event:
                notify(event)
        rounds += 1
        print(f"[check] round {rounds} done at {now_jst()}", flush=True)
        time.sleep(INTERVAL)


def status_page() -> bytes:
    with lock:
        snapshot = {u: dict(s) for u, s in state.items()}
    uptime_min = int((time.time() - STARTED) // 60)
    rows = ""
    for url, st in snapshot.items():
        mark = "⏳" if st["up"] is None else ("🟢" if st["up"] else "🔴")
        rows += (
            f"<tr><td>{mark}</td><td>{url}</td><td>{st['code'] or '-'}</td>"
            f"<td>{st['checked_at'] or '-'}</td></tr>"
        )
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>varelser watchdog</title></head>
<body style="font-family:system-ui,sans-serif;margin:2rem;max-width:720px">
<h1>varelser watchdog</h1>
<p>稼働時間: {uptime_min} 分 / チェック回数: {rounds} / Webhook: {'設定済み' if WEBHOOK else '未設定'}</p>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th></th><th>URL</th><th>結果</th><th>最終チェック</th></tr>
{rows}
</table>
<p style="color:#666">ダウン（2回連続失敗）と復旧のときだけ Discord に通知します。</p>
</body></html>"""
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/test-alert":
            notify("🧪 varelser watchdog のテスト通知です。この通知が届いていれば Discord 連携は正常です。")
            body = "test alert sent (see logs if webhook is unset)".encode()
            self.send_response(200)
        else:
            body = status_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter logs
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    print(f"[start] watchdog on port {PORT}, {len(CHECK_URLS)} urls, interval {INTERVAL}s", flush=True)
    threading.Thread(target=check_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
