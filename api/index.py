from flask import Flask, Response, request, stream_with_context, abort, make_response
import requests
import time
import hashlib
import threading
import random
from collections import deque, defaultdict

app = Flask(__name__)

IMGUR_CDN = "https://i.imgur.com"
CACHE_TTL = 60 * 5  # 5 minutes
STALE_IF_ERROR = True

# in-memory cache only (Vercel has no persistent disk)
cache_data = {}
cache_meta = {}
meta_lock = threading.Lock()

# rate limiting (per client)
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

def key_from_path(img_path: str) -> str:
    return hashlib.sha256(img_path.encode("utf-8")).hexdigest()

def make_upstream_headers(prefer_mobile=False, rotate=False):
    if rotate:
        prefer_mobile = random.choice([True, False])
    ua = MOBILE_UA if prefer_mobile else DESKTOP_UA
    headers = {
        "User-Agent": ua,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://imgur.com/",
        "DNT": "1",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Dest": "image",
        "Upgrade-Insecure-Requests": "1",
    }
    client_ua = request.headers.get("User-Agent")
    if client_ua:
        headers["X-Forwarded-User-Agent"] = client_ua
    return headers

@app.route("/<path:img_path>")
def proxy_imgur(img_path):
    if ".." in img_path:
        abort(400, "invalid path")
    if request.method != "GET":
        abort(405)

    client_ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    if not client_allow(client_ip):
        return Response("Too many requests", status=429)

    key = key_from_path(img_path)
    upstream = f"{IMGUR_CDN}/{img_path}"

    prefer_mobile = False
    rotate = False
    if request.args.get("mobile") == "1":
        prefer_mobile = True
    elif request.args.get("rotate") == "1":
        rotate = True
    elif "Mobile" in (request.headers.get("User-Agent") or ""):
        prefer_mobile = True

    headers = make_upstream_headers(prefer_mobile=prefer_mobile, rotate=rotate)

    meta = cache_meta.get(key)
    if meta:
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    try:
        resp = session.get(upstream, headers=headers, stream=True, timeout=10)
    except requests.RequestException:
        if meta and key in cache_data:
            r = make_response(cache_data[key])
            r.headers["Content-Type"] = meta.get("content_type", "image/jpeg")
            r.headers["Warning"] = '110 - "Response is stale"'
            return r
        abort(502, "Bad Gateway")

    if resp.status_code == 304 and key in cache_data:
        meta["fetched_at"] = time.time()
        r = make_response(cache_data[key])
        r.headers["Content-Type"] = meta.get("content_type", "image/jpeg")
        return r

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        if meta and key in cache_data:
            r = make_response(cache_data[key])
            r.headers["Content-Type"] = meta.get("content_type", "image/jpeg")
            if retry_after:
                r.headers["Retry-After"] = retry_after
            return r
        out = Response("Too Many Requests", status=429)
        if retry_after:
            out.headers["Retry-After"] = retry_after
        return out

    if resp.status_code >= 400:
        if meta and key in cache_data and STALE_IF_ERROR:
            r = make_response(cache_data[key])
            r.headers["Content-Type"] = meta.get("content_type", "image/jpeg")
            r.headers["Warning"] = '111 - "Revalidation failed"'
            return r
        return Response(resp.content, status=resp.status_code)

    body = resp.content
    meta = {
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
        "content_type": resp.headers.get("Content-Type", "image/jpeg"),
        "fetched_at": time.time(),
    }

    cache_data[key] = body
    cache_meta[key] = meta

    r = make_response(body)
    r.headers["Content-Type"] = meta["content_type"]
    return r

# For Vercel
def handler(event, context):
    return app(event, context)
