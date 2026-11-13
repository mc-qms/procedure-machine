#!/usr/bin/env python3
"""fetch.py - fetch one public http/https URL for the Procedure Machine.

Deterministic Python only. No LLM. No credentials, no cookies.

Usage:
  python fetch.py URL --session <session_id>
  python fetch.py URL --session-dir <path/to/session>

The session folder holds the fetched file and a fetch record:
  sessions/<session_id>/fetch_record.json  (a list, one entry per fetch)

Rules:
- http/https only. Reject private / loopback / intranet addresses.
- Follow redirects (max 5). Timeout 30 seconds. Max 25 MB per file.
- Public links only. Do not paste links to confidential, internal,
  or login-required documents.
- PDF / docx: save bytes as-is for docsrc.py. Do not parse them here.
- HTML: extract main text only, strip navigation / footer /
  boilerplate, keep headings and tables in reading order as far as
  practical. Record extracted_as: html-text.
- JavaScript-rendered pages (little extractable text) come back
  BLOCKED. Do not pretend a rendered page was read.
- On failure, print "FETCH BLOCKED: <url> - <reason>" and exit
  non-zero. Do not return partial content as if it were complete.

Exit codes: 0 = OK, 2 = BLOCKED / usage error.
"""

import argparse
import datetime
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

VERSION = "1.0"
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 30
MAX_REDIRECTS = 5
USER_AGENT = "Procedure-Machine/1.0 (+public demo, fetches public documents only)"
MIN_HTML_TEXT_CHARS = 50

# Hostnames that are never public, even if DNS resolves them.
BLOCKED_HOSTS = {"localhost"}
BLOCKED_SUFFIXES = (".local", ".intranet", ".internal", ".lan", ".home", ".corp")


def die_blocked(url, reason):
    print(f"FETCH BLOCKED: {url} - {reason}")
    sys.exit(2)


def is_private_ip(ip_str):
    # Explicit ranges only. Do NOT use ip.is_private: in Python 3.12+
    # it also flags the 198.18.0.0/15 benchmarking range, which this
    # sandbox's egress NAT uses for real public hosts (e.g. example.com
    # resolving to 198.18.33.x). That would block every public fetch.
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable is not a public address we can trust
    private_nets = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("fc00::/7"),
    ]
    return any(ip in net for net in private_nets)


def check_public_host(url):
    """Reject non-http(s) and private / loopback / intranet hosts."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        die_blocked(url, f"non-http(s) URL (scheme: {parsed.scheme or 'none'})")
    host = (parsed.hostname or "").lower()
    if not host:
        die_blocked(url, "no hostname in URL")
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES):
        die_blocked(url, f"private / intranet hostname: {host}")
    # Resolve and check every address the hostname returns.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        die_blocked(url, f"hostname did not resolve: {e}")
    for info in infos:
        ip_str = info[4][0]
        if is_private_ip(ip_str):
            die_blocked(url, f"hostname resolves to a private address: {ip_str}")
    return host


class _RedirectLimiter(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects):
        super().__init__()
        self.max_redirects = max_redirects
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > self.max_redirects:
            raise urllib.error.HTTPError(
                req.full_url, code, "too many redirects", headers, fp
            )
        # Re-validate every hop (finding 13): the first-hop check
        # alone let a public URL redirect into a private or
        # intranet address and be fetched anyway. check_public_host
        # exits with the FETCH BLOCKED message, same as a blocked
        # first hop.
        check_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _MainTextParser(HTMLParser):
    """Extract main text only. Skip script/style/nav/footer/aside/form."""

    SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "form", "noscript"}
    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "td", "th", "div"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts = []
        self.in_td = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        if tag == "td" or tag == "th":
            self.in_td = True

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth > 0:
            self.skip_depth -= 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")
            self.in_td = False

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")


def extract_html_text(raw_bytes, charset="utf-8"):
    try:
        text = raw_bytes.decode(charset, errors="replace")
    except LookupError:
        text = raw_bytes.decode("utf-8", errors="replace")
    parser = _MainTextParser()
    parser.feed(text)
    out = "".join(parser.parts)
    # Collapse blank lines, keep headings / paragraphs readable.
    lines = [html.unescape(line.strip()) for line in out.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def safe_filename(url, content_type):
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path.rstrip("/")) or "fetched"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    if not base or base in (".", ".."):
        base = "fetched"
    ct = (content_type or "").lower()
    if "pdf" in ct and not base.lower().endswith(".pdf"):
        base += ".pdf"
    elif "wordprocessingml" in ct or "msword" in ct:
        if not base.lower().endswith((".docx", ".doc")):
            base += ".docx"
    elif "html" in ct:
        base = os.path.splitext(base)[0] + ".txt"
    elif "plain" in ct or "markdown" in ct:
        if not base.lower().endswith((".txt", ".md")):
            base += ".txt"
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fetch one public URL.")
    ap.add_argument("url", nargs="?", help="public http/https URL to fetch")
    ap.add_argument("--session", help="session id (folder sessions/<id>)")
    ap.add_argument("--session-dir", help="session folder path (overrides --session)")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    if args.version:
        print(f"fetch {VERSION}")
        return 0

    if not args.url:
        ap.error("url is required (unless --version)")
    url = args.url
    if args.session_dir:
        session_dir = args.session_dir
    elif args.session:
        session_dir = os.path.join("sessions", args.session)
    else:
        session_dir = os.path.join("sessions", "default")
    os.makedirs(session_dir, exist_ok=True)

    host = check_public_host(url)

    opener = urllib.request.build_opener(_RedirectLimiter(MAX_REDIRECTS))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            final_url = resp.geturl()
            # Read in chunks, enforcing the size cap.
            chunks = []
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    die_blocked(url, f"file exceeds 25 MB cap ({total} bytes read)")
                chunks.append(chunk)
            raw = b"".join(chunks)
    except urllib.error.HTTPError as e:
        reason = {
            401: "login required (401)",
            403: "blocked / login required (403)",
            404: "not found (404)",
        }.get(e.code, f"HTTP {e.code}")
        die_blocked(url, reason)
    except urllib.error.URLError as e:
        die_blocked(url, f"fetch failed: {e.reason}")
    except (TimeoutError, socket.timeout):
        die_blocked(url, "timeout after 30 seconds")
    except Exception as e:  # noqa: BLE001 - report, do not guess
        die_blocked(url, f"fetch failed: {e}")

    if status >= 400:
        die_blocked(url, f"HTTP {status}")

    sha256 = hashlib.sha256(raw).hexdigest()[:12]
    ct = content_type.lower()
    filename = safe_filename(final_url, content_type)
    saved_path = os.path.join(session_dir, filename)

    if "html" in ct:
        text = extract_html_text(raw)
        js_stub = bool(re.search(r"javascript (is )?(required|disabled|not enabled)|enable javascript", text, re.I))
        if len(text) < MIN_HTML_TEXT_CHARS or (js_stub and len(text) < 500):
            die_blocked(
                url,
                "little extractable text "
                f"({len(text)} chars) - likely JavaScript-rendered; "
                "do not pretend a rendered page was read",
            )
        with open(saved_path, "w", encoding="utf-8") as f:
            f.write(text)
        extracted_as = "html-text"
    elif "pdf" in ct or filename.lower().endswith(".pdf"):
        with open(saved_path, "wb") as f:
            f.write(raw)
        extracted_as = "pdf"
    elif "wordprocessingml" in ct or filename.lower().endswith(".docx"):
        with open(saved_path, "wb") as f:
            f.write(raw)
        extracted_as = "docx"
    else:
        # Plain text / markdown / unknown: save bytes as-is.
        with open(saved_path, "wb") as f:
            f.write(raw)
        extracted_as = "text" if "text" in ct else "bytes"

    record = {
        "url": url,
        "final_url": final_url,
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "http_status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": sha256,
        "fetch_status": "OK",
        "extracted_as": extracted_as,
        "saved_as": saved_path,
        "host": host,
    }
    record_path = os.path.join(session_dir, "fetch_record.json")
    records = []
    if os.path.exists(record_path):
        try:
            with open(record_path, encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            records = []
    records.append(record)
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(f"FETCH OK: {url}")
    print(f"  saved: {saved_path} ({len(raw)} bytes, sha256 {sha256})")
    print(f"  final_url: {final_url}  status: {status}  type: {content_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
