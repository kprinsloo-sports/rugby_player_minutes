#!/usr/bin/env python3
"""Fetch international rugby matches from World Rugby's public data feed and
work out minutes played per player per match from substitution times.

Only matches involving the chosen teams are kept (default: South Africa,
New Zealand, Australia; exact team-name match, so "Australia A" is excluded).

Usage (run on your own machine; standard library only, Python 3.9+):

    python rugby_minutes.py --start 2026-07-01 --end 2026-11-05
    python rugby_minutes.py --start 2026-07-01 --end 2026-11-05 \
        --teams "South Africa,New Zealand,Australia,Argentina"

Results go to a SQLite file (default rugby.db). Raw JSON responses are cached
in ./cache so re-runs do not hit the API again for matches already fetched.

Minutes are taken from the match clock (which excludes the half-time break):
  - starters are on from 0 seconds
  - "Replacement On" starts a player's time on the pitch
  - "Replacement Off" or a red card ends it
  - anyone still on at the end plays until the match clock's final time
Yellow cards are counted but the sin-bin time is NOT deducted.
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.wr-rims-prod.pulselive.com/rugby/v3"
USER_AGENT = "rugby-minutes/0.1 (personal research script)"
DEFAULT_TEAMS = "South Africa,New Zealand,Australia"

# The feed's match clock is sometimes left running after full time (one match
# showed 179484:36). A plausible full-time clock is 80:00 to 110:00.
MIN_END_SECS = 80 * 60
MAX_END_SECS = 110 * 60


# --------------------------------------------------------------------------
# Minutes calculation (pure functions, no network)
# --------------------------------------------------------------------------

def _classify(event):
    label = (event.get("typeLabel") or event.get("type") or "").lower()
    if "replacement on" in label or label == "sub on":
        return "on"
    if "replacement off" in label or label == "sub off":
        return "off"
    if "red" in label and "card" in label:
        return "red"
    if "yellow" in label:
        return "yellow"
    return None


def effective_match_secs(summary, timeline):
    """Return (end_secs, estimated).

    Uses the feed's match clock when it is plausible. Otherwise falls back to
    80:00, or the last timeline event if that is later, and flags it as an
    estimate (players on the pitch at the end then get approximate minutes).
    """
    clock = ((summary.get("match") or {}).get("clock") or {}).get("secs") or 0
    if MIN_END_SECS <= clock <= MAX_END_SECS:
        return clock, False
    last = max((e["time"]["secs"] for e in (timeline or {}).get("timeline", [])
                if e["time"]["secs"] <= MAX_END_SECS), default=0)
    return max(MIN_END_SECS, last), True


# The feed's lineup "order" field for starters, mapped to the shirt slot (1-15).
# Read from complete lineups where shirt numbers and order agree. It is used
# only when a starter wears a number above 15 (a bench player promoted into the
# starting XV late keeps his bench number).
ORDER_TO_SLOT = {1: 1, 4: 2, 5: 3, 6: 4, 8: 5, 9: 6, 11: 7, 12: 8,
                 13: 9, 17: 10, 18: 11, 19: 12, 21: 13, 25: 14, 26: 15}


def position_group(slot):
    """Group a starting shirt number (1-15) into a broad position group."""
    return {1: "Front row", 2: "Front row", 3: "Front row",
            4: "Second row", 5: "Second row",
            6: "Back row", 7: "Back row", 8: "Back row",
            9: "Half-backs", 10: "Half-backs",
            12: "Centres", 13: "Centres",
            11: "Back three", 14: "Back three", 15: "Back three"}.get(slot)


def compute_appearances(summary, timeline):
    """Return (rows, warnings) for one match.

    Position: the feed lists substitutes only as "Replacement", so a substitute
    is given the position of the player they replaced (chains of substitutions
    pass the position on). `position_source` says how each position was found:
    listed / replaced / replaced_ambiguous (several swaps in the same second,
    so who replaced whom is a guess) / unknown / never played.

    summary  -- JSON from /match/{id}/summary
    timeline -- JSON from /match/{id}/timeline
    """
    match = summary["match"]
    end, estimated = effective_match_secs(summary, timeline)
    team_names = [t["name"] for t in match["teams"]]
    warnings = []
    if estimated:
        warnings.append(
            f"match clock unusable ({match['clock'].get('label')}); assumed the "
            f"match ended at {end // 60}:{end % 60:02d} - minutes for players on "
            f"at the end are approximate")

    players = {}   # key -> dict
    index = {}     # any known id (id or altId) -> key

    for ti, team in enumerate(summary["teams"]):
        for entry in team["teamList"]["list"]:
            if entry.get("number") in (None, ""):
                continue  # coaches and other staff
            p = entry["player"]
            key = str(p.get("altId") or p["id"])
            started = not p.get("isReplacement", False)
            shirt = int(entry["number"])
            slot = None
            if started:
                if 1 <= shirt <= 15:
                    slot = shirt
                else:
                    slot = ORDER_TO_SLOT.get(entry.get("order"))
                    name = (p.get("name") or {}).get("display")
                    if slot is not None:
                        warnings.append(
                            f"{name} started wearing #{shirt}; position taken "
                            f"from lineup order (slot {slot})")
                    else:
                        warnings.append(
                            f"{name} started wearing #{shirt} and the lineup order "
                            f"{entry.get('order')} is not recognised; no position slot")
            players[key] = {
                "team_index": ti,
                "team": team_names[ti],
                "player_key": key,
                "player_id": str(p["id"]),
                "player_name": (p.get("name") or {}).get("display"),
                "shirt_number": shirt,
                "listed_position": entry.get("positionLabel"),
                "position": entry.get("positionLabel") if started else None,
                "slot": slot,
                "position_source": "listed" if started else None,
                "started": started,
                "intervals": [],
                "open": 0 if started else None,
                "yellow_cards": 0,
                "red_cards": 0,
            }
            index[str(p["id"])] = key
            index[key] = key

    def lookup(event):
        for field in ("playerId", "playerAltId"):
            value = event.get(field)
            if value is not None and str(value) in index:
                return players[index[str(value)]]
        return None

    events = sorted(enumerate(timeline["timeline"]),
                    key=lambda pair: (pair[1]["time"]["secs"], pair[0]))
    # Pair each "on" with the "off" at the same second for the same team, in the
    # order listed. (The feed's own link numbers are not reliable.)
    groups = {}
    for _, ev in events:
        kind = _classify(ev)
        if kind in ("on", "off"):
            groups.setdefault((ev["time"]["secs"], ev.get("teamIndex")),
                              {"on": [], "off": []})[kind].append(ev)
    replaced_by_pair = {}  # id(on event) -> (off event, ambiguous)
    for g in groups.values():
        if len(g["on"]) == len(g["off"]):
            for on_ev, off_ev in zip(g["on"], g["off"]):
                replaced_by_pair[id(on_ev)] = (off_ev, len(g["on"]) > 1)

    ons = {0: 0, 1: 0}
    offs = {0: 0, 1: 0}
    for _, ev in events:
        kind = _classify(ev)
        if kind is None:
            continue
        secs = ev["time"]["secs"]
        p = lookup(ev)
        if p is None:
            warnings.append(f"{kind} event at {secs}s for unknown player "
                            f"{ev.get('playerId')}")
            continue
        if kind == "on":
            ons[p["team_index"]] += 1
            if p["position_source"] is None:  # first time on: inherit position
                partner, ambiguous = replaced_by_pair.get(id(ev), (None, False))
                gone = lookup(partner) if partner is not None else None
                if gone is not None and gone["position"] is not None:
                    p["position"] = gone["position"]
                    p["slot"] = gone["slot"]
                    p["position_source"] = ("replaced_ambiguous" if ambiguous
                                            else "replaced")
                else:
                    p["position_source"] = "unknown"
            if p["open"] is None:
                p["open"] = secs
            else:
                warnings.append(f"{p['player_name']} came on at {secs}s but was already on")
        elif kind in ("off", "red"):
            if kind == "off":
                offs[p["team_index"]] += 1
            else:
                p["red_cards"] += 1
            if p["open"] is not None:
                p["intervals"].append((p["open"], secs))
                p["open"] = None
            elif kind == "off":
                warnings.append(f"{p['player_name']} went off at {secs}s but was not on")
        elif kind == "yellow":
            p["yellow_cards"] += 1

    for ti in (0, 1):
        if ons[ti] != offs[ti]:
            warnings.append(f"{team_names[ti]}: {ons[ti]} replacements on but "
                            f"{offs[ti]} off")
        starters = sum(1 for p in players.values()
                       if p["team_index"] == ti and p["started"])
        if starters != 15:
            warnings.append(f"{team_names[ti]}: {starters} starters listed (expected 15)")

    rows = []
    for p in players.values():
        if p["open"] is not None:
            p["intervals"].append((p["open"], end))
            p["open"] = None
        seconds = sum(b - a for a, b in p["intervals"])
        first_on = p["intervals"][0][0] if p["intervals"] else None
        last_off = p["intervals"][-1][1] if p["intervals"] else None
        rows.append({
            "team": p["team"],
            "team_index": p["team_index"],
            "player_key": p["player_key"],
            "player_id": p["player_id"],
            "player_name": p["player_name"],
            "shirt_number": p["shirt_number"],
            "listed_position": p["listed_position"],
            "position": p["position"],
            "position_number": p["slot"],
            "position_group": position_group(p["slot"]),
            "position_source": p["position_source"] or "never played",
            "started": int(p["started"]),
            "appeared": int(seconds > 0),
            "sub_on_minute": None if p["started"] or first_on is None else round(first_on / 60, 1),
            "sub_off_minute": None if last_off is None or last_off >= end else round(last_off / 60, 1),
            "seconds_played": seconds,
            "minutes_played": round(seconds / 60, 1),
            "yellow_cards": p["yellow_cards"],
            "red_cards": p["red_cards"],
        })
    rows.sort(key=lambda r: (r["team_index"], r["shirt_number"]))
    return rows, warnings


# --------------------------------------------------------------------------
# API access
# --------------------------------------------------------------------------

def http_get_json(url, retries=3, delay=1.0):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def list_matches(start, end, sport, teams, require_both, pause):
    """Yield completed matches in the date range that involve the chosen teams."""
    wanted = {t.strip().casefold() for t in teams.split(",") if t.strip()}
    page = 0
    while True:
        query = urllib.parse.urlencode({
            "startDate": start, "endDate": end, "states": "C",
            "sort": "asc", "pageSize": 100, "page": page})
        data = http_get_json(f"{API}/match?{query}")
        for m in data.get("content", []):
            if (m.get("sport") or "").casefold() != sport.casefold():
                continue
            names = [t["name"].casefold() for t in m.get("teams", [])]
            hits = [n in wanted for n in names]
            if (all(hits) if require_both else any(hits)):
                yield m
        page += 1
        if page >= data.get("pageInfo", {}).get("numPages", 0):
            return
        time.sleep(pause)


def fetch_cached(cache_dir, match_id, name, pause):
    path = cache_dir / f"{match_id}_{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = http_get_json(f"{API}/match/{match_id}/{name}")
    path.write_text(json.dumps(data))
    time.sleep(pause)
    return data


# --------------------------------------------------------------------------
# SQLite
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id     TEXT PRIMARY KEY,
    match_date   TEXT,
    competition  TEXT,
    sport        TEXT,
    venue        TEXT,
    city         TEXT,
    team_a       TEXT,
    team_b       TEXT,
    score_a      INTEGER,
    score_b      INTEGER,
    match_secs   INTEGER,
    match_secs_estimated INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS appearances (
    match_id       TEXT NOT NULL REFERENCES matches(match_id),
    team           TEXT,
    player_key     TEXT NOT NULL,
    player_id      TEXT,
    player_name    TEXT,
    shirt_number   INTEGER,
    position       TEXT,
    started        INTEGER,
    listed_position TEXT,
    position_number INTEGER,
    position_group  TEXT,
    position_source TEXT,
    appeared       INTEGER,
    sub_on_minute  REAL,
    sub_off_minute REAL,
    seconds_played INTEGER,
    minutes_played REAL,
    yellow_cards   INTEGER,
    red_cards      INTEGER,
    PRIMARY KEY (match_id, player_key)
);
CREATE INDEX IF NOT EXISTS idx_app_player ON appearances(player_name);
"""


def migrate(conn):
    """Add columns introduced after a database was first created."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    if cols and "match_secs_estimated" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN match_secs_estimated "
                     "INTEGER DEFAULT 0")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(appearances)")}
    for name, decl in (("listed_position", "TEXT"), ("position_number", "INTEGER"),
                       ("position_group", "TEXT"), ("position_source", "TEXT")):
        if cols and name not in cols:
            conn.execute(f"ALTER TABLE appearances ADD COLUMN {name} {decl}")


def save_match(conn, summary, rows, timeline=None):
    m = summary["match"]
    mid = m["matchId"]
    end, estimated = effective_match_secs(summary, timeline)
    conn.execute("DELETE FROM appearances WHERE match_id = ?", (mid,))
    conn.execute("DELETE FROM matches WHERE match_id = ?", (mid,))
    venue = m.get("venue") or {}
    conn.execute(
        "INSERT INTO matches (match_id, match_date, competition, sport, venue, "
        "city, team_a, team_b, score_a, score_b, match_secs, match_secs_estimated) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, m["time"]["label"], m.get("competition"), m.get("sport"),
         venue.get("name"), venue.get("city"),
         m["teams"][0]["name"], m["teams"][1]["name"],
         m["scores"][0], m["scores"][1], end, int(estimated)))
    conn.executemany(
        "INSERT INTO appearances (match_id, team, player_key, player_id, "
        "player_name, shirt_number, position, started, listed_position, "
        "position_number, position_group, position_source, appeared, "
        "sub_on_minute, sub_off_minute, seconds_played, minutes_played, "
        "yellow_cards, red_cards) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(mid, r["team"], r["player_key"], r["player_id"], r["player_name"],
          r["shirt_number"], r["position"], r["started"], r["listed_position"],
          r["position_number"], r["position_group"], r["position_source"],
          r["appeared"], r["sub_on_minute"], r["sub_off_minute"],
          r["seconds_played"], r["minutes_played"], r["yellow_cards"],
          r["red_cards"])
         for r in rows])


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="last date, YYYY-MM-DD")
    ap.add_argument("--teams", default=DEFAULT_TEAMS,
                    help="comma-separated exact team names (default: %(default)s)")
    ap.add_argument("--both", action="store_true",
                    help="require BOTH teams to be in the list (default: either)")
    ap.add_argument("--sport", default="MRU",
                    help="MRU = men's 15s, WRU = women's 15s (default: MRU)")
    ap.add_argument("--db", default="rugby.db")
    ap.add_argument("--cache-dir", default="cache")
    ap.add_argument("--pause", type=float, default=0.5,
                    help="seconds to wait between requests (default 0.5)")
    ap.add_argument("--refresh", action="store_true",
                    help="recompute matches already in the database")
    args = ap.parse_args(argv)

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)
    migrate(conn)
    done ={r[0] for r in conn.execute("SELECT match_id FROM matches")}

    n_matches = n_rows = 0
    for m in list_matches(args.start, args.end, args.sport, args.teams,
                          args.both, args.pause):
        mid = m["matchId"]
        label = (f"{m['time']['label']} "
                 f"{' v '.join(t['name'] for t in m['teams'])} ({m.get('competition')})")
        if mid in done and not args.refresh:
            print(f"skip   {label}")
            continue
        try:
            summary = fetch_cached(cache, mid, "summary", args.pause)
            timeline = fetch_cached(cache, mid, "timeline", args.pause)
            rows, warnings = compute_appearances(summary, timeline)
        except Exception as exc:  # keep going on a bad match
            print(f"FAILED {label}: {exc}", file=sys.stderr)
            continue
        with conn:
            save_match(conn, summary, rows, timeline)
        n_matches += 1
        n_rows += len(rows)
        print(f"saved  {label}: {len(rows)} players")
        for w in warnings:
            print(f"  warning: {w}", file=sys.stderr)

    print(f"\nDone: {n_matches} matches, {n_rows} appearances -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
