"""Offline tests for the minutes calculation, using a trimmed copy of the
Japan v Fiji match (24 Oct 2026) taken from World Rugby's feed.

Run from the rugby-minutes folder:  python -m unittest discover -s tests -v
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import rugby_minutes as rm  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "japan_fiji_2026-10-24.json").read_text())
MATCH_END = 4812  # 80:12 on the match clock


class MinutesTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.warnings = rm.compute_appearances(
            FIXTURE["summary"], FIXTURE["timeline"])
        self.by_name = {r["player_name"]: r for r in self.rows}

    def test_no_warnings(self):
        self.assertEqual(self.warnings, [])

    def test_squad_sizes(self):
        self.assertEqual(len(self.rows), 46)  # coaches excluded
        for team in ("Japan", "Fiji"):
            starters = [r for r in self.rows if r["team"] == team and r["started"]]
            self.assertEqual(len(starters), 15)

    def test_starter_replaced(self):
        r = self.by_name["Yota Kamimori"]  # off at 2693s (44:53)
        self.assertEqual(r["seconds_played"], 2693)
        self.assertEqual(r["minutes_played"], 44.9)
        self.assertEqual(r["sub_off_minute"], 44.9)
        self.assertIsNone(r["sub_on_minute"])

    def test_replacement_on(self):
        r = self.by_name["Sojiro Otsuka"]  # on at 2693s until the end
        self.assertEqual(r["seconds_played"], MATCH_END - 2693)
        self.assertEqual(r["minutes_played"], 35.3)
        self.assertEqual(r["sub_on_minute"], 44.9)
        self.assertIsNone(r["sub_off_minute"])
        self.assertEqual(r["started"], 0)
        self.assertEqual(r["appeared"], 1)

    def test_starter_full_match(self):
        r = self.by_name["Ryunosuke Ito"]
        self.assertEqual(r["seconds_played"], MATCH_END)
        self.assertEqual(r["minutes_played"], 80.2)

    def test_red_card_ends_time(self):
        r = self.by_name["Motikiai Murray"]  # red card at 2002s (33:22)
        self.assertEqual(r["seconds_played"], 2002)
        self.assertEqual(r["red_cards"], 1)

    def test_id_forms_both_resolved(self):
        # Events use the short numeric id for some players, a UUID for others.
        self.assertEqual(self.by_name["Naoto Saito"]["seconds_played"], 4017)
        self.assertEqual(self.by_name["Takuro Matsunaga"]["seconds_played"], MATCH_END)

    def test_team_totals(self):
        # Japan: no cards, 15 on the pitch the whole match.
        japan = sum(r["seconds_played"] for r in self.rows if r["team"] == "Japan")
        self.assertEqual(japan, 15 * MATCH_END)
        # Fiji: down to 14 from the red card at 2002s.
        fiji = sum(r["seconds_played"] for r in self.rows if r["team"] == "Fiji")
        self.assertEqual(fiji, 15 * MATCH_END - (MATCH_END - 2002))

    def test_unused_replacement_has_zero_minutes(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        # Drop Kenji Sato's "on" event so he never plays.
        timeline["timeline"] = [
            e for e in timeline["timeline"]
            if not (e["typeLabel"] == "Replacement On"
                    and e["playerId"] == "2cb691be-52f7-4c69-a685-4984ad9c7255")]
        rows, warnings = rm.compute_appearances(FIXTURE["summary"], timeline)
        sato = next(r for r in rows if r["player_name"] == "Kenji Sato")
        self.assertEqual(sato["minutes_played"], 0)
        self.assertEqual(sato["appeared"], 0)
        self.assertTrue(any("replacements on but" in w for w in warnings))

    def test_player_can_return_after_going_off(self):
        # A temporary replacement: Ito off at 1000s, back on at 1600s.
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        ito = "35cfb35c-4f88-4db4-a6c8-2c83c93cc1e5"
        timeline["timeline"] += [
            {"type": "Sub Off", "typeLabel": "Replacement Off", "teamIndex": 0,
             "playerId": ito, "time": {"secs": 1000}},
            {"type": "Sub On", "typeLabel": "Replacement On", "teamIndex": 0,
             "playerId": ito, "time": {"secs": 1600}},
        ]
        rows, _ = rm.compute_appearances(FIXTURE["summary"], timeline)
        r = next(x for x in rows if x["player_name"] == "Ryunosuke Ito")
        self.assertEqual(r["seconds_played"], MATCH_END - 600)

    def test_yellow_card_counted(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"].append(
            {"type": "Yellow", "typeLabel": "Yellow Card", "teamIndex": 0,
             "playerId": "35cfb35c-4f88-4db4-a6c8-2c83c93cc1e5",
             "time": {"secs": 900}})
        rows, _ = rm.compute_appearances(FIXTURE["summary"], timeline)
        r = next(x for x in rows if x["player_name"] == "Ryunosuke Ito")
        self.assertEqual(r["yellow_cards"], 1)
        self.assertEqual(r["seconds_played"], MATCH_END)  # sin-bin not deducted


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.rows, _ = rm.compute_appearances(FIXTURE["summary"], FIXTURE["timeline"])
        self.by_name = {r["player_name"]: r for r in self.rows}

    def test_starter_keeps_listed_position(self):
        r = self.by_name["Yota Kamimori"]
        self.assertEqual((r["position"], r["position_number"], r["position_group"],
                          r["position_source"]),
                         ("Prop", 1, "Front row", "listed"))

    def test_substitute_takes_position_of_player_replaced(self):
        cases = {
            "Sojiro Otsuka": ("Prop", 1, "Front row"),        # for Kamimori
            "Sanshiro Kihara": ("Prop", 3, "Front row"),      # for Tamefusa
            "Michael Stolberg": ("Number 8", 8, "Back row"),  # for Makisi
            "Jisu Lee": ("Centre", 12, "Centres"),            # for Lawrence
            "Kenji Sato": ("Hooker", 2, "Front row"),         # for Harada
            "Kavaia Tagivetaua": ("Hooker", 2, "Front row"),  # Fiji, for Ikanivere
        }
        for name, (pos, num, group) in cases.items():
            r = self.by_name[name]
            self.assertEqual((r["position"], r["position_number"], r["position_group"]),
                             (pos, num, group), name)
            self.assertEqual(r["position_source"], "replaced", name)
            self.assertEqual(r["listed_position"], "Replacement", name)

    def test_starter_wearing_a_bench_number_uses_lineup_order(self):
        # Late change: a bench player promoted into the XV keeps his bench number
        # (seen for real: a flanker wearing #20 and a full back wearing #23).
        summary = json.loads(json.dumps(FIXTURE["summary"]))
        for entry in summary["teams"][0]["teamList"]["list"]:
            if entry["player"]["name"]["display"] == "Naoto Saito":  # scrum-half
                entry["number"] = "22"
        rows, warnings = rm.compute_appearances(summary, FIXTURE["timeline"])
        saito = next(r for r in rows if r["player_name"] == "Naoto Saito")
        self.assertEqual((saito["position_number"], saito["position_group"],
                          saito["shirt_number"], saito["position_source"]),
                         (9, "Half-backs", 22, "listed"))
        self.assertTrue(any("Naoto Saito started wearing #22" in w for w in warnings))
        # The substitute who replaced him (Fujiwara, on at 4017s) inherits slot 9.
        fujiwara = next(r for r in rows if r["player_name"] == "Shinobu Fujiwara")
        self.assertEqual(fujiwara["position_number"], 9)

    def test_unknown_order_for_odd_number_is_warned_not_guessed(self):
        summary = json.loads(json.dumps(FIXTURE["summary"]))
        for entry in summary["teams"][0]["teamList"]["list"]:
            if entry["player"]["name"]["display"] == "Naoto Saito":
                entry["number"] = "22"
                entry["order"] = 99
        rows, warnings = rm.compute_appearances(summary, FIXTURE["timeline"])
        saito = next(r for r in rows if r["player_name"] == "Naoto Saito")
        self.assertIsNone(saito["position_number"])
        self.assertTrue(any("not recognised" in w for w in warnings))

    def test_unused_bench_player_has_no_position(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"] = [
            e for e in timeline["timeline"]
            if e.get("playerId") not in ("2cb691be-52f7-4c69-a685-4984ad9c7255", "65987")]
        rows, _ = rm.compute_appearances(FIXTURE["summary"], timeline)
        sato = next(r for r in rows if r["player_name"] == "Kenji Sato")
        self.assertIsNone(sato["position"])
        self.assertEqual(sato["position_source"], "never played")

    def test_chain_of_substitutions_passes_position_on(self):
        # Otsuka (on for the #1 prop at 2693s) is himself replaced by Sato at 3000s.
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"] = [
            e for e in timeline["timeline"]
            if e.get("playerId") not in ("2cb691be-52f7-4c69-a685-4984ad9c7255", "65987")]
        timeline["timeline"] += [
            {"type": "Sub On", "typeLabel": "Replacement On", "teamIndex": 0,
             "playerId": "2cb691be-52f7-4c69-a685-4984ad9c7255", "time": {"secs": 3000}},
            {"type": "Sub Off", "typeLabel": "Replacement Off", "teamIndex": 0,
             "playerId": "8bb5c19d-c5f7-4bdf-b985-c1871a0ada7f", "time": {"secs": 3000}},
        ]
        rows, _ = rm.compute_appearances(FIXTURE["summary"], timeline)
        sato = next(r for r in rows if r["player_name"] == "Kenji Sato")
        self.assertEqual((sato["position"], sato["position_number"]), ("Prop", 1))
        self.assertEqual(sato["position_source"], "replaced")

    def test_several_swaps_in_one_second_is_flagged_ambiguous(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"] = [e for e in timeline["timeline"]
                                if e["time"]["secs"] not in (3226, 3227)]
        # Two Fiji swaps at the same second (half-time style bulk change).
        for pid_on, pid_off in (("58928041-5874-4213-9534-c676c78b0ff5", "64556"),
                                ("42557", "b54732a0-b196-4981-ad07-6799f0cabe8b")):
            timeline["timeline"] += [
                {"type": "Sub On", "typeLabel": "Replacement On", "teamIndex": 1,
                 "playerId": pid_on, "time": {"secs": 3300}},
                {"type": "Sub Off", "typeLabel": "Replacement Off", "teamIndex": 1,
                 "playerId": pid_off, "time": {"secs": 3300}},
            ]
        rows, _ = rm.compute_appearances(FIXTURE["summary"], timeline)
        for name in ("Kavaia Tagivetaua", "Ben Volavola"):
            r = next(x for x in rows if x["player_name"] == name)
            self.assertEqual(r["position_source"], "replaced_ambiguous", name)

    def test_position_saved_to_database(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(rm.SCHEMA)
        rm.save_match(conn, FIXTURE["summary"], self.rows, FIXTURE["timeline"])
        got = conn.execute(
            "SELECT position, position_number, position_group, position_source, "
            "minutes_played FROM appearances WHERE player_name = ?",
            ("Sojiro Otsuka",)).fetchone()
        self.assertEqual(got, ("Prop", 1, "Front row", "replaced", 35.3))

    def test_old_appearances_table_gets_new_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE appearances (match_id TEXT, player_key TEXT, position TEXT)")
        rm.migrate(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(appearances)")}
        self.assertTrue({"listed_position", "position_number", "position_group",
                         "position_source"} <= cols)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.warnings = rm.compute_appearances(
            FIXTURE["summary"], FIXTURE["timeline"])
        self.by_name = {r["player_name"]: r for r in self.rows}

    def test_tries_and_points(self):
        r = self.by_name["Kazuma Ueda"]
        self.assertEqual((r["tries"], r["points"]), (2, 10))

    def test_kicker_points(self):
        r = self.by_name["Isaiah Armstrong-Ravula"]
        self.assertEqual((r["conversions"], r["penalty_goals"], r["points"]), (3, 2, 12))
        self.assertEqual(self.by_name["Ryunosuke Ito"]["points"], 8)

    def test_team_points_equal_final_score_including_penalty_try(self):
        self.assertEqual(self.warnings, [])  # includes the score reconciliation
        fiji = sum(r["points"] for r in self.rows if r["team"] == "Fiji")
        self.assertEqual(fiji, 27)  # plus a 7-point penalty try = 34

    def test_mismatch_with_final_score_is_warned(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"] = [e for e in timeline["timeline"]
                                if not (e.get("typeLabel") == "Try" and e["time"]["secs"] == 600)]
        _, warnings = rm.compute_appearances(FIXTURE["summary"], timeline)
        self.assertTrue(any("Japan" in w and "23 points" in w for w in warnings), warnings)

    def test_unmatched_scorer_is_warned_but_team_points_still_count(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        for e in timeline["timeline"]:
            if e.get("typeLabel") == "Try" and e["time"]["secs"] == 600:
                e["playerId"] = "no-such-player"
        _, warnings = rm.compute_appearances(FIXTURE["summary"], timeline)
        self.assertEqual(len(warnings), 1)
        self.assertIn("could not be matched", warnings[0])

    def test_missed_conversion_and_hia_labels_are_not_scores(self):
        for label in ("Missed Conversion", "Replacement On - HIAO Return", "Yellow Card"):
            self.assertNotIn(rm._classify({"typeLabel": label}), rm.SCORE_POINTS)
        self.assertEqual(rm._classify({"typeLabel": "Penalty Try"}), "penalty_try")
        self.assertEqual(rm._classify({"typeLabel": "Penalty"}), "penalty_goal")
        self.assertEqual(rm._classify({"typeLabel": "Replacement On - HIAO Return"}), "on")

    def test_player_nested_in_event_is_found(self):
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        for e in timeline["timeline"]:
            if e.get("typeLabel") == "Try" and e["time"]["secs"] == 600:
                e["player"] = {"id": e.pop("playerId")}
        rows, warnings = rm.compute_appearances(FIXTURE["summary"], timeline)
        self.assertEqual(warnings, [])

    def test_scores_saved_and_old_database_migrated(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(rm.SCHEMA)
        rm.save_match(conn, FIXTURE["summary"], self.rows, FIXTURE["timeline"])
        got = conn.execute("SELECT tries, conversions, penalty_goals, points FROM "
                           "appearances WHERE player_name = 'Isaiah Armstrong-Ravula'").fetchone()
        self.assertEqual(got, (0, 3, 2, 12))
        old = sqlite3.connect(":memory:")
        old.execute("CREATE TABLE appearances (match_id TEXT, player_key TEXT)")
        rm.migrate(old)
        cols = {r[1] for r in old.execute("PRAGMA table_info(appearances)")}
        self.assertTrue({"tries", "conversions", "penalty_goals", "drop_goals",
                         "points"} <= cols)


class BadClockTests(unittest.TestCase):
    """The feed sometimes leaves the match clock running after full time."""

    def _with_clock(self, secs):
        summary = json.loads(json.dumps(FIXTURE["summary"]))
        summary["match"]["clock"] = {"secs": secs, "label": "bogus"}
        return summary

    def test_runaway_clock_falls_back_to_80_minutes(self):
        summary = self._with_clock(10769076)  # 179484:36, as seen in the feed
        rows, warnings = rm.compute_appearances(summary, FIXTURE["timeline"])
        self.assertTrue(any("match clock unusable" in w for w in warnings))
        japan = sum(r["seconds_played"] for r in rows if r["team"] == "Japan")
        self.assertEqual(japan, 15 * 4800)
        self.assertEqual(max(r["minutes_played"] for r in rows), 80.0)

    def test_zero_clock_falls_back(self):
        summary = self._with_clock(0)
        end, estimated = rm.effective_match_secs(summary, FIXTURE["timeline"])
        self.assertEqual((end, estimated), (4800, True))

    def test_late_event_extends_the_fallback(self):
        summary = self._with_clock(10769076)
        timeline = json.loads(json.dumps(FIXTURE["timeline"]))
        timeline["timeline"].append(
            {"type": "Try", "typeLabel": "Try", "teamIndex": 0, "playerId": None,
             "time": {"secs": 4950}})
        end, estimated = rm.effective_match_secs(summary, timeline)
        self.assertEqual((end, estimated), (4950, True))

    def test_good_clock_is_kept(self):
        end, estimated = rm.effective_match_secs(FIXTURE["summary"], FIXTURE["timeline"])
        self.assertEqual((end, estimated), (4812, False))

    def test_estimated_flag_saved(self):
        summary = self._with_clock(10769076)
        rows, _ = rm.compute_appearances(summary, FIXTURE["timeline"])
        conn = sqlite3.connect(":memory:")
        conn.executescript(rm.SCHEMA)
        rm.save_match(conn, summary, rows, FIXTURE["timeline"])
        row = conn.execute(
            "SELECT match_secs, match_secs_estimated FROM matches").fetchone()
        self.assertEqual(row, (4800, 1))

    def test_old_database_is_migrated(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, match_date TEXT, "
                     "competition TEXT, sport TEXT, venue TEXT, city TEXT, team_a TEXT, "
                     "team_b TEXT, score_a INTEGER, score_b INTEGER, match_secs INTEGER)")
        rm.migrate(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
        self.assertIn("match_secs_estimated", cols)


class DatabaseTests(unittest.TestCase):
    def test_save_and_requery(self):
        rows, _ = rm.compute_appearances(FIXTURE["summary"], FIXTURE["timeline"])
        conn = sqlite3.connect(":memory:")
        conn.executescript(rm.SCHEMA)
        rm.save_match(conn, FIXTURE["summary"], rows)
        rm.save_match(conn, FIXTURE["summary"], rows)  # re-save must not duplicate
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM appearances").fetchone()[0], 46)
        mins = conn.execute(
            "SELECT minutes_played FROM appearances WHERE player_name = ?",
            ("Yota Kamimori",)).fetchone()[0]
        self.assertEqual(mins, 44.9)


class TeamFilterTests(unittest.TestCase):
    def _run(self, matches, teams=rm.DEFAULT_TEAMS, both=False, sport="MRU"):
        original = rm.http_get_json
        rm.http_get_json = lambda url, **kw: {
            "pageInfo": {"numPages": 1}, "content": matches}
        try:
            return [m["matchId"] for m in rm.list_matches(
                "2026-01-01", "2026-12-31", sport, teams, both, 0)]
        finally:
            rm.http_get_json = original

    @staticmethod
    def _m(mid, a, b, sport="MRU"):
        return {"matchId": mid, "sport": sport,
                "teams": [{"name": a}, {"name": b}]}

    def test_default_filter(self):
        matches = [
            self._m("1", "New Zealand", "France"),
            self._m("2", "Japan", "Fiji"),
            self._m("3", "Ireland", "South Africa"),
            self._m("4", "USA", "Australia A"),          # "A" side: excluded
            self._m("5", "Australia", "Argentina"),
            self._m("6", "New Zealand", "Australia", sport="WRU"),  # women's
        ]
        self.assertEqual(self._run(matches), ["1", "3", "5"])

    def test_both_teams_option(self):
        matches = [self._m("1", "New Zealand", "France"),
                   self._m("2", "New Zealand", "South Africa")]
        self.assertEqual(self._run(matches, both=True), ["2"])

    def test_custom_teams_case_insensitive(self):
        matches = [self._m("1", "Fiji", "Japan")]
        self.assertEqual(self._run(matches, teams="fiji"), ["1"])


if __name__ == "__main__":
    unittest.main()
