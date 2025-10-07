from flask import Flask, Response, request, stream_with_context, abort
import requests, time, hashlib, random, threading
from collections import deque, defaultdict

app = Flask(__name__)

IMGUR_CDN = "https://i.imgur.com"
CLIENT_WINDOW = 10
CLIENT_MAX_REQUESTS = 6
client_lock = threading.Lock()
client_requests = defaultdict(lambda: deque())

session = requests.Session()

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

def client_allow(ip: str) -> bool:
    now = time.time()
    with client_lock:
        dq = client_requests[ip]
        while dq and dq[0] < now - CLIENT_WINDOW:
            dq.popleft()
        if len(dq) >= CLIENT_MAX_REQUESTS:
            return False
        dq.append(now)
    return True

def make_upstream_headers(prefer_mobile=False):
    ua = MOBILE_UA if prefer_mobile else DESKTOP_UA
    headers = {
        "User-Agent": ua,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://imgur.com/",
        "DNT": "1",
    }
    client_ua = request.headers.get("User-Agent")
    if client_ua:
        headers["X-Forwarded-User-Agent"] = client_ua
    return headers

@app.route("/")
def index_page():
    return """<head>
  <meta http-equiv='refresh' content='0; URL=https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js'>
</head>"""

@app.route("/<path:img_path>")
def proxy_imgur(img_path):
    if ".." in img_path:
        abort(400)

    client_ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    if not client_allow(client_ip):
        return Response("Rate limit exceeded", status=429)

    prefer_mobile = "Mobile" in (request.headers.get("User-Agent") or "")
    upstream = f"{IMGUR_CDN}/{img_path}"
    headers = make_upstream_headers(prefer_mobile)

    try:
        resp = session.get(upstream, headers=headers, stream=True, timeout=10)
    except requests.RequestException:
        abort(502, "Imgur unreachable")

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        return Response("Upstream rate limit", status=429, headers={"Retry-After": retry_after})

    if resp.status_code >= 400:
        return Response(resp.content, status=resp.status_code)

    r = Response(
        stream_with_context(resp.iter_content(8192)),
        status=resp.status_code,
        content_type=resp.headers.get("Content-Type", "image/jpeg"),
    )
    r.headers["Cache-Control"] = resp.headers.get("Cache-Control", "public, max-age=60")
    return r

# Vercel looks for "app" by default — this must exist at the module top level
# (no need for custom handler)
