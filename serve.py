#!/usr/bin/env python3
"""
Imgur proxy PoC with basic caching & 429 handling.

Features:
 - Session reuse
 - Realistic desktop/mobile User-Agent + browser-like headers
 - Optional UA rotation and prefer-mobile toggle (query param or auto-detect)
 - Conditional GET using stored ETag/Last-Modified
 - Simple on-disk cache under ./cache with TTL
 - If upstream returns 429 and we have cached content -> serve stale with Warning header
 - If upstream returns 429 and no cache -> return 429 (propagate Retry-After if present)
 - Very small per-client in-memory rate limiter (sliding window-ish)
"""
from flask import Flask, Response, request, stream_with_context, abort, make_response
import requests
import argparse
import logging
import ssl
import os
import time
import hashlib
import threading
import random
from pathlib import Path
from collections import deque, defaultdict

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

IMGUR_CDN = "https://i.imgur.com"
CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL = 60 * 5  # 5 minutes TTL for PoC (tune as needed)
STALE_IF_ERROR = True  # serve stale cache on 429/502

# very small per-client rate-limit settings (PoC)
CLIENT_WINDOW = 10      # seconds
CLIENT_MAX_REQUESTS = 6 # max requests per window per client IP

session = requests.Session()

# realistic-ish UAs
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

# simple in-memory metadata store: maps cache_key -> {etag, last_modified, fetched_at, path}
meta_lock = threading.Lock()
metadata = {}

# per-client recent request timestamps
client_lock = threading.Lock()
client_requests = defaultdict(lambda: deque())

def client_allow(ip: str) -> bool:
    """Very small sliding-window rate limiter per IP."""
    now = time.time()
    with client_lock:
        dq = client_requests[ip]
        # drop old
        while dq and dq[0] < now - CLIENT_WINDOW:
            dq.popleft()
        if len(dq) >= CLIENT_MAX_REQUESTS:
            return False
        dq.append(now)
    return True

def cache_path_for(key: str) -> Path:
    return CACHE_DIR / f"{key}.bin"

def key_from_path(img_path: str) -> str:
    # deterministic hash for filenames (safe characters)
    h = hashlib.sha256(img_path.encode("utf-8")).hexdigest()
    return h

def load_meta(key: str):
    with meta_lock:
        return metadata.get(key)

def save_meta(key: str, meta: dict):
    with meta_lock:
        metadata[key] = meta

def is_fresh(meta: dict) -> bool:
    if not meta:
        return False
    return (time.time() - meta.get("fetched_at", 0)) < CACHE_TTL

def stream_file(path: Path):
    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            yield chunk

def make_upstream_headers(prefer_mobile: bool = False, rotate: bool = False):
    """
    Build realistic upstream headers.
    - prefer_mobile: prefer mobile UA if True
    - rotate: randomly choose between desktop/mobile to diversify
    Also preserves the original client's UA in X-Forwarded-User-Agent.
    """
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
    # preserve original client's UA in a separate header (optional but useful for logging)
    client_ua = request.headers.get("User-Agent")
    if client_ua:
        headers["X-Forwarded-User-Agent"] = client_ua
    return headers

@app.route("/<path:img_path>")
def proxy_imgur(img_path):
    # defensive checks
    if ".." in img_path:
        abort(400, "invalid path")
    if request.method != "GET":
        abort(405)

    client_ip = request.remote_addr or "unknown"
    if not client_allow(client_ip):
        app.logger.warning("Rate limit hit for client %s", client_ip)
        return Response("Too many requests (client rate limit)", status=429)

    upstream = f"{IMGUR_CDN}/{img_path}"
    key = key_from_path(img_path)
    cache_file = cache_path_for(key)
    meta = load_meta(key)

    # decide UA mode:
    # - query param mobile=1 to force mobile
    # - query param desktop=1 to force desktop
    # - query param rotate=1 will randomly pick desktop/mobile for each request
    # - otherwise auto-detect from client's UA (if contains 'Mobile')
    prefer_mobile = False
    rotate = False
    if request.args.get("mobile") == "1":
        prefer_mobile = True
    elif request.args.get("desktop") == "1":
        prefer_mobile = False
    elif request.args.get("rotate") == "1":
        rotate = True
    else:
        # basic auto-detect
        if "Mobile" in (request.headers.get("User-Agent") or ""):
            prefer_mobile = True

    # build headers for conditional request (with realistic browser-like headers)
    headers = make_upstream_headers(prefer_mobile=prefer_mobile, rotate=rotate)
    # add conditional revalidation headers if we have them
    if meta:
        etag = meta.get("etag")
        lm = meta.get("last_modified")
        if etag:
            headers["If-None-Match"] = etag
        if lm:
            headers["If-Modified-Since"] = lm

    try:
        resp = session.get(upstream, headers=headers, stream=True, timeout=10)
    except requests.RequestException as e:
        app.logger.warning("Upstream request error for %s: %s", upstream, e)
        # if we have a cached file, serve stale
        if meta and cache_file.exists():
            app.logger.info("Serving stale cache due to upstream error for %s", img_path)
            r = make_response(stream_with_context(stream_file(cache_file)))
            # forward minimal headers from metadata
            if meta.get("content_type"):
                r.headers["Content-Type"] = meta["content_type"]
            r.headers["Warning"] = '110 - "Response is stale"'
            return r
        abort(502, "Bad Gateway")

    # handle 304 Not Modified -> serve cached file (update fetched_at)
    if resp.status_code == 304:
        if meta and cache_file.exists():
            app.logger.info("Upstream 304 — serving cached %s", img_path)
            meta["fetched_at"] = time.time()
            save_meta(key, meta)
            r = make_response(stream_with_context(stream_file(cache_file)))
            if meta.get("content_type"):
                r.headers["Content-Type"] = meta["content_type"]
            # preserve Cache-Control if present in meta
            if meta.get("cache_control"):
                r.headers["Cache-Control"] = meta["cache_control"]
            return r
        # 304 but no cache? fall through to fetch body (rare)
        app.logger.warning("Received 304 but no cache exists for %s", img_path)

    # propagate upstream 429 handling
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        app.logger.warning("Upstream 429 for %s (retry-after=%s)", img_path, retry_after)
        if meta and cache_file.exists():
            # serve stale cached content
            r = make_response(stream_with_context(stream_file(cache_file)))
            if meta.get("content_type"):
                r.headers["Content-Type"] = meta["content_type"]
            r.headers["Warning"] = '111 - "Revalidation failed"'
            # include Retry-After for clients if present
            if retry_after:
                r.headers["Retry-After"] = retry_after
            return r
        # no cache to fall back to, propagate 429 with Retry-After if available
        resp_body = resp.content or b"Too Many Requests"
        out = Response(resp_body, status=429)
        if retry_after:
            out.headers["Retry-After"] = retry_after
        return out

    # other upstream errors -> propagate or serve stale if configured
    if resp.status_code >= 400:
        app.logger.warning("Upstream returned %d for %s", resp.status_code, img_path)
        if meta and cache_file.exists() and STALE_IF_ERROR:
            r = make_response(stream_with_context(stream_file(cache_file)))
            if meta.get("content_type"):
                r.headers["Content-Type"] = meta["content_type"]
            r.headers["Warning"] = '111 - "Revalidation failed"'
            return r
        return Response(resp.content, status=resp.status_code)

    # success (200)
    # read headers we care about and write to cache atomically
    content_type = resp.headers.get("Content-Type")
    cache_control = resp.headers.get("Cache-Control")
    etag = resp.headers.get("ETag")
    last_mod = resp.headers.get("Last-Modified")

    # save to temp file then move to final to avoid races
    tmp_path = cache_file.with_suffix(".tmp")
    try:
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
        tmp_path.replace(cache_file)
        meta = {
            "etag": etag,
            "last_modified": last_mod,
            "content_type": content_type,
            "cache_control": cache_control,
            "fetched_at": time.time(),
        }
        save_meta(key, meta)
    except Exception as e:
        app.logger.exception("Failed to write cache for %s: %s", img_path, e)
        # If cache write failed, still stream directly from upstream response generator:
        # rewind the response by requesting it again (cheap for PoC) or stream from resp.raw
        try:
            resp.raw.decode_content = True
            return Response(stream_with_context(resp.raw.stream(8192)), headers={
                "Content-Type": content_type or "application/octet-stream",
                "Cache-Control": cache_control or "public, max-age=60"
            }, status=resp.status_code)
        except Exception:
            abort(502, "Bad Gateway while streaming")

    # serve cached file (fresh)
    r = make_response(stream_with_context(stream_file(cache_file)))
    if content_type:
        r.headers["Content-Type"] = content_type
    if cache_control:
        r.headers["Cache-Control"] = cache_control
    else:
        r.headers["Cache-Control"] = "public, max-age=60"
    return r

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Imgur proxy PoC (cached)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--cert", help="path to cert.pem for HTTPS (optional)")
    p.add_argument("--key", help="path to key.pem for HTTPS (optional)")
    args = p.parse_args()

    ssl_context = None
    if args.cert and args.key:
        ssl_context = (args.cert, args.key)
        app.logger.info("Starting HTTPS server on %s:%d", args.host, args.port)
    else:
        app.logger.info("Starting HTTP server on %s:%d", args.host, args.port)

    app.run(host=args.host, port=args.port, debug=True, ssl_context=ssl_context)
