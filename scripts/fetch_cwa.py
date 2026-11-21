#!/usr/bin/env python3
"""Fetch open data from Taiwan's Central Weather Administration (CWA) for the Torik (都歷) coast page.

Writes data/latest.json (what the page reads) and data/status.json (what happened this run).
The API key is read from the CWA_KEY environment variable and is never written to disk.

Datasets (response formats confirmed against live responses on 2026-11-21):
  O-B0076-001 (file API)  marine station list with names and coordinates
  O-B0075-001             48-hour marine observations (tide gauges, buoys)
  O-A0003-001             current weather, staffed stations
  O-A0001-001             current weather, automatic stations
  F-A0021-001             tide forecast, high and low water for the coming month
  F-D0047-037             township forecast, Taitung County, next 3 days
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

STORE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"
FILES = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
TPE = timezone(timedelta(hours=8))

TORIK = {"name": "都歷", "lat": 23.0236, "lon": 121.3340}
MARINE_RADIUS_KM = 45     # marine stations kept, nearest first
WEATHER_RADIUS_KM = 25


def km(lat, lon):
    """Distance from Torik in km (equirectangular; fine at this scale)."""
    dy = (lat - TORIK["lat"]) * 110.75
    dx = (lon - TORIK["lon"]) * 111.32 * math.cos(math.radians(TORIK["lat"]))
    return round(math.hypot(dx, dy), 1)


def num(v):
    """CWA sends numbers as strings, and missing values as 'None', '', '-99' or similar."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= -90:
        return None
    return f


def text(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in ("", "None", "-99", "-99.0", "X") else s


def get(url_base, dataset_id, key, extra=None):
    params = {"Authorization": key, "format": "JSON"}
    params.update(extra or {})
    url = url_base + dataset_id + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    last = None
    for attempt, pause in enumerate((0, 8, 25)):      # the service sometimes resets large downloads
        time.sleep(pause)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise
            last = e
        except Exception as e:
            last = e
    raise last


def flatten(d, prefix=""):
    """{'a': {'b': '1'}} -> {'a.b': '1'}; lists are skipped."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, prefix + k + "."))
        elif not isinstance(v, list):
            out[prefix + k] = v
    return out


# ---------- marine ----------

def marine_stations(key):
    data = get(FILES, "O-B0076-001", key, {"downloadType": "WEB"})
    locs = data["cwaopendata"]["Resources"]["Resource"]["Data"]["SeaSurfaceObs"]["Location"]
    out = []
    for loc in locs:
        s = loc.get("Station", {})
        lat, lon = num(s.get("StationLatitude")), num(s.get("StationLongitude"))
        if lat is None or lon is None:
            continue
        d = km(lat, lon)
        if d <= MARINE_RADIUS_KM:
            out.append({
                "id": s.get("StationID"), "name": s.get("StationName"), "kind": s.get("StationAttribute"),
                "lat": lat, "lon": lon, "km": d, "where": text(s.get("StationAddress")),
                "operator": text(s.get("StationChargeIns")),
            })
    return sorted(out, key=lambda x: x["km"])


def marine_obs(key, stations):
    wanted = {s["id"]: s for s in stations}
    data = get(STORE, "O-B0075-001", key)
    locs = data["Records"]["SeaSurfaceObs"]["Location"]
    for loc in locs:
        sid = loc.get("Station", {}).get("StationID")
        if sid not in wanted:
            continue
        rows = []
        for t in loc.get("StationObsTimes", {}).get("StationObsTime", []):
            flat = flatten(t.get("WeatherElements", {}))
            row = {"t": t.get("DateTime")}
            for k, v in flat.items():
                n = num(v)
                row[k] = n if n is not None else text(v)
            rows.append(row)
        rows.sort(key=lambda r: r["t"] or "")
        # drop fields that are empty for the whole period, to keep the file small
        keep = {k for r in rows for k, v in r.items() if v is not None}
        wanted[sid]["obs"] = [{k: r.get(k) for k in r if k in keep} for r in rows]
    def has_numbers(st):
        return any(isinstance(v, (int, float)) for r in st.get("obs", []) for k, v in r.items() if k != "t")
    return [s for s in stations if has_numbers(s)][:6]


# ---------- weather ----------

def wgs84(geo):
    for c in geo.get("Coordinates", []):
        if c.get("CoordinateName") == "WGS84":
            return num(c.get("StationLatitude")), num(c.get("StationLongitude"))
    return None, None


def weather(key, dataset_id, kind):
    data = get(STORE, dataset_id, key)
    out = []
    for s in data["records"]["Station"]:
        geo = s.get("GeoInfo", {})
        lat, lon = wgs84(geo)
        if lat is None or lon is None:
            continue
        d = km(lat, lon)
        if d > WEATHER_RADIUS_KM:
            continue
        we = s.get("WeatherElement", {})
        gust = we.get("GustInfo", {})
        out.append({
            "id": s.get("StationId"), "name": s.get("StationName"), "kind": kind,
            "lat": lat, "lon": lon, "km": d, "alt": num(geo.get("StationAltitude")),
            "town": text(geo.get("TownName")), "t": s.get("ObsTime", {}).get("DateTime"),
            "weather": text(we.get("Weather")),
            "temp": num(we.get("AirTemperature")), "rh": num(we.get("RelativeHumidity")),
            "pressure": num(we.get("AirPressure")), "rain_today": num(we.get("Now", {}).get("Precipitation")),
            "wind_speed": num(we.get("WindSpeed")), "wind_dir": num(we.get("WindDirection")),
            "gust": num(gust.get("PeakGustSpeed")),
            "visibility": text(we.get("VisibilityDescription")), "uv": num(we.get("UVIndex")),
        })
    return sorted(out, key=lambda x: x["km"])


# ---------- forecasts ----------

def tide_forecast(key):
    data = get(STORE, "F-A0021-001", key)
    best = None
    for item in data["records"]["TideForecasts"]:
        loc = item.get("Location", {})
        lat, lon = num(loc.get("Latitude")), num(loc.get("Longitude"))
        if lat is None or lon is None:
            continue
        d = km(lat, lon)
        if best is None or d < best[0]:
            best = (d, loc, lat, lon)
    d, loc, lat, lon = best
    events = []
    for day in loc.get("TimePeriods", {}).get("Daily", []):
        for e in day.get("Time", []):
            h = e.get("TideHeights", {})
            events.append({
                "t": e.get("DateTime"), "type": e.get("Tide"), "range": text(day.get("TideRange")),
                "twvd_cm": num(h.get("AboveTWVD")), "msl_cm": num(h.get("AboveLocalMSL")),
                "chart_cm": num(h.get("AboveChartDatum")),
            })
    events.sort(key=lambda e: e["t"] or "")
    return {"id": loc.get("LocationId"), "name": loc.get("LocationName"), "lat": lat, "lon": lon, "km": d, "events": events}


def town_forecast(key):
    data = get(STORE, "F-D0047-037", key)
    best = None
    for group in data["records"]["Locations"]:
        for loc in group.get("Location", []):
            lat, lon = num(loc.get("Latitude")), num(loc.get("Longitude"))
            if lat is None or lon is None:
                continue
            d = km(lat, lon)
            if best is None or d < best[0]:
                best = (d, loc, lat, lon)
    d, loc, lat, lon = best
    elements = []
    wanted = ("溫度", "體感溫度", "相對濕度", "風速", "風向", "3小時降雨機率", "天氣現象")
    for el in loc.get("WeatherElement", []):
        if el.get("ElementName") not in wanted:
            continue
        series = []
        for t in el.get("Time", [])[:24]:
            row = {"t": t.get("DataTime") or t.get("StartTime"), "end": t.get("EndTime")}
            for v in t.get("ElementValue", []):
                row.update(v)
            series.append({k: v for k, v in row.items() if v is not None})
        elements.append({"name": el.get("ElementName"), "series": series})
    return {"name": loc.get("LocationName"), "lat": lat, "lon": lon, "km": d, "elements": elements}


# ---------- run ----------

def main():
    key = os.environ.get("CWA_KEY", "").strip()
    os.makedirs(OUT, exist_ok=True)
    now = datetime.now(TPE)
    status = {"updated": now.strftime("%Y-%m-%d %H:%M"), "timezone": "Asia/Taipei", "stage": "live", "datasets": []}
    latest = {"updated": now.isoformat(timespec="seconds"), "site": TORIK}

    def step(dataset_id, label, fn):
        started = time.time()
        try:
            result = fn()
            status["datasets"].append({"id": dataset_id, "label": label, "ok": True,
                                       "seconds": round(time.time() - started, 1)})
            return result
        except urllib.error.HTTPError as e:
            err = "HTTP %s" % e.code
        except Exception as e:
            err = type(e).__name__ + ": " + str(e).replace(key, "***")[:200]
        status["datasets"].append({"id": dataset_id, "label": label, "ok": False, "error": err,
                                   "seconds": round(time.time() - started, 1)})
        return None

    # Sections that fail this run keep their last good value, marked with when it was fetched.
    previous = {}
    try:
        with open(os.path.join(OUT, "latest.json"), encoding="utf-8") as f:
            previous = json.load(f)
    except Exception:
        pass
    fetched = dict(previous.get("fetched") or {})
    LABELS = {"marine": "海象觀測", "weather": "氣象觀測", "tide_forecast": "潮汐預報", "town_forecast": "鄉鎮天氣預報"}

    def settle(section, value):
        if value:
            latest[section] = value
            fetched[section] = latest["updated"]
        elif previous.get(section):
            latest[section] = previous[section]
            fetched.setdefault(section, previous.get("updated"))
        else:
            latest[section] = None

    if not key:
        status["note"] = "CWA_KEY secret is not set; nothing was fetched."
    else:
        stations = step("O-B0076-001", "海象測站清單", lambda: marine_stations(key))
        settle("marine", step("O-B0075-001", "海象觀測（48 小時）", lambda: marine_obs(key, stations)) if stations else None)
        staffed = step("O-A0003-001", "氣象觀測（署屬測站）", lambda: weather(key, "O-A0003-001", "署屬氣象站")) or []
        auto = step("O-A0001-001", "氣象觀測（自動站）", lambda: weather(key, "O-A0001-001", "自動氣象站")) or []
        merged = {}
        for st in staffed + auto:
            if st["id"] not in merged:
                merged[st["id"]] = st
            else:
                for k, v in st.items():
                    if merged[st["id"]].get(k) is None and k != "kind":
                        merged[st["id"]][k] = v
        settle("weather", sorted(merged.values(), key=lambda x: x["km"])[:8])
        settle("tide_forecast", step("F-A0021-001", "潮汐預報", lambda: tide_forecast(key)))
        settle("town_forecast", step("F-D0047-037", "鄉鎮天氣預報", lambda: town_forecast(key)))
        latest["fetched"] = fetched
        latest["carried_over"] = [{"section": k, "label": LABELS[k], "fetched": fetched.get(k)}
                                  for k in LABELS if latest.get(k) and fetched.get(k) != latest["updated"]]
        if any(latest.get(k) for k in LABELS):
            with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
                json.dump(latest, f, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(OUT, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    for d in status["datasets"]:
        print(d["id"], "ok" if d["ok"] else d.get("error"), d.get("seconds"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
