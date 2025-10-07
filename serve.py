#!/usr/bin/env python3
"""
Minimal Imgur image proxy PoC.

Routes:
  /imgur/<path:img_path>  -> proxies https://i.imgur.com/<img_path>

Examples:
  http://localhost:8080/imgur/abcd.jpg
  https://localhost:8443/imgur/abcd.png

Run (HTTP):
  python imgur_proxy.py --port 8080

Run (HTTPS) with cert/key:
  python imgur_proxy.py --port 8443 --cert cert.pem --key key.pem
"""
from flask import Flask, Response, request, stream_with_context, abort
import requests
import argparse
import logging
import ssl

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

IMGUR_CDN = "https://i.imgur.com"  # we proxy images from here only (tight scope)

def stream_resp(r):
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            yield chunk

@app.route("/<path:img_path>")
def proxy_imgur(img_path):
    # build upstream URL
    upstream = f"{IMGUR_CDN}/{img_path}"

    # optional: forbid local paths / weird hosts (defense-in-depth)
    if ".." in img_path:
        abort(400, "invalid path")

    # forward only GET for this simple PoC
    if request.method != "GET":
        abort(405)

    # Stream from upstream
    try:
        upstream_resp = requests.get(upstream, stream=True, timeout=10)
    except requests.RequestException as e:
        app.logger.warning("upstream request failed: %s", e)
        abort(502, "Bad Gateway")

    # If upstream returns not-found or error, relay status
    if upstream_resp.status_code >= 400:
        return Response(upstream_resp.content, status=upstream_resp.status_code)

    # Prepare headers we want to forward (safe subset)
    headers = {}
    if "Content-Type" in upstream_resp.headers:
        headers["Content-Type"] = upstream_resp.headers["Content-Type"]
    if "Content-Length" in upstream_resp.headers:
        headers["Content-Length"] = upstream_resp.headers["Content-Length"]
    # Allow client-side caching similar to upstream (or override)
    if "Cache-Control" in upstream_resp.headers:
        headers["Cache-Control"] = upstream_resp.headers["Cache-Control"]
    else:
        # conservative default
        headers["Cache-Control"] = "public, max-age=60"

    # Stream response body
    return Response(stream_with_context(stream_resp(upstream_resp)), headers=headers, status=upstream_resp.status_code)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Minimal Imgur proxy PoC")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--cert", help="path to cert.pem for HTTPS (optional)")
    p.add_argument("--key", help="path to key.pem for HTTPS (optional)")
    args = p.parse_args()

    ssl_context = None
    if args.cert and args.key:
        # Use built-in Flask (Werkzeug) dev server with SSL context for PoC only
        ssl_context = (args.cert, args.key)
        app.logger.info("Starting HTTPS server on %s:%d", args.host, args.port)
    else:
        app.logger.info("Starting HTTP server on %s:%d", args.host, args.port)

    app.run(host=args.host, port=args.port, debug=True, ssl_context=ssl_context)
