#!/usr/bin/env python3
"""
proxy_server.py

A minimal threaded HTTP/HTTPS proxy with:
 - CONNECT tunnelling support
 - Password protection via PROXY_PASSWORD env var
 - Whitelist (PROXY_WHITELIST env var, default imgur hosts)
 - Strips auth headers before forwarding (no secret leaks)

Deploy on Render (Web Service). Render provides a PORT env var we listen on.
"""

import os
import socket
import threading
import base64
import time
from urllib.parse import urlparse

# Config from environment
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.getenv("PORT", "8080"))
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")  # REQUIRED
WHITELIST_CSV = os.getenv("PROXY_WHITELIST", "imgur.com,i.imgur.com,s.imgur.com,m.imgur.com")

if not PROXY_PASSWORD:
    raise SystemExit("ERROR: PROXY_PASSWORD environment variable is required (do NOT commit it).")

WHITELIST = set(h.strip().lower() for h in WHITELIST_CSV.split(",") if h.strip())

# Runtime tuning
RECV_BUF = 65536
HEADER_TIMEOUT = 5.0

def debug(*args):
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), *args, flush=True)

def read_until_double_crlf(client_sock, timeout=HEADER_TIMEOUT):
    client_sock.settimeout(timeout)
    data = b""
    try:
        while b"\r\n\r\n" not in data:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            data += chunk
            # Safety cap
            if len(data) > 1024 * 1024:
                break
    except socket.timeout:
        pass
    except Exception:
        pass
    finally:
        client_sock.settimeout(None)
    return data

def parse_request_head(head_bytes):
    try:
        head_text = head_bytes.decode("iso-8859-1")
    except Exception:
        head_text = head_bytes.decode("utf-8", errors="ignore")
    lines = head_text.split("\r\n")
    request_line = lines[0] if lines else ""
    parts = request_line.split(" ", 2)
    if len(parts) < 2:
        return None, None, None, {}
    method = parts[0]
    path = parts[1]
    proto = parts[2] if len(parts) > 2 else "HTTP/1.1"
    headers = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return method, path, proto, headers

def check_auth(headers):
    # Accept either Proxy-Authorization: Basic ... or X-Proxy-Password: secret
    # Return True if matches
    # Don't leak the credential: we'll strip headers later.
    pa = headers.get("proxy-authorization")
    if pa:
        parts = pa.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "basic":
            try:
                raw = base64.b64decode(parts[1]).decode("utf-8", errors="ignore")
                # raw is "username:password" or just "password"
                if ":" in raw:
                    _, password = raw.split(":", 1)
                else:
                    password = raw
                return password == PROXY_PASSWORD
            except Exception:
                return False
    xp = headers.get("x-proxy-password")
    if xp:
        return xp == PROXY_PASSWORD
    return False

def hostname_allowed(hostname):
    if not hostname:
        return False
    host = hostname.lower().strip()
    # strip optional port
    if ":" in host:
        host = host.split(":", 1)[0]
    # exact or subdomain match
    if host in WHITELIST:
        return True
    for w in WHITELIST:
        if host.endswith("." + w):
            return True
    return False

def forward_data(src, dst):
    try:
        while True:
            data = src.recv(RECV_BUF)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        try:
            src.shutdown(socket.SHUT_RD)
        except Exception:
            pass

def handle_client(client_sock, client_addr):
    try:
        head = read_until_double_crlf(client_sock)
        if not head:
            client_sock.close()
            return

        method, path, proto, headers = parse_request_head(head)
        if not method:
            client_sock.close()
            return

        debug(f"{client_addr} -> {method} {path}")

        # Check auth
        if not check_auth(headers):
            # 407 Proxy Authentication Required
            resp = (
                "HTTP/1.1 407 Proxy Authentication Required\r\n"
                "Proxy-Authenticate: Basic realm=\"proxy\"\r\n"
                "Content-Length: 0\r\n\r\n"
            ).encode()
            client_sock.sendall(resp)
            client_sock.close()
            debug(f"{client_addr} -> auth failed")
            return

        # Handle CONNECT (HTTPS tunneling)
        if method.upper() == "CONNECT":
            # path is like "host:port"
            host_port = path
            if ":" in host_port:
                host, port_s = host_port.split(":", 1)
                try:
                    port = int(port_s)
                except Exception:
                    port = 443
            else:
                host = host_port
                port = 443

            if not hostname_allowed(host):
                client_sock.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                client_sock.close()
                debug(f"{client_addr} -> CONNECT host not allowed: {host}")
                return

            # connect to remote
            try:
                remote = socket.create_connection((host, port), timeout=10)
            except Exception as e:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                client_sock.close()
                debug(f"{client_addr} -> CONNECT failed to {host}:{port} : {e}")
                return

            # Acknowledge to client and start tunneling
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            # Start forwarding both ways
            t1 = threading.Thread(target=forward_data, args=(client_sock, remote), daemon=True)
            t2 = threading.Thread(target=forward_data, args=(remote, client_sock), daemon=True)
            t1.start()
            t2.start()
            # wait for both to finish
            t1.join()
            t2.join()
            try:
                remote.close()
            except Exception:
                pass
            try:
                client_sock.close()
            except Exception:
                pass
            debug(f"{client_addr} -> CONNECT tunnel closed for {host}:{port}")
            return

        # Non-CONNECT: standard HTTP proxy usage
        # Build the target URL/host
        # If the path is absolute URL -> use it. Otherwise use Host header.
        target_url = None
        if path.lower().startswith("http://") or path.lower().startswith("https://"):
            target_url = path
        else:
            host_header = headers.get("host")
            if host_header:
                target_url = f"http://{host_header}{path}"

        if not target_url:
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            client_sock.close()
            return

        parsed = urlparse(target_url)
        target_host = parsed.hostname
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if not hostname_allowed(target_host):
            client_sock.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            client_sock.close()
            debug(f"{client_addr} -> HTTP host not allowed: {target_host}")
            return

        # Connect to target
        try:
            remote = socket.create_connection((target_host, target_port), timeout=10)
        except Exception as e:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            client_sock.close()
            debug(f"{client_addr} -> connect to origin failed: {e}")
            return

        # Prepare the request to send to remote: strip Proxy-Authorization / X-Proxy-Password
        try:
            head_text = head.decode("iso-8859-1")
        except Exception:
            head_text = head.decode("utf-8", errors="ignore")

        # Remove proxy auth headers before sending upstream
        safe_lines = []
        for line in head_text.split("\r\n"):
            if not line:
                continue
            lower = line.lower()
            if lower.startswith("proxy-authorization:") or lower.startswith("x-proxy-password:"):
                continue
            # If path was absolute URL, convert request line to path-only for origin
            if line.startswith(("GET ", "POST ", "PUT ", "DELETE ", "HEAD ", "OPTIONS ", "PATCH ")):
                parts = line.split(" ", 2)
                method_line = parts[0]
                request_target = parts[1]
                version = parts[2] if len(parts) > 2 else "HTTP/1.1"
                if request_target.startswith("http://") or request_target.startswith("https://"):
                    p = urlparse(request_target)
                    path_only = p.path or "/"
                    if p.query:
                        path_only += "?" + p.query
                    safe_lines.append(f"{method_line} {path_only} {version}")
                    continue
            safe_lines.append(line)

        # Recompose and send headers
        final_head = "\r\n".join(safe_lines) + "\r\n\r\n"
        remote.sendall(final_head.encode("iso-8859-1"))

        # If we read any body bytes after headers, forward them
        header_end = head.find(b"\r\n\r\n")
        body_tail = b""
        if header_end != -1 and len(head) > header_end + 4:
            body_tail = head[header_end + 4 :]
            if body_tail:
                remote.sendall(body_tail)

        # Now pipe remaining data both ways until close
        t_up = threading.Thread(target=forward_data, args=(client_sock, remote), daemon=True)
        t_down = threading.Thread(target=forward_data, args=(remote, client_sock), daemon=True)
        t_up.start()
        t_down.start()
        t_up.join()
        t_down.join()
        try:
            remote.close()
        except Exception:
            pass
        try:
            client_sock.close()
        except Exception:
            pass
        debug(f"{client_addr} -> HTTP session closed for {target_host}")

    except Exception as e:
        debug(f"Exception handling client {client_addr}: {e}")
        try:
            client_sock.close()
        except Exception:
            pass

def start_server():
    debug(f"Starting proxy on {LISTEN_HOST}:{LISTEN_PORT}")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(200)
    try:
        while True:
            client_sock, client_addr = server.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        debug("Shutting down.")
    finally:
        try:
            server.close()
        except Exception:
            pass

if __name__ == "__main__":
    start_server()
