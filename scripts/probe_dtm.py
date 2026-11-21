#!/usr/bin/env python3
"""One-off probe: what is inside the Ministry of the Interior 20 m DTM archive for Taitung County?

Writes data/probe_dtm.json. The archive itself is not kept.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile

URL = ("https://www.tgos.tw/MDE/VirtualDir_TC/Product/794ca116-8ceb-4c4b-af3d-3e7c46398660/"
       + urllib.parse.quote("分幅_臺東縣20MDEM(2025).zip"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "probe_dtm.json")
TMP = "/tmp/dtm.zip"


def name_of(info):
    """Zip entries from Windows tools are often Big5 without the UTF-8 flag."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", "replace")
    for enc in ("utf-8", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return info.filename


def reach(url, ua=None):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
        with urllib.request.urlopen(req, timeout=40) as r:
            r.read(2000)
            return r.status
    except Exception as e:
        return type(e).__name__ + ": " + str(e)[:80]


def main():
    out = {"url": URL}
    # is it this file, or the whole host, that refuses the runner?
    out["reach"] = {
        "tgos home": reach("https://www.tgos.tw/"),
        "tgos file, default client": reach(URL),
        "dtm.moi.gov.tw home": reach("https://dtm.moi.gov.tw/"),
        "data.gov.tw dataset page": reach("https://data.gov.tw/dataset/176927"),
    }
    started = time.time()
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "torik-coast research page (github.com/mobio0527/torik-coast)"})
        with urllib.request.urlopen(req, timeout=120) as r, open(TMP, "wb") as f:
            out["status"], out["type"], out["length_header"] = r.status, r.headers.get("Content-Type"), r.headers.get("Content-Length")
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        out["bytes"], out["seconds"] = os.path.getsize(TMP), round(time.time() - started, 1)
        with zipfile.ZipFile(TMP) as z:
            infos = z.infolist()
            out["entries"] = len(infos)
            out["total_uncompressed"] = sum(i.file_size for i in infos)
            exts = {}
            for i in infos:
                exts.setdefault(os.path.splitext(i.filename)[1].lower(), []).append(i)
            out["extensions"] = {k: len(v) for k, v in exts.items()}
            out["names"] = [[name_of(i), i.file_size] for i in infos[:80]]
            samples = []
            for ext, items in exts.items():
                if not ext:
                    continue
                for i in items[:2]:
                    with z.open(i) as f:
                        head = f.read(700)
                    try:
                        text = head.decode("utf-8")
                    except Exception:
                        text = None
                    with z.open(i) as f:
                        data = f.read() if i.file_size < 80_000_000 else b""
                    entry = {"name": name_of(i), "size": i.file_size,
                             "head_text": text, "head_hex": None if text else head[:64].hex()}
                    if text is not None and data:
                        lines = data.decode("utf-8", "replace").splitlines()
                        entry["lines"] = len(lines)
                        entry["first"] = lines[:4]
                        entry["last"] = lines[-2:]
                    samples.append(entry)
            out["samples"] = samples
    except Exception as e:
        out["error"] = type(e).__name__ + ": " + str(e)[:300]
        out["seconds"] = round(time.time() - started, 1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("names", "samples")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
