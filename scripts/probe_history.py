#!/usr/bin/env python3
"""One-off probe: which sources of past typhoon and station data can this runner reach?

Writes data/probe_history.json. Nothing here feeds the page. The API key is read from
CWA_KEY and is removed from everything that is written.
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
OPEN = "https://opendata.cwa.gov.tw"


def scrub(s):
    return s.replace(KEY, "***") if KEY else s


def shape(v, depth=0):
    """Structure of a JSON value with short samples, lists reduced to their first item."""
    if depth > 9:
        return "..."
    if isinstance(v, dict):
        return {k: shape(x, depth + 1) for k, x in list(v.items())[:40]}
    if isinstance(v, list):
        return {"_list_len": len(v), "_first": shape(v[0], depth + 1) if v else None}
    s = str(v)
    return s if len(s) <= 70 else s[:70] + "..."


def fetch(url, data=None, limit=40_000_000, timeout=90, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=h)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(limit)
            return {"status": r.status, "type": r.headers.get("Content-Type"), "bytes": len(raw),
                    "seconds": round(time.time() - started, 1)}, raw
    except urllib.error.HTTPError as e:
        return {"status": e.code, "seconds": round(time.time() - started, 1)}, b""
    except Exception as e:
        return {"error": type(e).__name__ + ": " + str(e)[:160], "seconds": round(time.time() - started, 1)}, b""


def describe(info, raw, want="json", ids=False, links=None):
    if not raw:
        return info
    txt = raw.decode("utf-8", "replace")
    if want == "json":
        try:
            info["shape"] = shape(json.loads(txt))
            return info
        except Exception:
            info["not_json"] = True
    if want == "csv":
        info["first_lines"] = txt.splitlines()[:4]
        return info
    title = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S | re.I)
    if title:
        info["title"] = title.group(1).strip()[:120]
    if ids:
        found = {}
        for m in re.finditer(r"([A-Z]-[A-Z]\d{4}-\d{3})", txt):
            around = re.sub(r"<[^>]+>|\s+", " ", txt[max(0, m.start() - 160):m.end() + 160])
            found.setdefault(m.group(1), around.strip()[:200])
        info["dataset_ids"] = found
    if links:
        info["links"] = sorted(set(re.findall(links, txt)))[:60]
    if "title" not in info and "dataset_ids" not in info:
        info["text_start"] = re.sub(r"\s+", " ", txt[:300])
    return info


def main():
    results = []

    def run(label, url, **kw):
        want, ids, links = kw.pop("want", "json"), kw.pop("ids", False), kw.pop("links", None)
        info, raw = fetch(url, **kw)
        entry = {"label": label, "url": scrub(url)}
        entry.update(describe(info, raw, want, ids, links))
        results.append(entry)
        print(label, entry.get("status", entry.get("error")), entry.get("bytes"))
        time.sleep(1)
        return raw

    auth = "Authorization=" + KEY

    # 1. CWA open data: typhoon datasets on both interfaces
    for ds in ("W-C0034-005", "W-C0034-001", "W-C0034-002", "W-C0034-004"):
        run("datastore " + ds, "%s/api/v1/rest/datastore/%s?%s&format=JSON" % (OPEN, ds, auth))
        run("fileapi " + ds, "%s/fileapi/v1/opendataapi/%s?%s&downloadType=WEB&format=JSON" % (OPEN, ds, auth))

    # 2. CWA open data: how far back does the history interface keep each dataset?
    for ds in ("O-A0001-001", "O-A0003-001", "O-B0075-001", "W-C0034-005", "W-C0034-001"):
        run("history " + ds, "%s/historyapi/v1/getMetadata/%s?%s" % (OPEN, ds, auth))

    # 3. CWA open data: catalogue pages, to read real dataset IDs for climate, marine and typhoon data
    for page in ("dataset/climate?page=1", "dataset/climate?page=2", "dataset/climate?page=3",
                 "dataset/observation?page=1", "dataset/warning?page=1", "dataset/all?page=1"):
        run("catalogue " + page, "%s/%s" % (OPEN, page), want="html", ids=True)

    # 4. CWA open data: station climate datasets (IDs to be confirmed by the catalogue above)
    for ds in ("C-B0024-001", "C-B0024-002", "C-B0025-001", "C-B0026-001", "C-B0027-001"):
        run("datastore " + ds, "%s/api/v1/rest/datastore/%s?%s&format=JSON&limit=2" % (OPEN, ds, auth))
        run("fileapi " + ds, "%s/fileapi/v1/opendataapi/%s?%s&downloadType=WEB&format=JSON" % (OPEN, ds, auth))

    # 5. CODiS (climate observation query service): one day of hourly data at Chenggong during typhoon Champi
    run("CODiS home", "https://codis.cwa.gov.tw/", want="html")
    run("CODiS station list", "https://codis.cwa.gov.tw/api/station_list")
    for stn, kind in (("467610", "cwb"), ("C0SA30", "auto_C0")):
        run("CODiS hourly %s 2026-10-23" % stn, "https://codis.cwa.gov.tw/api/station?",
            data={"date": "2026-10-23T00:00:00.000+08:00", "type": "report_date", "stn_ID": stn,
                  "stn_type": kind, "more": "", "start": "2026-10-23T00:00:00", "end": "2026-10-23T23:59:59",
                  "item": ""},
            headers={"Referer": "https://codis.cwa.gov.tw/StationData"})

    # 6. CWA typhoon database
    run("Typhoon database home", "https://rdc28.cwa.gov.tw/TDB/", want="html",
        links=r'href="([^"]*(?:typhoon|warning|public)[^"]*)"')
    run("Typhoon database list", "https://rdc28.cwa.gov.tw/TDB/public/typhoon_list/", want="html",
        links=r'href="([^"]*(?:typhoon|warning|public)[^"]*)"')
    run("Typhoon database warnings", "https://rdc28.cwa.gov.tw/TDB/public/warning_typhoon_list/", want="html",
        links=r'href="([^"]*(?:typhoon|warning|public)[^"]*)"')

    # 7. IBTrACS (NOAA): provisional tracks, last three years
    base = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/"
    run("IBTrACS folder", base, want="html", links=r'href="(ibtracs[^"]+)"')
    raw = run("IBTrACS active storms", base + "ibtracs.ACTIVE.list.v04r01.csv", want="csv", limit=2_000_000)
    info, raw = fetch(base + "ibtracs.last3years.list.v04r01.csv", limit=60_000_000, timeout=180)
    entry = {"label": "IBTrACS last three years", "url": base + "ibtracs.last3years.list.v04r01.csv"}
    entry.update(info)
    if raw:
        lines = raw.decode("utf-8", "replace").splitlines()
        entry["lines"] = len(lines)
        entry["header"] = lines[0][:400]
        rows_2026 = [l.split(",") for l in lines[2:] if l.split(",")[1:2] == ["2026"]]
        wp = [r for r in rows_2026 if len(r) > 6 and r[3] == "WP"]
        entry["wp_2026_storms"] = sorted({r[5] for r in wp})
        entry["wp_2026_last_time"] = max((r[6] for r in wp), default=None)
        entry["sample_row"] = ",".join(wp[-1][:30]) if wp else None
    results.append(entry)

    out = {"run": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"), "results": results}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(scrub(json.dumps(out, ensure_ascii=False, indent=1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
