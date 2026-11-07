#!/usr/bin/env python3
"""Who played the most minutes per position?  Reads rugby.db (stdlib only).

Examples:
  python analysis.py                          # top 5 per position, all teams
  python analysis.py --team "South Africa"    # one team only
  python analysis.py --top 10 --group "Back row"
  python analysis.py --position Hooker --top 20
  python analysis.py --sort tries             # rank by tries (or: points, minutes)
  python analysis.py --csv minutes_by_position.csv
  python analysis.py --since 2026-01-01 --until 2026-06-30
"""
import argparse
import csv
import sqlite3
import sys

POSITION_ORDER = ["Prop", "Hooker", "Lock", "Flanker", "Number 8", "Scrum Half",
                  "Fly Half", "Centre", "Wing", "Full Back"]

QUERY = """
SELECT a.position, a.position_group, a.player_name, a.team,
       COUNT(*)                          AS matches,
       SUM(a.started)                    AS starts,
       ROUND(SUM(a.minutes_played), 1)   AS total_minutes,
       ROUND(AVG(a.minutes_played), 1)   AS avg_minutes,
       SUM(a.tries)                      AS tries,
       SUM(a.points)                     AS points
FROM appearances a JOIN matches m ON m.match_id = a.match_id
WHERE a.appeared = 1 AND a.position IS NOT NULL
  AND a.position_source != 'replaced_ambiguous'
  {where}
GROUP BY a.player_key, a.team, a.position
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="rugby.db")
    ap.add_argument("--team")
    ap.add_argument("--position")
    ap.add_argument("--group")
    ap.add_argument("--sort", choices=["minutes", "tries", "points"], default="minutes",
                    help="what to rank by (default: minutes)")
    ap.add_argument("--top", type=int, default=5, help="players per position (0 = all)")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--include-uncertain", action="store_true",
                    help="also count rows whose position is a guess")
    ap.add_argument("--csv", help="write results to this CSV file")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(appearances)")}
    if "points" not in cols or "position_group" not in cols:
        sys.exit("No position data yet. Run: python rugby_minutes.py --refresh")
    mcols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    date_col = "match_date" if "match_date" in mcols else next(
        (c for c in ("date", "match_time", "played_on") if c in mcols), None)

    where, params = [], []
    for col, val in (("a.team", args.team), ("a.position", args.position),
                     ("a.position_group", args.group)):
        if val:
            where.append(f"AND lower({col}) = lower(?)")
            params.append(val)
    if (args.since or args.until) and not date_col:
        sys.exit("Could not find the date column in matches; omit --since/--until.")
    if args.since:
        where.append(f"AND substr(m.{date_col},1,10) >= ?")
        params.append(args.since)
    if args.until:
        where.append(f"AND substr(m.{date_col},1,10) <= ?")
        params.append(args.until)
    sql = QUERY.format(where=" ".join(where))
    if args.include_uncertain:
        sql = sql.replace("AND a.position_source != 'replaced_ambiguous'", "")

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        sys.exit("No matching appearances.")

    by_pos = {}
    for r in rows:
        by_pos.setdefault(r[0], []).append(r)
    order = [p for p in POSITION_ORDER if p in by_pos] + sorted(
        p for p in by_pos if p not in POSITION_ORDER)

    out = []
    for pos in order:
        sort_idx = {"minutes": 6, "tries": 8, "points": 9}[args.sort]
        ranked = sorted(by_pos[pos], key=lambda r: (-(r[sort_idx] or 0), -r[6], r[2]))
        if args.top:
            ranked = ranked[:args.top]
        for i, r in enumerate(ranked, 1):
            out.append((pos, i) + r[2:] )
        print(f"\n{pos}")
        print(f"  {'#':<3}{'Player':<30}{'Team':<16}{'Mtch':>5}{'Strt':>5}{'Total':>9}{'Avg':>7}{'Tries':>7}{'Pts':>6}")
        for i, r in enumerate(ranked, 1):
            print(f"  {i:<3}{r[2][:29]:<30}{r[3][:15]:<16}{r[4]:>5}{r[5]:>5}{r[6]:>9.1f}{r[7]:>7.1f}{r[8] or 0:>7}{r[9] or 0:>6}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["position", "rank", "player", "team", "matches", "starts",
                        "total_minutes", "avg_minutes", "tries", "points"])
            w.writerows(out)
        print(f"\nWrote {len(out)} rows to {args.csv}")


if __name__ == "__main__":
    main()
