"""Heathrow runway tracker: live ADS-B traffic + METAR wind + the 15:00 swap rule."""
import json, math, os, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
MID_LAT = 51.471  # approx. midline between the runways; tune against real thresholds
FEEDS = ["https://api.adsb.lol/v2/point/51.4706/-0.4619/12",
         "https://api.airplanes.live/v2/point/51.4706/-0.4619/12"]
METAR = "https://aviationweather.gov/api/data/metar?ids=EGLL&format=json"
WINDOW_MIN, MIN_AC = 15, 3


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lhr-runway-tracker"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_aircraft():
    err = "no feed"
    for url in FEEDS:
        try:
            return get(url).get("ac", [])
        except Exception as e:
            err = str(e)
    raise RuntimeError(err)


def events(aircraft):
    """Turn raw aircraft into [hex, mode(W/E), kind(arr/dep), side(N/S)] events."""
    out = []
    for a in aircraft:
        alt, lat, lon, trk = a.get("alt_baro"), a.get("lat"), a.get("lon"), a.get("track")
        if not isinstance(alt, (int, float)) or None in (lat, lon, trk) or alt > 3500:
            continue
        vr = a.get("baro_rate") or 0
        d = "W" if 240 <= trk <= 300 else "E" if 60 <= trk <= 120 else None
        if not d or not -0.80 < lon < -0.15:
            continue
        east, west = lon > -0.43, lon < -0.49  # beyond the eastern / western runway ends
        if d == "W":
            kind = "arr" if east and vr < 0 and alt < 3000 else "dep" if west and vr > 200 else None
        else:
            kind = "arr" if west and vr < 0 and alt < 3000 else "dep" if east and vr > 200 else None
        if kind:
            out.append([a.get("hex"), d, kind, "N" if lat > MID_LAT else "S"])
    return out


def resolve(evs):
    seen = {(h, k): (d, s) for h, d, k, s in evs}  # dedupe repeat sightings
    modes = [d for d, _ in seen.values()]
    mode = max("WE", key=modes.count) if modes else None
    res, n = {}, {}
    for kind in ("arr", "dep"):
        sides = [s for (h, k), (d, s) in seen.items() if k == kind and d == mode]
        n[kind] = len(sides)
        res[kind] = sides.count("N") / len(sides) if len(sides) >= MIN_AC else None
    return mode, res, n


def rwy(mode, north_share):
    n, s = ("27R", "27L") if mode == "W" else ("09L", "09R")
    return n if north_share >= .7 else s if north_share <= .3 else f"{n} + {s}"


def eff_flip(state, today):
    weeks = (today - datetime.fromisoformat(state["ref"]).date()).days // 7
    return state["flip"] if weeks % 2 == 0 else not state["flip"]


def predict(mode, now, state):
    if mode == "E":  # unverified assumption; live traffic overrides it
        return {"arr": "09L", "dep": "09R"}
    dep_north = (now.hour < 15) == eff_flip(state, now.date())
    return {"arr": "27L", "dep": "27R"} if dep_north else {"arr": "27R", "dep": "27L"}


def calibrate(state, mode, res, now):
    """If live departures clearly contradict the weekly pattern, re-anchor it."""
    d = res.get("dep")
    if mode != "W" or d is None or .2 < d < .8 or not (7 <= now.hour < 14 or 16 <= now.hour < 23):
        return
    state["flip"] = (d >= .8) == (now.hour < 15)
    state["ref"] = (now.date() - timedelta(days=now.weekday())).isoformat()


def main():
    now = datetime.now(UK)
    try:
        state = get(os.environ["PAGES_URL"] + "/state.json")
    except Exception:
        state = {}
    state.setdefault("flip", True)
    state.setdefault("ref", (now.date() - timedelta(days=now.weekday())).isoformat())
    state.setdefault("hist", [])
    note = ""
    try:
        evs = events(fetch_aircraft())
    except Exception as e:
        evs, note = [], f" Traffic feed unavailable ({e})."
    cutoff = now.timestamp() - WINDOW_MIN * 60
    state["hist"] = [h for h in state["hist"] if h["t"] > cutoff] + [{"t": now.timestamp(), "ev": evs}]
    mode, res, n = resolve([e for h in state["hist"] for e in h["ev"]])
    source = "traffic" if mode else "wind"
    if not mode:
        try:
            w = get(METAR)[0].get("wdir")
            if isinstance(w, (int, float)):
                mode = "W" if math.cos(math.radians(w - 270)) >= 0 else "E"
        except Exception:
            pass
        mode = mode or state.get("mode", "W")
    state["mode"] = mode
    calibrate(state, mode, res, now)
    pred = predict(mode, now, state)
    live = {k: rwy(mode, res[k]) for k in res if res[k] is not None}
    quiet = (now.hour == 23 and now.minute >= 30) or now.hour < 6
    if len(live) == 2:
        basis, msg = "live", f"Confirmed by {n['arr']} landings and {n['dep']} departures in the last {WINDOW_MIN} minutes."
        state["last"] = live
    elif live:
        basis, msg = "partial", "Partly confirmed by live traffic; the rest is predicted from the 15:00 swap."
    elif quiet and state.get("last"):
        basis, msg = "quiet", "Quiet hours (about 23:30 to 06:00). Showing the last confirmed pattern."
        live = state["last"]
    else:
        basis, msg = "predicted", "No live traffic to confirm. Predicted from wind direction and the 15:00 swap."
    status = {
        "updated": datetime.now(timezone.utc).isoformat(), "mode": mode, "modeSource": source,
        "arrivals": live.get("arr", pred["arr"]), "departures": live.get("dep", pred["dep"]),
        "basis": basis, "message": msg + note, "flip": state["flip"], "ref": state["ref"],
    }
    os.makedirs("out", exist_ok=True)
    json.dump(status, open("out/status.json", "w"), indent=1)
    json.dump(state, open("out/state.json", "w"))
    print(status)


if __name__ == "__main__":
    main()
