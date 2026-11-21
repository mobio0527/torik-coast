#!/usr/bin/env python3
"""One-off probe (round 2): how does the CWA typhoon database page load its warning list?

Writes data/probe_history.json. Nothing here feeds the page.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "probe_history.json")
KEY = os.environ.get("CWA_KEY", "").strip()
UA = "torik-coast research page (github.com/mobio0527/torik-coast)"
TDB = "https://rdc28.cwa.gov.tw/TDB/"


def fetch(url, data=None, timeout=60):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "*/*",
                                                          "X-Requested-With": "XMLHttpRequest", "Referer": TDB})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return type(e).__name__, ""


def main():
    out = {"run": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"), "pages": [], "scripts": [], "tries": []}
    seen = set()
    for page in ("public/warning_typhoon_list/", "public/typhoon_list/"):
        status, html = fetch(TDB + page)
        srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
        inline = " ".join(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S))
        body = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S))
        out["pages"].append({"page": page, "status": status, "bytes": len(html), "scripts": srcs,
                             "inline_js": re.sub(r"\s+", " ", inline)[:1500], "visible_text": body[:900],
                             "forms": re.findall(r"<(?:form|select|input)[^>]{0,200}>", html)[:20]})
        for s in srcs:
            if "/TDB/" in s and "pages/public" in s and s not in seen:
                seen.add(s)
                st, js = fetch(s)
                hits = []
                for m in re.finditer(r"(ajax|\.post|\.get\(|fetch\(|url\s*:)", js):
                    hits.append(re.sub(r"\s+", " ", js[max(0, m.start() - 80):m.end() + 260]))
                out["scripts"].append({"src": s, "status": st, "bytes": len(js), "hits": hits[:14],
                                       "start": re.sub(r"\s+", " ", js[:700])})
                time.sleep(1)
        time.sleep(1)
    for label, url, data in (
        ("warning list GET get_warning_typhoon", TDB + "public/warning_typhoon_list/get_warning_typhoon", None),
        ("warning list POST year", TDB + "public/warning_typhoon_list/get_warning_typhoon", {"year": "2026"}),
        ("typhoon list POST year", TDB + "public/typhoon_list/get_typhoon", {"year": "2026"}),
    ):
        st, txt = fetch(url, data)
        out["tries"].append({"label": label, "status": st, "bytes": len(txt), "start": re.sub(r"\s+", " ", txt[:500])})
        time.sleep(1)
    s = json.dumps(out, ensure_ascii=False, indent=1)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(s.replace(KEY, "***") if KEY else s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
