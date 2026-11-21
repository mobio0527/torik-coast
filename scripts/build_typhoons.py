#!/usr/bin/env python3
"""Build data/typhoons.json: typhoons with a CWA warning in the past year, seen from the Torik (都歷) coast.

Sources (all confirmed reachable from a GitHub runner on 2026-11-21):
  CWA Typhoon Database   list of typhoons with warnings, warning period, values near Taiwan
  NOAA IBTrACS v04r01    track positions (provisional for the current season)
  CWA CODiS              hourly observations at Chenggong (467610) and Torik (C0SA30)

No API key is needed. CODiS and the Typhoon Database are public query pages rather than
documented APIs, so every request is paced and a failed request is recorded, not retried hard.
"""
import csv
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT = os.path.join(ROOT, "typhoons.json")
TPE = timezone(timedelta(hours=8))
UA = "torik-coast research page (github.com/mobio0527/torik-coast)"
TORIK = (23.0236, 121.3340)
TDB = "https://rdc28.cwa.gov.tw/TDB/public/"
CODIS = "https://codis.cwa.gov.tw/api/station?"
IBTRACS = ("https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
           "v04r01/access/csv/ibtracs.last3years.list.v04r01.csv")
STATIONS = [  # id, CODiS station type, name, km from Torik, altitude (from the live weather feed)
    {"id": "467610", "type": "cwb", "name": "成功", "km": 9.1},
    {"id": "C0SA30", "type": "auto_C0", "name": "都歷", "km": 1.1},
]
INTENSITY = {"s": "強烈", "m": "中度", "w": "輕度"}


def http(url, data=None, timeout=120, limit=80_000_000, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    last = None
    for pause in (0, 6, 20):
        time.sleep(pause)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=h), timeout=timeout) as r:
                return r.read(limit)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                raise
            last = e
        except Exception as e:
            last = e
    raise last


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (f <= -90 or math.isnan(f)) else f


def km_from_torik(lat, lon):
    p1, p2 = math.radians(TORIK[0]), math.radians(lat)
    dl = math.radians(lon - TORIK[1])
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def tdb(path, year):
    raw = http(TDB + path, {"year": str(year)}, headers={"X-Requested-With": "XMLHttpRequest", "Referer": TDB})
    return json.loads(raw.decode("utf-8-sig"))


def parse_local(s):
    """'2026-10-21 23:30:00' in Taiwan time -> aware datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TPE)


def tracks(names_by_year):
    """IBTrACS rows for the wanted (year, NAME) pairs -> {(year, name): [[iso, lat, lon, wind_kt, pres], ...]}"""
    raw = http(IBTRACS, timeout=240).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(raw))
    by_sid = {}
    for r in reader:
        if r.get("BASIN") != "WP":
            continue
        key = (r.get("SEASON", "").strip(), r.get("NAME", "").strip().upper())
        if key not in names_by_year:
            continue
        lat, lon = num(r.get("LAT")), num(r.get("LON"))
        if lat is None or lon is None:
            continue
        try:
            t = datetime.strptime(r["ISO_TIME"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(TPE)
        except Exception:
            continue
        by_sid.setdefault((key, r["SID"]), {"type": r.get("TRACK_TYPE", "").strip(), "rows": []})["rows"].append(
            [t.isoformat(timespec="minutes"), round(lat, 2), round(lon, 2), num(r.get("USA_WIND")), num(r.get("USA_PRES"))])
    out = {}
    for (key, sid), v in by_sid.items():
        if key not in out or len(v["rows"]) > len(out[key]["rows"]):
            out[key] = {"sid": sid, "type": v["type"], "rows": sorted(v["rows"])}
    return out


def codis_day(st, day):
    """One day of hourly observations. Values are for the hour ending at the stated time."""
    d = day.strftime("%Y-%m-%d")
    raw = http(CODIS, {"date": d + "T00:00:00.000+08:00", "type": "report_date", "stn_ID": st["id"],
                       "stn_type": st["type"], "more": "", "start": d + "T00:00:00", "end": d + "T23:59:59", "item": ""},
               headers={"Referer": "https://codis.cwa.gov.tw/StationData"}, timeout=60)
    data = json.loads(raw.decode("utf-8-sig"))
    rows = []
    for block in data.get("data") or []:
        for r in block.get("dts") or []:
            def g(a, b, r=r):
                v = num((r.get(a) or {}).get(b))
                # negative codes mark trace rain or a missing reading; neither is a measurement
                return None if (v is not None and v < 0 and a != "AirTemperature") else v
            rows.append({"t": (r.get("DataTime") or "")[:16] + "+08:00", "wind": g("WindSpeed", "Mean"),
                         "wind_dir": g("WindDirection", "Mean"), "gust": g("PeakGust", "Maximum"),
                         "pressure": g("StationPressure", "Instantaneous"), "rain": g("Precipitation", "Accumulation"),
                         "temp": g("AirTemperature", "Instantaneous")})
    return rows


def peak(rows, key, fn=max):
    vals = [(r[key], r["t"]) for r in rows if r.get(key) is not None]
    if not vals:
        return None
    v, t = fn(vals)
    return {"value": v, "t": t}


def main():
    now = datetime.now(TPE)
    since = now - timedelta(days=365)
    problems = []

    warned, names = [], {}
    for year in sorted({since.year, now.year}):
        try:
            for row in tdb("warning_typhoon_list/get_warning_typhoon", year):
                if row.get("sea_end_datetime") and parse_local(row["sea_end_datetime"]) >= since:
                    warned.append(row)
        except Exception as e:
            problems.append("颱風資料庫 %s 年警報清單：%s" % (year, type(e).__name__))
    warned.sort(key=lambda r: r["sea_start_datetime"])

    wanted = {(r["id"][:4], r["eng_name"].strip().upper()) for r in warned}
    try:
        trk = tracks(wanted) if wanted else {}
    except Exception as e:
        trk = {}
        problems.append("IBTrACS 路徑：%s" % type(e).__name__)

    storms = []
    for r in warned:
        start, end = parse_local(r["sea_start_datetime"]), parse_local(r["sea_end_datetime"])
        storm = {
            "id": r["id"], "name": r.get("cht_name"), "eng": r.get("eng_name"),
            "warning": {"start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
                        "count": num(r.get("warning_count"))},
            "near_taiwan": {"intensity": INTENSITY.get(r.get("max_intensity"), None),
                            "min_pressure_hpa": num(r.get("min_pressure")), "max_wind_ms": num(r.get("max_wind_speed")),
                            "radius7_km": num(r.get("max_range7")), "radius10_km": num(r.get("max_range10"))},
            "path_category": (r.get("official_path_category") or "").strip() or None,
        }
        t = trk.get((r["id"][:4], r["eng_name"].strip().upper()))
        if t:
            storm["track"] = {"sid": t["sid"], "type": t["type"], "rows": t["rows"]}
            d, row = min((km_from_torik(x[1], x[2]), x) for x in t["rows"])
            storm["closest"] = {"km": round(d), "t": row[0], "lat": row[1], "lon": row[2]}
        obs = {}
        day, last = (start - timedelta(days=1)).date(), (end + timedelta(days=1)).date()
        while day <= last:
            for st in STATIONS:
                try:
                    obs.setdefault(st["id"], []).extend(codis_day(st, datetime(day.year, day.month, day.day)))
                except Exception as e:
                    problems.append("CODiS %s %s：%s" % (st["name"], day, type(e).__name__))
                time.sleep(0.8)
            day += timedelta(days=1)
        storm["obs"], storm["summary"] = {}, {}
        for st in STATIONS:
            rows = sorted(obs.get(st["id"], []), key=lambda x: x["t"])
            storm["obs"][st["id"]] = rows
            inside = [x for x in rows if storm["warning"]["start"] <= x["t"] <= storm["warning"]["end"]]
            rain = [x["rain"] for x in inside if x.get("rain") is not None]
            storm["summary"][st["id"]] = {
                "hours": len(inside), "max_gust": peak(inside, "gust"), "max_wind": peak(inside, "wind"),
                "min_pressure": peak(inside, "pressure", min),
                "rain_total": round(sum(rain), 1) if rain else None, "rain_hours": len(rain),
            }
        storms.append(storm)
        print(storm["id"], storm["eng"], storm.get("closest"), {k: len(v) for k, v in storm["obs"].items()})

    try:   # station altitude and distance as given by the live weather feed
        with open(os.path.join(ROOT, "latest.json"), encoding="utf-8") as f:
            live = {w["id"]: w for w in json.load(f).get("weather") or []}
        for st in STATIONS:
            if st["id"] in live:
                st["alt"], st["km"] = live[st["id"]].get("alt"), live[st["id"]].get("km", st["km"])
    except Exception:
        pass
    out = {
        "updated": now.isoformat(timespec="seconds"),
        "period": {"from": since.date().isoformat(), "to": now.date().isoformat()},
        "stations": STATIONS, "storms": storms, "problems": problems,
    }
    if storms or not os.path.exists(OUT):
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    for p in problems:
        print("PROBLEM", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
