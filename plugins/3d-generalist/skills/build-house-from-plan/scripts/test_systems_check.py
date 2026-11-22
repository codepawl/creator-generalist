"""Tests for systems_check.py on examples/systems-fixture.json, a four-room house with a kitchen and a bath.

    uv run --no-project python scripts/test_systems_check.py
"""

import copy
import json
import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import systems_check  # noqa: E402

FIXTURE = SCRIPTS.parent / "examples" / "systems-fixture.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def checks_named(report, rule):
    return [check for check in report["checks"] if check["rule"] == rule]


class FixturePasses(unittest.TestCase):
    def test_every_rule_passes_after_rerouting(self):
        report = systems_check.run(load_fixture())
        failed = [check for check in report["checks"] if check["status"] != "pass"]
        self.assertEqual(failed, [])
        self.assertEqual(report["unresolved"], [])
        self.assertTrue(report["passed"])

    def test_long_trap_arms_get_individual_vents(self):
        report = systems_check.run(load_fixture())
        self.assertIn("lav: individual vent in the nearest wall", report["reroutes"])
        vents = [element for element in report["elements"] if element["kind"] == "individual_vent"]
        self.assertTrue(vents)
        for check in checks_named(report, "trap arm"):
            self.assertLessEqual(check["value_m"], check["limit_m"])

    def test_no_two_trades_left_crossing(self):
        report = systems_check.run(load_fixture())
        runs = report["runs"]
        for later_index, later in enumerate(runs):
            for earlier in runs[:later_index]:
                if later["trade"] != earlier["trade"]:
                    self.assertFalse(systems_check.runs_clash(later, earlier), f"{later['kind']} x {earlier['kind']}")


class ElectricalRules(unittest.TestCase):
    def test_every_kitchen_and_bath_receptacle_is_gfci(self):
        report = systems_check.run(load_fixture())
        for element in report["elements"]:
            if element.get("room") in ("Kitchen", "Bath") and "receptacle" in element["kind"]:
                self.assertTrue(element["gfci"], element)

    def test_bedroom_gets_smoke_alarm_and_house_gets_co_alarm(self):
        report = systems_check.run(load_fixture())
        self.assertEqual([check["status"] for check in checks_named(report, "smoke alarm in bedroom")], ["pass"])
        self.assertEqual([check["status"] for check in checks_named(report, "CO alarm outside sleeping areas")], ["pass"])

    def test_receptacles_avoid_floor_to_ceiling_glass(self):
        plan = load_fixture()
        # Glaze the whole west wall to the floor: a wall receptacle there is impossible, so it must move.
        for opening in plan["openings"]:
            if opening["id"] == "living_glass":
                opening.update({"at": 3.5, "width": 6.8})
        report = systems_check.run(plan)
        self.assertTrue(any("glass" in clash for clash in report["first_pass_clashes"]))
        self.assertTrue(any("floor receptacle" in line or "solid wall" in line for line in report["reroutes"]))
        self.assertEqual([check["status"] for check in checks_named(report, "receptacle spacing") if check.get("item") == "Living"], ["pass"])


class PlumbingRules(unittest.TestCase):
    def test_drain_fall_fails_when_floor_is_too_shallow(self):
        plan = load_fixture()
        plan["systems"]["drain_depth_m"] = 0.01
        report = systems_check.run(plan)
        self.assertEqual([check["status"] for check in checks_named(report, "drain fall fits under the floor")], ["fail"])
        self.assertFalse(report["passed"])


class GasRules(unittest.TestCase):
    def test_gas_boiler_in_closet_gets_outdoor_combustion_air(self):
        plan = copy.deepcopy(load_fixture())
        plan["rooms"].append({"name": "Closet", "kind": "utility", "poly": [[0, 6], [1, 6], [1, 7], [0, 7]]})
        plan["rooms"][0]["poly"] = [[0, 0], [5, 0], [5, 7], [1, 7], [1, 6], [0, 6]]
        plan["walls"] += [{"id": "closet_s", "a": [0, 6], "b": [1, 6], "t": 0.1, "kind": "int"},
                          {"id": "closet_e", "a": [1, 6], "b": [1, 7], "t": 0.1, "kind": "int"}]
        plan["systems"]["appliances"].append({"id": "boiler", "kind": "boiler", "fuel": "gas", "room": "Closet", "at": [0.5, 6.5]})
        report = systems_check.run(plan)
        self.assertTrue(any("combustion air" in line for line in report["reroutes"]))
        self.assertEqual({check["status"] for check in checks_named(report, "combustion air")}, {"pass"})
        self.assertEqual({check["status"] for check in checks_named(report, "gas shutoff")}, {"pass"})


if __name__ == "__main__":
    unittest.main()
