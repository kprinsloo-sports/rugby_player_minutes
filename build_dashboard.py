#!/usr/bin/env python3
"""Build a self-contained dashboard (one HTML file) from rugby.db.

Usage:
    python build_dashboard.py                       # rugby.db -> dashboard.html
    python build_dashboard.py --db rugby.db --out dashboard.html

Open dashboard.html in any browser (double-click it). It needs no internet
connection and no server; the data is embedded in the file. Re-run this script
after fetching new matches to refresh it.
"""
import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

# A match counts as an international when BOTH sides are national men's teams.
# Club and invitational sides (Stormers, Barbarians, ...) are not in this list.
# Add missing nations on the command line: --national "Name 1,Name 2"
NATIONAL_TEAMS = {
    "Argentina", "Australia", "England", "Fiji", "France", "Ireland", "Italy",
    "Japan", "New Zealand", "Samoa", "Scotland", "South Africa", "Tonga", "Wales",
    "Georgia", "Romania", "Spain", "Portugal", "Uruguay", "Chile", "Canada", "USA",
    "United States", "Namibia", "Zimbabwe", "Kenya", "Uganda", "Russia", "Belgium",
    "Netherlands", "Germany", "Poland", "Hong Kong China", "Hong Kong", "Korea",
    "South Korea", "Brazil", "Paraguay", "Colombia", "Switzerland", "Sweden",
    "Lithuania", "Czechia", "Czech Republic", "Ivory Coast", "Cote d'Ivoire",
    "Madagascar", "Senegal", "Morocco", "Tunisia", "Algeria", "Cameroon", "Ghana",
    "Nigeria", "Zambia", "Malta", "Croatia", "Ukraine", "Latvia", "Sri Lanka",
    "Philippines", "Malaysia", "Singapore", "Kazakhstan", "China", "India",
    "Papua New Guinea", "Cook Islands", "Peru", "Venezuela", "Mexico", "Jamaica",
    "Trinidad and Tobago", "Barbados",
}


def is_international(team_a, team_b, national):
    return team_a in national and team_b in national


QUERY = """
SELECT a.match_id, m.match_date, m.team_a, m.team_b, m.competition,
       COALESCE(m.match_secs_estimated, 0),
       a.team, a.player_key, a.player_name, a.shirt_number, a.position,
       a.position_number, a.position_group, a.position_source, a.started,
       a.sub_on_minute, a.sub_off_minute, a.minutes_played,
       a.yellow_cards, a.red_cards, a.tries, a.points,
       a.conversions, a.penalty_goals
FROM appearances a JOIN matches m USING (match_id)
ORDER BY m.match_date DESC, a.match_id, a.team, a.shirt_number
"""


def load_rows(db_path, national=NATIONAL_TEAMS):
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(appearances)")}
    if not cols:
        sys.exit(f"{db_path} has no appearances table - run rugby_minutes.py first.")
    if "points" not in cols:
        sys.exit("The database has no try/points columns yet. Run rugby_minutes.py "
                 "with --refresh (same dates as before) to add them, then try again.")
    if "position_group" not in cols:
        sys.exit("The database has no position columns yet. Run rugby_minutes.py "
                 "with --refresh (same dates as before) to add them, then try again.")
    out = []
    for (mid, date, ta, tb, comp, est, team, key, name, shirt, pos, slot, group,
         src, started, on, off, mins, yc, rc, tries, points, conv, pens) in conn.execute(QUERY):
        out.append({
            "id": mid, "d": date, "ma": f"{ta} v {tb}", "c": comp, "est": est,
            "i": 1 if is_international(ta, tb, national) else 0,
            "t": team, "k": key, "p": name, "sh": shirt, "pos": pos, "n": slot,
            "g": group, "src": src, "st": started, "on": on, "off": off,
            "m": mins or 0, "yc": yc or 0, "rc": rc or 0,
            "tr": tries or 0, "pts": points or 0, "cv": conv or 0, "pg": pens or 0,
        })
    return out


def build(db_path, out_path, extra_national=()):
    national = set(NATIONAL_TEAMS) | {t.strip() for t in extra_national if t.strip()}
    rows = load_rows(db_path, national)
    meta = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "db": Path(db_path).name,
    }
    # "</" inside JSON could end the script tag early.
    data_js = json.dumps(rows, separators=(",", ":")).replace("</", "<\\/")
    meta_js = json.dumps(meta).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data_js).replace("__META__", meta_js)
    Path(out_path).write_text(html, encoding="utf-8")
    matches = len({r["id"] for r in rows})
    print(f"Wrote {out_path}: {len(rows)} appearances from {matches} matches")
    stale = [r for r in rows if r["pos"] == "Replacement" or
             (r["src"] is None and r["m"] > 0)]
    if stale:
        n = len({r["id"] for r in stale})
        print(f"WARNING: {len(stale)} appearances in {n} matches have no proper position "
              "(still 'Replacement' or never processed). Run\n"
              "  python rugby_minutes.py --start YYYY-MM-DD --end YYYY-MM-DD --refresh\n"
              "with the latest rugby_minutes.py, then build the dashboard again.")
    other = sorted({(r["d"], r["ma"]) for r in rows if not r["i"]})
    if other:
        print(f"{len(other)} match(es) are NOT counted as internationals (a side is not "
              "in the national-team list):")
        for d, ma in other:
            print(f"  {d}  {ma}")
        print("If one of these is really a national side, re-run with "
              '--national "Team Name".')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="rugby.db")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--national", default="",
                    help="extra national-team names, comma separated")
    args = ap.parse_args()
    build(args.db, args.out, args.national.split(","))


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rugby minutes</title>
<style>
:root {
  --bg: #f6f7f5; --surface: #ffffff; --text: #1b2420; --muted: #5d6b64;
  --border: #dfe4e0; --accent: #1f6f54; --accent-soft: rgba(31, 111, 84, .16);
  --hover: #f0f4f1; --warn: #8a5a00; --yc: #e0b400; --rc: #c0392b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121714; --surface: #1a211d; --text: #e8eeea; --muted: #9aa8a0;
    --border: #2d3832; --accent: #4cc29a; --accent-soft: rgba(76, 194, 154, .22);
    --hover: #212a25; --warn: #e0b45a; --yc: #e0b400; --rc: #ef6a5b;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { color: var(--muted); margin: 0 0 18px; font-size: 14px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 16px; }
.tile { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; }
.tile .v { font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }
.tile .l { color: var(--muted); font-size: 13px; }
.panel { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px; margin-bottom: 16px; }
.filters { display: flex; flex-wrap: wrap; gap: 12px 14px; align-items: flex-end; }
.field { display: flex; flex-direction: column; gap: 4px; min-width: 150px; }
.field label { font-size: 12px; color: var(--muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; }
select, input[type=search], button {
  font: inherit; color: var(--text); background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; }
select:focus-visible, input:focus-visible, button:focus-visible, th button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px; }
button { cursor: pointer; }
button:hover { background: var(--hover); }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; border-radius: 0; background: transparent; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed=true] { background: var(--accent); color: #fff; }
@media (prefers-color-scheme: dark) { .seg button[aria-pressed=true] { color: #0d1511; } }
.checks { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 12px; font-size: 14px; }
.checks label { display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }
.tablewrap { overflow: auto; max-height: 68vh; border: 1px solid var(--border);
  border-radius: 10px; background: var(--surface); }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 10px; text-align: left; white-space: nowrap;
  border-bottom: 1px solid var(--border); }
th { position: sticky; top: 0; background: var(--surface); z-index: 1;
  font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
th button { all: unset; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; }
th.num, td.num { text-align: right; }
th.sel button { color: var(--accent); }
th.sel { background: var(--accent-soft); }
th[aria-sort=ascending] button::after { content: "\25B2"; font-size: 9px; }
th[aria-sort=descending] button::after { content: "\25BC"; font-size: 9px; }
tbody tr:hover { background: var(--hover); }
.mins { position: relative; min-width: 96px; }
.mins .bar { position: absolute; inset: 5px auto 5px 0; background: var(--accent-soft);
  border-radius: 0 4px 4px 0; }
.mins span { position: relative; }
.muted { color: var(--muted); }
.chip { display: inline-block; min-width: 18px; text-align: center; font-size: 11px;
  font-weight: 700; border-radius: 4px; padding: 0 4px; color: #111; margin-right: 3px; }
.chip.y { background: var(--yc); } .chip.r { background: var(--rc); color: #fff; }
.mark { color: var(--warn); cursor: help; }
.pager { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  justify-content: space-between; margin-top: 10px; color: var(--muted); font-size: 14px; }
.pager .btns { display: flex; gap: 8px; align-items: center; }
.empty { padding: 36px; text-align: center; color: var(--muted); }
.note { color: var(--muted); font-size: 13px; margin-top: 14px; }
</style>
</head>
<body>
<main>
  <h1>Rugby minutes</h1>
  <p class="sub" id="sub"></p>

  <section class="tiles" aria-label="Summary of the rows shown">
    <div class="tile"><div class="v" id="t-matches">0</div><div class="l">Matches</div></div>
    <div class="tile"><div class="v" id="t-players">0</div><div class="l">Players</div></div>
    <div class="tile"><div class="v" id="t-apps">0</div><div class="l">Appearances</div></div>
    <div class="tile"><div class="v" id="t-mins">0</div><div class="l" id="t-mins-l">Minutes played</div></div>
  </section>

  <section class="panel" aria-label="Filters">
    <div class="filters">
      <div class="field"><label for="f-type">Matches</label>
        <select id="f-type">
          <option value="intl">Internationals only</option>
          <option value="all">All matches</option>
          <option value="other">Non-internationals only</option>
        </select></div>
      <div class="field"><label for="f-metric">Performance indicator</label>
        <select id="f-metric"></select></div>
      <div class="field"><label for="f-team">Team</label>
        <select id="f-team"></select></div>
      <div class="field"><label for="f-year">Year</label>
        <select id="f-year"></select></div>
      <div class="field"><label for="f-month">Month</label>
        <select id="f-month"></select></div>
      <div class="field"><label for="f-pos">Position</label>
        <select id="f-pos"></select></div>
      <div class="field"><label for="f-q">Player</label>
        <input id="f-q" type="search" placeholder="Search name"></div>
      <div class="field"><label>View</label>
        <div class="seg" role="group" aria-label="View">
          <button id="v-apps" type="button" aria-pressed="true">By match</button>
          <button id="v-totals" type="button" aria-pressed="false">Player totals</button>
        </div></div>
      <button id="reset" type="button">Reset filters</button>
    </div>
    <div class="checks">
      <label><input id="f-played" type="checkbox" checked> Only players who played</label>
      <label><input id="f-uncertain" type="checkbox"> Hide uncertain positions (?)</label>
    </div>
  </section>

  <div class="tablewrap"><table id="tbl"><thead></thead><tbody></tbody></table>
    <div class="empty" id="empty" hidden>No rows match these filters.</div></div>

  <div class="pager">
    <div id="range"></div>
    <div class="btns">
      <label for="f-size">Rows per page</label>
      <select id="f-size"><option>50</option><option selected>100</option>
        <option>250</option><option>1000</option><option value="0">All</option></select>
      <button id="prev" type="button">Previous</button>
      <button id="next" type="button">Next</button>
    </div>
  </div>

  <p class="note"><span class="mark">~</span> approximate minutes: the feed's match clock was
  unusable for that match, so players on the pitch at the end are counted to 80:00 or the
  last recorded event. <span class="mark">?</span> uncertain position: several substitutions
  happened in the same second, so who replaced whom is a guess. Yellow cards are shown but
  sin-bin time is not deducted. Tries and points count the player's own tries, conversions
  and penalty goals; a penalty try is credited to the team only. <span id="gen"></span></p>
</main>

<script>
const DATA = __DATA__;
const META = __META__;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num1 = n => (Math.round(n * 10) / 10).toLocaleString(undefined, {maximumFractionDigits: 1});
const int = n => Math.round(n).toLocaleString();

// Performance indicators: key in the data rows, label, and (for the tile) a unit.
const METRICS = [
  {k: "m", label: "Minutes", tile: "Minutes played"},
  {k: "tr", label: "Tries", tile: "Tries"},
  {k: "pts", label: "Points", tile: "Points"},
  {k: "cv", label: "Conversions", tile: "Conversions"},
  {k: "pg", label: "Penalty goals", tile: "Penalty goals"},
  {k: "yc", label: "Yellow cards", tile: "Yellow cards"},
  {k: "rc", label: "Red cards", tile: "Red cards"},
];
const metricOf = k => METRICS.find(m => m.k === k) || METRICS[0];

const state = {metric: "m", type: "intl", team: "", year: "", month: "", pos: "", q: "", view: "apps", playedOnly: true,
  hideUncertain: false, sortKey: "d", sortDir: "desc", page: 0, size: 100};

const COLS = {
  apps: [
    {k: "d", label: "Date"}, {k: "ma", label: "Match"}, {k: "t", label: "Team"},
    {k: "p", label: "Player"}, {k: "pos", label: "Position"}, {k: "g", label: "Group"},
    {k: "st", label: "Role"}, {k: "m", label: "Minutes", num: true},
    {k: "on", label: "On", num: true}, {k: "off", label: "Off", num: true},
    {k: "tr", label: "Tries", num: true}, {k: "cv", label: "Conv", num: true},
    {k: "pg", label: "Pens", num: true}, {k: "pts", label: "Points", num: true},
    {k: "cards", label: "Cards"}],
  totals: [
    {k: "p", label: "Player"}, {k: "t", label: "Team"}, {k: "pos", label: "Position"},
    {k: "g", label: "Group"}, {k: "apps", label: "Matches", num: true},
    {k: "starts", label: "Starts", num: true}, {k: "m", label: "Total minutes", num: true},
    {k: "avg", label: "Avg per match", num: true},
    {k: "tr", label: "Tries", num: true}, {k: "cv", label: "Conv", num: true},
    {k: "pg", label: "Pens", num: true}, {k: "pts", label: "Points", num: true},
    {k: "yc", label: "Yellow", num: true}, {k: "rc", label: "Red", num: true}],
};
const DEFAULT_SORT = {apps: ["d", "desc"], totals: ["m", "desc"]};
// Choosing an indicator other than minutes sorts by it, highest first.
const defaultSort = view => state.metric !== "m" ? [state.metric, "desc"] : DEFAULT_SORT[view];

function fillSelect(sel, values, allLabel, selected) {
  sel.innerHTML = '<option value="">' + esc(allLabel) + "</option>" +
    values.map(v => "<option>" + esc(v) + "</option>").join("");
  sel.value = values.includes(selected) ? selected : "";
}

function positionOptions() {
  const slot = {};
  DATA.forEach(r => {
    if (!r.pos) return;
    const n = r.n == null ? 99 : r.n;
    if (!(r.pos in slot) || n < slot[r.pos]) slot[r.pos] = n;
  });
  return Object.keys(slot).sort((a, b) => slot[a] - slot[b] || a.localeCompare(b));
}

function setupFilters() {
  $("f-metric").innerHTML = METRICS.map(m =>
    '<option value="' + m.k + '">' + esc(m.label) + "</option>").join("");
  $("f-metric").value = state.metric;
  const inType = r => state.type === "all" || (state.type === "intl") === !!r.i;
  const teams = [...new Set(DATA.filter(inType).map(r => r.t))].sort();
  fillSelect($("f-team"), teams, "All teams", state.team);
  const scoped = DATA.filter(inType);
  const years = [...new Set(scoped.map(r => r.d.slice(0, 4)))].sort();
  fillSelect($("f-year"), years, "All years", state.year);
  state.year = $("f-year").value;
  setupMonths();
  fillSelect($("f-pos"), positionOptions(), "All positions", state.pos);
}

// Months that occur in the chosen match type and year (all years when none is chosen).
function setupMonths() {
  const inType = r => state.type === "all" || (state.type === "intl") === !!r.i;
  const months = [...new Set(DATA.filter(r => inType(r) && (!state.year || r.d.slice(0, 4) === state.year))
    .map(r => r.d.slice(5, 7)))].sort();
  const sel = $("f-month");
  sel.innerHTML = '<option value="">All months</option>' +
    months.map(m => '<option value="' + m + '">' + MONTHS[+m - 1] + "</option>").join("");
  sel.value = months.includes(state.month) ? state.month : "";
  state.month = sel.value;
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  return DATA.filter(r =>
    (state.type === "all" || (state.type === "intl") === !!r.i) &&
    (!state.team || r.t === state.team) &&
    (!state.year || r.d.slice(0, 4) === state.year) &&
    (!state.month || r.d.slice(5, 7) === state.month) &&
    (!state.pos || r.pos === state.pos) &&
    (!state.playedOnly || r.m > 0) &&
    (state.metric === "m" || r[state.metric] > 0) &&
    (!state.hideUncertain || r.src !== "replaced_ambiguous") &&
    (!q || (r.p || "").toLowerCase().includes(q)));
}

function isApprox(r) { return r.est && r.m > 0 && r.off == null; }

function aggregate(rows) {
  const map = new Map();
  rows.forEach(r => {
    const key = r.k + "|" + r.t + "|" + (r.pos || "");
    let a = map.get(key);
    if (!a) {
      a = {p: r.p, t: r.t, pos: r.pos, g: r.g, apps: 0, starts: 0, m: 0, tr: 0, pts: 0, cv: 0, pg: 0, yc: 0, rc: 0,
           approx: false, uncertain: false};
      map.set(key, a);
    }
    if (r.m > 0) a.apps++;
    a.starts += r.st ? 1 : 0;
    a.m += r.m;
    a.tr += r.tr;
    a.pts += r.pts;
    a.cv += r.cv;
    a.pg += r.pg;
    a.yc += r.yc;
    a.rc += r.rc;
    a.approx = a.approx || isApprox(r);
    a.uncertain = a.uncertain || r.src === "replaced_ambiguous";
  });
  const out = [...map.values()];
  out.forEach(a => { a.avg = a.apps ? a.m / a.apps : 0; });
  return out;
}

function cmp(a, b, key, dir) {
  let x = a[key], y = b[key];
  if (key === "cards") { x = a.yc * 10 + a.rc * 100; y = b.yc * 10 + b.rc * 100; }
  const nx = x == null || x === "", ny = y == null || y === "";
  if (nx || ny) return nx && ny ? 0 : nx ? 1 : -1;   // blanks always last
  const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
  return dir === "asc" ? r : -r;
}

function posCell(r) {
  if (!r.pos) return '<span class="muted">-</span>';
  const mark = r.src === "replaced_ambiguous" || r.uncertain
    ? ' <span class="mark" title="Uncertain: several substitutions at the same second">?</span>' : "";
  return esc(r.pos) + mark;
}

function minsCell(value, max, approx) {
  const w = max ? Math.min(100, value / max * 100) : 0;
  const mark = approx ? ' <span class="mark" title="Approximate: match clock unusable">~</span>' : "";
  return '<td class="num mins"><div class="bar" style="width:' + w.toFixed(1) +
    '%"></div><span>' + num1(value) + mark + "</span></td>";
}

function renderHead() {
  const cols = COLS[state.view];
  $("tbl").tHead.innerHTML = "<tr>" + cols.map(c => {
    const sorted = state.sortKey === c.k;
    const sort = sorted ? (state.sortDir === "asc" ? "ascending" : "descending") : "none";
    const sel = c.k === state.metric ? " sel" : "";
    return '<th class="' + (c.num ? "num" : "") + sel + '" aria-sort="' + sort + '">' +
      '<button type="button" data-key="' + c.k + '">' + esc(c.label) + "</button></th>";
  }).join("") + "</tr>";
}

function render() {
  const rows = filtered();
  const totals = state.view === "totals";
  const data = totals ? aggregate(rows) : rows.slice();
  data.sort((a, b) => cmp(a, b, state.sortKey, state.sortDir));

  // Summary tiles describe everything that matches the filters, not just this page.
  $("t-matches").textContent = int(new Set(rows.map(r => r.id)).size);
  $("t-players").textContent = int(new Set(rows.map(r => r.k)).size);
  $("t-apps").textContent = int(rows.filter(r => r.m > 0).length);
  $("t-mins").textContent = int(rows.reduce((s, r) => s + (r[state.metric] || 0), 0));
  $("t-mins-l").textContent = metricOf(state.metric).tile;

  const size = state.size || data.length || 1;
  const pages = Math.max(1, Math.ceil(data.length / size));
  state.page = Math.min(state.page, pages - 1);
  const start = state.page * size;
  const shown = data.slice(start, start + size);
  const maxM = data.reduce((m, r) => Math.max(m, r.m), 0);

  renderHead();
  $("tbl").tBodies[0].innerHTML = shown.map(r => totals ? totalsRow(r, maxM) : appRow(r, maxM)).join("");
  $("empty").hidden = data.length > 0;
  $("range").textContent = data.length
    ? "Showing " + int(start + 1) + "-" + int(start + shown.length) + " of " + int(data.length) +
      (totals ? " player/position rows" : " rows")
    : "0 rows";
  $("prev").disabled = state.page === 0;
  $("next").disabled = state.page >= pages - 1;
}

function appRow(r, maxM) {
  const cards = (r.yc ? '<span class="chip y" title="Yellow card">Y' + (r.yc > 1 ? r.yc : "") + "</span>" : "") +
                (r.rc ? '<span class="chip r" title="Red card">R</span>' : "");
  return "<tr><td>" + esc(r.d) + "</td><td>" + esc(r.ma) + "</td><td>" + esc(r.t) + "</td><td>" +
    esc(r.p) + "</td><td>" + posCell(r) + "</td><td>" + esc(r.g || "") + "</td><td>" +
    (r.st ? "Start" : '<span class="muted">Bench</span>') + "</td>" +
    minsCell(r.m, maxM, isApprox(r)) +
    '<td class="num">' + (r.on == null ? "" : num1(r.on)) + '</td><td class="num">' +
    (r.off == null ? "" : num1(r.off)) + '</td><td class="num">' + (r.tr || "") +
    '</td><td class="num">' + (r.cv || "") + '</td><td class="num">' + (r.pg || "") +
    '</td><td class="num">' + (r.pts || "") + "</td><td>" + cards + "</td></tr>";
}

function totalsRow(a, maxM) {
  return "<tr><td>" + esc(a.p) + "</td><td>" + esc(a.t) + "</td><td>" + posCell(a) +
    "</td><td>" + esc(a.g || "") + '</td><td class="num">' + int(a.apps) +
    '</td><td class="num">' + int(a.starts) + "</td>" + minsCell(a.m, maxM, a.approx) +
    '<td class="num">' + num1(a.avg) + '</td><td class="num">' + (a.tr || "") +
    '</td><td class="num">' + (a.cv || "") + '</td><td class="num">' + (a.pg || "") +
    '</td><td class="num">' + (a.pts || "") + '</td><td class="num">' + (a.yc || "") +
    '</td><td class="num">' + (a.rc || "") + "</td></tr>";
}

function setView(view) {
  state.view = view;
  [state.sortKey, state.sortDir] = defaultSort(view);
  state.page = 0;
  $("v-apps").setAttribute("aria-pressed", view === "apps");
  $("v-totals").setAttribute("aria-pressed", view === "totals");
  render();
}

function wire() {
  $("f-metric").onchange = e => {
    state.metric = e.target.value;
    [state.sortKey, state.sortDir] = defaultSort(state.view);
    state.page = 0; render();
  };
  $("f-type").onchange = e => {
    state.type = e.target.value; state.page = 0; setupFilters();
    state.team = $("f-team").value; state.pos = $("f-pos").value; render();
  };
  $("f-team").onchange = e => { state.team = e.target.value; state.page = 0; render(); };
  $("f-year").onchange = e => {
    state.year = e.target.value; setupMonths(); state.page = 0; render();
  };
  $("f-month").onchange = e => { state.month = e.target.value; state.page = 0; render(); };
  $("f-pos").onchange = e => { state.pos = e.target.value; state.page = 0; render(); };
  $("f-q").oninput = e => { state.q = e.target.value; state.page = 0; render(); };
  $("f-played").onchange = e => { state.playedOnly = e.target.checked; state.page = 0; render(); };
  $("f-uncertain").onchange = e => { state.hideUncertain = e.target.checked; state.page = 0; render(); };
  $("f-size").onchange = e => { state.size = +e.target.value; state.page = 0; render(); };
  $("v-apps").onclick = () => setView("apps");
  $("v-totals").onclick = () => setView("totals");
  $("prev").onclick = () => { state.page--; render(); };
  $("next").onclick = () => { state.page++; render(); };
  $("reset").onclick = () => {
    Object.assign(state, {metric: "m", type: "intl", team: "", year: "", month: "", pos: "", q: "", playedOnly: true, hideUncertain: false});
    $("f-type").value = "intl"; $("f-q").value = ""; $("f-played").checked = true; $("f-uncertain").checked = false;
    setupFilters(); setView(state.view);
  };
  $("tbl").tHead.onclick = e => {
    const b = e.target.closest("button[data-key]");
    if (!b) return;
    const key = b.dataset.key;
    if (state.sortKey === key) state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
    else { state.sortKey = key; state.sortDir = ["m", "avg", "apps", "starts", "d", "tr", "pts", "cv", "pg", "yc", "rc"].includes(key) ? "desc" : "asc"; }
    render();
  };
}

(function init() {
  const dates = DATA.map(r => r.d).sort();
  $("sub").textContent = DATA.length
    ? DATA.length.toLocaleString() + " appearances, " + new Set(DATA.map(r => r.id)).size +
      " matches, " + dates[0] + " to " + dates[dates.length - 1]
    : "No data yet - run rugby_minutes.py first.";
  $("gen").textContent = "Built " + META.generated + " from " + META.db + ".";
  setupFilters(); wire(); render();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
