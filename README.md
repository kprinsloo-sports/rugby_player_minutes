# Rugby player minutes

Match results and per-player minutes for men's international rugby, built from
World Rugby's public match feed. Minutes are derived from substitution times.
Defaults to matches involving South Africa, New Zealand and Australia. Each
appearance records the player's position (substitutes inherit the position of
the player they replaced).

Python standard library only (3.9+). No installs needed.

## Run

```
python -m unittest discover -s tests -v                      # tests
python rugby_minutes.py --start 2026-01-01 --end 2026-11-06  # fetch into rugby.db
python build_dashboard.py                                    # writes dashboard.html
python analysis.py --top 10                                  # most minutes per position
```

Fetching is cached in `cache/`, so re-running resumes where it stopped. Use
`--refresh` after upgrading the script to re-process cached matches.
`--teams "France,Ireland"` changes the teams; `--both` requires both sides to match.

## Publish the dashboard (GitHub Pages)

Run `publish.bat` (Windows). It rebuilds `index.html` from `rugby.db`, commits and
pushes it. In the repo's Settings > Pages, set the source to branch `main`, folder
`/ (root)`; the site is then at https://kprinsloo-sports.github.io/rugby_player_minutes/

## Dashboard

`dashboard.html` is a single self-contained file: full table, filters for match type
(internationals only by default), team, position group, position and player, and a
player-totals view. A match is an international when both sides are national teams;
club and invitational sides (Stormers, Barbarians, ...) are not. The build prints the
matches it excluded; add missing nations with `--national "Team Name"`.

## Caveats

- Unofficial API; it may change without notice.
- Some matches have an unusable match clock; those use 80:00 or the last event
  and are flagged `match_secs_estimated` (shown as `~`).
- Yellow cards are recorded but sin-bin time is not deducted.
- When several substitutions happen in the same second the position of the
  replacement is a guess (`replaced_ambiguous`, shown as `?`).
