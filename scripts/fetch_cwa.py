#!/usr/bin/env python3
"""Fetch open data from Taiwan's Central Weather Administration (CWA) for the Torik (都歷) coast page.

Stage A (this version): probe each dataset and write a compact description of what came back,
so the page parser can be written against the real response format.

The API key is read from the CWA_KEY environment variable and is never written to disk.
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

API = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
TPE = timezone(timedelta(hours=8))

# id -> (label, confirmed?)  "confirmed" means the id was checked against CWA documentation.
DATASETS = {
    # second-round probe: find the dataset that lists marine stations with names and coordinates
    "O-B0076-001@file": ("海象觀測測站資料（檔案介面，候選）", False),
    "O-B0075-002": ("海象監測－30 天（候選）", False),
    "C-B0052-001": ("測站資料（候選）", False),
    "C-B0052-001@file": ("測站資料（檔案介面，候選）", False),
    "O-B0075-001@file": ("海象監測 48 小時（檔案介面，候選）", False),
}

FILE_API = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/"

# Places near Torik used to pull out sample records.
NEAR = ("成功", "東河", "都蘭", "都歷", "富岡", "長濱", "臺東", "台東", "綠島", "蘭嶼")
NAME_KEY = re.compile(r"(station|location|county|town).*(name|id)$|^(StationID|StationId|LocationName)$", re.I)


def scrub(text, key):
    return text.replace(key, "***") if key else text


def shape(node, depth=0):
    """Describe the structure of a JSON value without copying its data."""
    if depth > 12:
        return "…"
    if isinstance(node, dict):
        return {k: shape(v, depth + 1) for k, v in list(node.items())[:40]}
    if isinstance(node, list):
        return {"__list_len__": len(node), "__first__": shape(node[0], depth + 1) if node else None}
    return type(node).__name__ + ":" + str(node)[:40]


def trim(node, depth=0):
    """Copy a record, keeping only the first few items of long lists."""
    if isinstance(node, dict):
        return {k: trim(v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        keep = 4 if depth > 0 else 12
        out = [trim(v, depth + 1) for v in node[:keep]]
        if len(node) > keep:
            out.append("…(%d more)" % (len(node) - keep))
        return out
    return node


def walk(node, names, samples):
    if isinstance(node, dict):
        hit = False
        for k, v in node.items():
            if isinstance(v, str) and NAME_KEY.search(k):
                names.setdefault(k, set()).add(v)
                if any(n in v for n in NEAR):
                    hit = True
        if hit and len(samples) < 14:
            text = json.dumps(trim(node), ensure_ascii=False)
            if len(text) < 9000:
                samples.append(trim(node))
        for v in node.values():
            walk(v, names, samples)
    elif isinstance(node, list):
        for v in node:
            walk(v, names, samples)


def fetch(dataset_id, key):
    if dataset_id.endswith("@file"):
        url = FILE_API + dataset_id[:-5] + "?" + urllib.parse.urlencode({"Authorization": key, "downloadType": "WEB", "format": "JSON"})
    else:
        url = API + dataset_id + "?" + urllib.parse.urlencode({"Authorization": key, "format": "JSON"})
    started = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=90) as r:
            body = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    except Exception as e:  # network errors
        return {"http": None, "error": scrub(repr(e), key), "seconds": round(time.time() - started, 1)}
    info = {"http": code, "bytes": len(body), "seconds": round(time.time() - started, 1)}
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        info["error"] = "not JSON: " + scrub(body[:300].decode("utf-8", "replace"), key)
        return info
    if code != 200:
        info["error"] = scrub(json.dumps(data, ensure_ascii=False)[:500], key)
        return info
    names, samples = {}, []
    walk(data, names, samples)
    info["shape"] = shape(data)
    info["names"] = {k: sorted(v)[:400] for k, v in names.items()}
    info["near_samples"] = samples
    return info


def main():
    key = os.environ.get("CWA_KEY", "").strip()
    os.makedirs(os.path.join(OUT, "probe"), exist_ok=True)
    now = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    status = {"updated": now, "timezone": "Asia/Taipei", "stage": "probe", "datasets": []}
    if not key:
        status["note"] = "CWA_KEY secret is not set; nothing was fetched."
    else:
        for dataset_id, (label, confirmed) in DATASETS.items():
            info = fetch(dataset_id, key)
            with open(os.path.join(OUT, "probe", dataset_id.replace("@", "_") + ".json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            status["datasets"].append({
                "id": dataset_id, "label": label, "confirmed": confirmed,
                "ok": info.get("http") == 200 and "error" not in info,
                "http": info.get("http"), "bytes": info.get("bytes"), "error": info.get("error"),
            })
            time.sleep(1)
    with open(os.path.join(OUT, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in status.items() if k != "datasets"}, ensure_ascii=False))
    for d in status["datasets"]:
        print(d["id"], d["http"], d["bytes"], "ok" if d["ok"] else d.get("error"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
