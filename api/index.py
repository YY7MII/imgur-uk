from flask import Flask, Response, request, stream_with_context, abort, jsonify
import requests, time, threading
from collections import deque, defaultdict
import re

app = Flask(__name__)

IMGUR_CDN = "https://i.imgur.com"
IMGUR_API = "https://api.imgur.com/3/album"
CLIENT_WINDOW = 10
CLIENT_MAX_REQUESTS = 6

client_lock = threading.Lock()
client_requests = defaultdict(lambda: deque())

session = requests.Session()
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
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

def make_headers():
    return {
        "User-Agent": DESKTOP_UA,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://imgur.com/",
    }

@app.route("/")
def index_page():
    return """<head>
  <meta http-equiv='refresh' content='0; URL=https://raw.githubusercontent.com/YY7MII/imgur-uk/main/imgur-proxy.user.js'>
</head>"""

# ---- proxy single images ----
@app.route("/i/<path:img_path>")
def proxy_image(img_path):
    if ".." in img_path:
        abort(400)
    client_ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    if not client_allow(client_ip):
        return Response("Rate limit exceeded", status=429)

    img_path = re.sub(r'_\d+x(\.(?:png|jpg|jpeg|gif))$', r'\1', img_path)
    upstream = f"{IMGUR_CDN}/{img_path}"
    headers = make_headers()

    try:
        resp = session.get(upstream, headers=headers, stream=True, timeout=10)
    except requests.RequestException:
        abort(502, "Imgur unreachable")

    if resp.status_code >= 400:
        return Response(resp.content, status=resp.status_code)

    r = Response(
        stream_with_context(resp.iter_content(8192)),
        status=resp.status_code,
        content_type=resp.headers.get("Content-Type", "image/jpeg"),
    )
    r.headers["Cache-Control"] = resp.headers.get("Cache-Control", "public, max-age=60")
    return r

# ---- proxy albums as JSON ----
@app.route("/a/<album_id>")
@app.route("/gallery/<album_id>")
def proxy_album(album_id):
    client_ip = request.headers.get("x-forwarded-for", request.remote_addr or "unknown")
    if not client_allow(client_ip):
        return Response("Rate limit exceeded", status=429)

    headers = {"Authorization": "Client-ID 5466e1234567890"}  # Replace with a valid Imgur Client-ID
    try:
        resp = session.get(f"{IMGUR_API}/{album_id}", headers=headers, timeout=10)
        data = resp.json()
    except Exception:
        abort(502, "Imgur API unreachable")

    if not data.get("success"):
        return Response("Album not found", status=404)

    # Return only image hashes and extensions
    images = [
        f"/i/{img['id']}{img.get('type','').split('/')[-1].replace('jpeg','jpg') if img.get('type') else '.jpg'}"
        for img in data["data"].get("images", [])
    ]
    return jsonify({"images": images})

# Vercel requires this at top-level
app = app
