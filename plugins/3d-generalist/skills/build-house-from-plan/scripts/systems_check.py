"""Route a house's services (power, water, drains and vents, gas, heating, exhaust) from plan.json and check the
layout against the residential code rules a first draft must meet. Layout and code checks only: no load
calculations, pipe or duct sizing beyond the tables below, and no substitute for a licensed designer.

Usage: uv run --no-project python systems_check.py plan.json
Writes systems_report.json and systems.md beside the plan. Exit 1 when any rule fails after rerouting.
Rules and the plan keys it reads: references/systems.md.
"""
import json
import math
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

METRES_PER_UNIT = {"m": 1.0, "ft": 0.3048}
FOOT = 0.3048

# NEC 210.52(A): no point along a wall line more than 6 ft from a receptacle; wall spaces of 2 ft and up count.
RECEPTACLE_REACH_M = 6 * FOOT
SMALLEST_WALL_SPACE_M = 2 * FOOT
# NEC 210.52(C): no point along a counter more than 24 in from a receptacle.
COUNTER_REACH_M = 2 * FOOT
FLOOR_RECEPTACLE_WALL_GAP_M = 18 * 0.0254
RECEPTACLE_ROOMS = {"bedroom", "living", "dining", "family", "den", "study", "office", "library", "kitchen", "sunroom",
                    "playroom", "workshop"}
GFCI_ROOMS = {"bath", "laundry", "garage", "carport", "utility"}
# NEC 2023 210.8(A)(6): every 125 V receptacle in a kitchen, not only the counter ones.
GFCI_RECEPTACLE_ROOMS = GFCI_ROOMS | {"kitchen"}
SLEEPING_ROOMS = {"bedroom"}
# IRC P3105.1 trap arm lengths by trap size, P3004.1 drainage fixture units, P3201.7 trap sizes.
TRAP_ARM_LIMIT_M = {1.25: 5 * FOOT, 1.5: 6 * FOOT, 2.0: 8 * FOOT, 3.0: 12 * FOOT, 4.0: 16 * FOOT}
FIXTURES = {
    "lavatory": {"trap": 1.25, "dfu": 1, "hot": True, "cold": True},
    "sink": {"trap": 1.5, "dfu": 2, "hot": True, "cold": True},
    "dishwasher": {"trap": None, "dfu": 2, "hot": True, "cold": False},
    "shower": {"trap": 2.0, "dfu": 2, "hot": True, "cold": True},
    "tub": {"trap": 1.5, "dfu": 2, "hot": True, "cold": True},
    "toilet": {"trap": 3.0, "dfu": 3, "hot": False, "cold": True},
    "washer": {"trap": 2.0, "dfu": 2, "hot": True, "cold": True},
    "laundry_tub": {"trap": 1.5, "dfu": 2, "hot": True, "cold": True},
    "floor_drain": {"trap": 2.0, "dfu": 2, "hot": False, "cold": False},
    "hose_bib": {"trap": None, "dfu": 0, "hot": False, "cold": True},
}
BATHING_FIXTURES = {"toilet", "shower", "tub"}
# IRC P3005.3: 1/4 in per ft below 3 in, 1/8 in per ft from 3 in.
DRAIN_SLOPE_SMALL = 0.25 / 12
DRAIN_SLOPE_LARGE = 0.125 / 12
# WaterSense: at most 0.5 gal (1.89 L) of water between the heater and a hot fixture.
HOT_WATER_LIMIT_L = 1.89
PEX_LITRES_PER_METRE = {"1/2": 0.1144, "3/8": 0.0622}
SMALL_PEX_FIXTURES = {"lavatory", "sink", "dishwasher"}
# IFGC 409.5.1: the shutoff sits in the same room, within 6 ft of the appliance. IFGC 304.5.1: 50 cu ft of room per
# 1,000 Btu/h of vented appliance input, or air from outdoors.
GAS_SHUTOFF_REACH_M = 6 * FOOT
ROOM_AIR_M3_PER_KBTU = 50 * FOOT ** 3
GAS_INPUT_KBTU = {"furnace": 60, "boiler": 80, "water_heater": 40, "range": 65, "dryer": 22, "fireplace": 30}
VENTED_GAS = {"furnace", "boiler", "water_heater", "dryer", "fireplace"}
# IRC R303.3: a bathroom needs 3 sq ft of glazing, half of it openable, or a 50 cfm exhaust fan.
BATH_OPENABLE_M2 = 1.5 * FOOT ** 2
OPENABLE_SHARE = {"double_hung": 0.45, "casement": 0.9, "awning": 0.9, "slider": 0.45, "fixed": 0.0}
# House rules, not code: say so in the report.
POINTS_PER_GENERAL_CIRCUIT = 10
RADIANT_LOOP_SPACING_M = 0.229
RADIANT_LOOP_LIMIT_M = 91.0
SUPPLY_AREA_PER_REGISTER_M2 = 14.0
CROSSING_CLEARANCE_M = 0.03
TRADE_LIFT_M = 0.08
SAMPLE_STEP_M = 0.1


def scaled(point, scale):
    return [point[0] * scale, point[1] * scale]


def manhattan(point_a, point_b):
    return abs(point_a[0] - point_b[0]) + abs(point_a[1] - point_b[1])


def polygon_area(polygon):
    total = 0.0
    for index, (x_a, y_a) in enumerate(polygon):
        x_b, y_b = polygon[(index + 1) % len(polygon)]
        total += x_a * y_b - x_b * y_a
    return abs(total) / 2


def centroid(polygon):
    return [sum(point[0] for point in polygon) / len(polygon), sum(point[1] for point in polygon) / len(polygon)]


def inside(point, polygon):
    result = False
    for index, (x_a, y_a) in enumerate(polygon):
        x_b, y_b = polygon[(index + 1) % len(polygon)]
        if (y_a > point[1]) != (y_b > point[1]) and point[0] < (x_b - x_a) * (point[1] - y_a) / (y_b - y_a) + x_a:
            result = not result
    return result


def closest_on_segment(point, start, end):
    delta_x, delta_y = end[0] - start[0], end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y or 1e-12
    fraction = max(0.0, min(1.0, ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y) / length_squared))
    return [start[0] + fraction * delta_x, start[1] + fraction * delta_y], fraction


def l_route(start, end, z_start, z_end, travel_z, first_axis):
    """An orthogonal run: up or down to the travel plane, along one axis, then the other, then to the end height."""
    corner = [end[0], start[1]] if first_axis == "x" else [start[0], end[1]]
    return [[start[0], start[1], z_start], [start[0], start[1], travel_z], [corner[0], corner[1], travel_z],
            [end[0], end[1], travel_z], [end[0], end[1], z_end]]


def run_length(points):
    return sum(math.dist(points[index], points[index + 1]) for index in range(len(points) - 1))


class House:
    def __init__(self, plan):
        self.plan = plan
        self.scale = METRES_PER_UNIT[plan.get("units", "m")]
        levels = plan.get("levels", {})
        self.ceiling = levels.get("ceiling", 8) * self.scale
        self.rooms = [{**room, "poly_m": [scaled(point, self.scale) for point in room["poly"]],
                       "ceiling_m": room.get("ceiling", levels.get("ceiling", 8)) * self.scale}
                      for room in plan.get("rooms", [])]
        self.walls = {wall["id"]: {**wall, "a_m": scaled(wall["a"], self.scale), "b_m": scaled(wall["b"], self.scale),
                                   "t_m": wall["t"] * self.scale} for wall in plan["walls"]}
        self.openings = []
        for opening in plan.get("openings", []):
            wall = self.walls[opening["wall"]]
            if "from" in opening:
                span = (opening["from"] * self.scale, opening["to"] * self.scale)
            else:
                half = opening["width"] * self.scale / 2
                span = (opening["at"] * self.scale - half, opening["at"] * self.scale + half)
            length = math.dist(wall["a_m"], wall["b_m"])
            direction = [(wall["b_m"][0] - wall["a_m"][0]) / length, (wall["b_m"][1] - wall["a_m"][1]) / length]
            self.openings.append({**opening, "start_m": [wall["a_m"][0] + direction[0] * span[0], wall["a_m"][1] + direction[1] * span[0]],
                                  "end_m": [wall["a_m"][0] + direction[0] * span[1], wall["a_m"][1] + direction[1] * span[1]],
                                  "sill_m": opening.get("sill", 0) * self.scale, "head_m": opening.get("head", 6.8) * self.scale,
                                  "width_m": span[1] - span[0], "t_m": wall["t_m"]})

    def room_named(self, name):
        return next(room for room in self.rooms if room["name"] == name)

    def room_at(self, point):
        return next((room for room in self.rooms if inside(point, room["poly_m"])), None)

    def openings_on_edge(self, start, end, kinds):
        """Openings that sit in the wall along this room edge, as (from, to) distances along the edge."""
        length = math.dist(start, end)
        spans = []
        for opening in self.openings:
            if opening["kind"] not in kinds:
                continue
            point_a, fraction_a = closest_on_segment(opening["start_m"], start, end)
            point_b, fraction_b = closest_on_segment(opening["end_m"], start, end)
            near = opening["t_m"] / 2 + 0.08
            if math.dist(point_a, opening["start_m"]) <= near and math.dist(point_b, opening["end_m"]) <= near:
                low, high = sorted((fraction_a * length, fraction_b * length))
                if high - low > 0.05:
                    spans.append((low, high, opening))
        return sorted(spans, key=lambda span: span[0])

    def is_exterior_edge(self, start, end):
        middle = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2]
        for wall in self.walls.values():
            if wall.get("kind") != "ext":
                continue
            point, _ = closest_on_segment(middle, wall["a_m"], wall["b_m"])
            if math.dist(point, middle) <= wall["t_m"] / 2 + 0.08:
                return True
        return False


def wall_spaces(house, room):
    """Contiguous runs of a room's wall line, broken by doors and cased openings (NEC 210.52(A)(2))."""
    spaces = []
    polygon = room["poly_m"]
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        length = math.dist(start, end)
        cursor = 0.0
        for low, high, _ in house.openings_on_edge(start, end, {"door", "cased"}):
            if low - cursor > 0:
                spaces.append((start, end, cursor, low))
            cursor = max(cursor, high)
        if length - cursor > 0:
            spaces.append((start, end, cursor, length))
    return spaces


def point_along(start, end, distance):
    length = math.dist(start, end) or 1e-9
    return [start[0] + (end[0] - start[0]) * distance / length, start[1] + (end[1] - start[1]) * distance / length]


def glass_to_floor(house, start, end, distance):
    """True where the wall at this spot is glazing that comes down to within 0.3 m of the floor."""
    for low, high, opening in house.openings_on_edge(start, end, {"window"}):
        if low <= distance <= high and opening["sill_m"] < 0.3:
            return True
    return False


def place_receptacles(house, room, report):
    """Receptacles along every wall space, so no point is more than 6 ft from one. A spot on floor-to-ceiling glass
    is a clash: slide along the wall to solid wall within reach, else a floor receptacle within 18 in of the glass."""
    placed = []
    for start, end, low, high in wall_spaces(house, room):
        if high - low < SMALLEST_WALL_SPACE_M:
            continue
        count = max(1, math.ceil((high - low) / (2 * RECEPTACLE_REACH_M)))
        step = (high - low) / count
        for slot in range(count):
            distance = low + step * (slot + 0.5)
            kind = "receptacle"
            if glass_to_floor(house, start, end, distance):
                report["first_pass_clashes"].append(f"{room['name']}: receptacle on floor-to-ceiling glass")
                candidates = [low + offset * SAMPLE_STEP_M for offset in range(int((high - low) / SAMPLE_STEP_M) + 1)]
                # A slid receptacle must still reach both ends of its slot, or the slide just moves the gap.
                slot_low, slot_high = distance - step / 2, distance + step / 2
                solid = [spot for spot in candidates if max(spot - slot_low, slot_high - spot) <= RECEPTACLE_REACH_M
                         and not glass_to_floor(house, start, end, spot)]
                if solid:
                    distance = min(solid, key=lambda spot: abs(spot - distance))
                    report["reroutes"].append(f"{room['name']}: receptacle slid to solid wall")
                else:
                    kind = "floor_receptacle"
                    report["reroutes"].append(f"{room['name']}: floor receptacle at the glass")
            at = point_along(start, end, distance)
            if kind == "floor_receptacle":
                inward = inward_normal(room["poly_m"], start, end)
                at = [at[0] + inward[0] * FLOOR_RECEPTACLE_WALL_GAP_M * 0.6, at[1] + inward[1] * FLOOR_RECEPTACLE_WALL_GAP_M * 0.6]
            gfci = room.get("kind") in GFCI_RECEPTACLE_ROOMS
            placed.append({"trade": "power", "kind": kind, "room": room["name"], "at": at, "z": 0.0 if kind == "floor_receptacle" else 0.3,
                           "gfci": gfci, "edge": [start, end], "along": distance})
    return placed


def inward_normal(polygon, start, end):
    length = math.dist(start, end) or 1e-9
    normal = [-(end[1] - start[1]) / length, (end[0] - start[0]) / length]
    middle = [(start[0] + end[0]) / 2 + normal[0] * 0.05, (start[1] + end[1]) / 2 + normal[1] * 0.05]
    return normal if inside(middle, polygon) else [-normal[0], -normal[1]]


def check_receptacle_reach(house, room, receptacles):
    """Walk every wall space in 10 cm steps; return the worst distance to a receptacle on the same space."""
    worst = 0.0
    for start, end, low, high in wall_spaces(house, room):
        if high - low < SMALLEST_WALL_SPACE_M:
            continue
        on_space = [item["along"] for item in receptacles if item["edge"] == [start, end] and low - 0.01 <= item["along"] <= high + 0.01]
        for step in range(int((high - low) / SAMPLE_STEP_M) + 1):
            spot = low + step * SAMPLE_STEP_M
            # A floor receptacle within 18 in of the wall counts for that wall (NEC 210.52(A)(3)).
            nearest = min((abs(spot - along) for along in on_space), default=math.inf)
            worst = max(worst, nearest)
    return worst


def counter_receptacles(house, plan, room, report):
    placed = []
    for casework in plan.get("casework", []):
        if casework.get("kind") != "base":
            continue
        start, end = scaled(casework["a"], house.scale), scaled(casework["b"], house.scale)
        if house.room_at(point_along(start, end, math.dist(start, end) / 2)) is not room:
            continue
        length = math.dist(start, end)
        count = max(1, math.ceil(length / (2 * COUNTER_REACH_M)))
        for slot in range(count):
            at = point_along(start, end, length * (slot + 0.5) / count)
            placed.append({"trade": "power", "kind": "counter_receptacle", "room": room["name"], "at": at, "z": 1.07,
                           "gfci": True, "counter_length": length, "count_on_counter": count})
    if not placed and room.get("kind") == "kitchen":
        report["notes"].append(f"{room['name']}: no base casework in the plan, so no counter receptacles were placed")
    return placed


def door_switches(house, room):
    switches = []
    for index, start in enumerate(room["poly_m"]):
        end = room["poly_m"][(index + 1) % len(room["poly_m"])]
        for low, _high, opening in house.openings_on_edge(start, end, {"door", "cased"}):
            inward = inward_normal(room["poly_m"], start, end)
            spot = point_along(start, end, max(0.0, low - 0.15))
            switches.append({"trade": "power", "kind": "switch", "room": room["name"], "at": [spot[0] + inward[0] * 0.02, spot[1] + inward[1] * 0.02],
                             "z": 1.2, "door": opening["id"]})
    return switches


def route_power(house, plan, report):
    service = plan["systems"].get("service", {})
    panel = scaled(service["panel"], house.scale) if "panel" in service else centroid(house.rooms[0]["poly_m"])
    devices = []
    for room in house.rooms:
        if room.get("no_access"):
            continue
        kind = room.get("kind", "")
        receptacles = []
        if kind in RECEPTACLE_ROOMS or kind in GFCI_ROOMS:
            receptacles = place_receptacles(house, room, report) if kind in RECEPTACLE_ROOMS else []
        if kind in GFCI_ROOMS and not receptacles:
            fixture = next((item for item in plan["systems"].get("fixtures", []) if item.get("room") == room["name"] and item["kind"] in ("lavatory", "laundry_tub", "washer")), None)
            at = scaled(fixture["at"], house.scale) if fixture else centroid(room["poly_m"])
            receptacles = [{"trade": "power", "kind": "receptacle", "room": room["name"], "at": at, "z": 1.0, "gfci": True}]
        if kind == "hall" and polygon_area(room["poly_m"]) > 0 and max(math.dist(a, b) for a in room["poly_m"] for b in room["poly_m"]) >= 10 * FOOT:
            receptacles = receptacles or [{"trade": "power", "kind": "receptacle", "room": room["name"], "at": centroid(room["poly_m"]), "z": 0.3, "gfci": False}]
        counters = counter_receptacles(house, plan, room, report) if kind == "kitchen" else []
        devices += receptacles + counters + door_switches(house, room)
        devices.append({"trade": "power", "kind": "light", "room": room["name"], "at": centroid(room["poly_m"]), "z": room["ceiling_m"] - 0.02})
        room["_receptacles"] = receptacles
        room["_counters"] = counters
    devices += place_alarms(house, report)
    circuits = group_circuits(house, plan, devices)
    runs = []
    for circuit in circuits:
        points = circuit["points"]
        travel = house.ceiling + 0.15
        first = min(points, key=lambda device: manhattan(device["at"], panel))
        runs.append({"trade": "power", "kind": "home_run", "circuit": circuit["name"],
                     "points": l_route(panel, first["at"], 1.5, first["z"], travel, "x")})
        ordered = sorted(points, key=lambda device: manhattan(device["at"], first["at"]))
        for previous, device in zip(ordered, ordered[1:]):
            runs.append({"trade": "power", "kind": "branch", "circuit": circuit["name"],
                         "points": l_route(previous["at"], device["at"], previous["z"], device["z"], travel, "y")})
    return devices, circuits, runs, panel


def place_alarms(house, report):
    alarms = []
    gas = any(item.get("fuel") == "gas" for item in house.plan["systems"].get("appliances", []))
    bedrooms = [room for room in house.rooms if room.get("kind") in SLEEPING_ROOMS]
    for room in bedrooms:
        alarms.append({"trade": "power", "kind": "smoke_alarm", "room": room["name"], "at": centroid(room["poly_m"]), "z": room["ceiling_m"] - 0.02})
    outside_spots = []
    for room in bedrooms:
        # The way out of a bedroom: its doors and cased openings, and any room it opens onto with no wall (open_to).
        candidates = []
        for index, start in enumerate(room["poly_m"]):
            end = room["poly_m"][(index + 1) % len(room["poly_m"])]
            for low, high, _opening in house.openings_on_edge(start, end, {"door", "cased"}):
                middle = point_along(start, end, (low + high) / 2)
                inward = inward_normal(room["poly_m"], start, end)
                candidates.append([middle[0] - inward[0] * 0.9, middle[1] - inward[1] * 0.9])
        bedroom_centre = centroid(room["poly_m"])
        for name in room.get("open_to", []):
            other = house.room_named(name)
            edges = [(point, other["poly_m"][(index + 1) % len(other["poly_m"])]) for index, point in enumerate(other["poly_m"])]
            nearest = min((closest_on_segment(bedroom_centre, *edge)[0] for edge in edges), key=lambda point: math.dist(point, bedroom_centre))
            toward = centroid(other["poly_m"])
            length = math.dist(nearest, toward) or 1
            candidates.append([nearest[0] + (toward[0] - nearest[0]) / length * 0.6, nearest[1] + (toward[1] - nearest[1]) / length * 0.6])
        for outside in candidates:
            other = house.room_at(outside)
            if other is None or other.get("kind") in SLEEPING_ROOMS or other.get("no_access"):
                continue
            if all(math.dist(outside, spot) > 3.0 for spot in outside_spots):
                outside_spots.append(outside)
                alarms.append({"trade": "power", "kind": "smoke_co_alarm" if gas else "smoke_alarm", "room": other["name"],
                               "at": outside, "z": other["ceiling_m"] - 0.02})
    if not alarms and house.rooms:
        report["notes"].append("no bedroom in the plan: one smoke alarm placed in the largest room for the storey")
        largest = max(house.rooms, key=lambda room: polygon_area(room["poly_m"]))
        alarms.append({"trade": "power", "kind": "smoke_alarm", "room": largest["name"], "at": centroid(largest["poly_m"]), "z": largest["ceiling_m"] - 0.02})
    return alarms


def group_circuits(house, plan, devices):
    circuits = []
    counters = [device for device in devices if device["kind"] == "counter_receptacle"]
    if counters:
        half = max(1, len(counters) // 2)
        circuits.append({"name": "kitchen small appliance 1", "amps": 20, "points": counters[:half]})
        circuits.append({"name": "kitchen small appliance 2", "amps": 20, "points": counters[half:] or counters[:1]})
    for kind in ("bath", "laundry"):
        points = [device for device in devices if device["kind"] in ("receptacle",) and house.room_named(device["room"]).get("kind") == kind]
        if points:
            circuits.append({"name": f"{kind} receptacles", "amps": 20, "points": points})
    for appliance in plan["systems"].get("appliances", []) + [item for item in plan["systems"].get("fixtures", []) if item["kind"] in ("dishwasher",)]:
        if appliance.get("fuel") == "gas" and appliance["kind"] not in ("furnace", "range", "dryer"):
            continue
        amps = {"range": 50, "dryer": 30, "water_heater": 30}.get(appliance["kind"], 20) if appliance.get("fuel") != "gas" else 15
        # Beside the appliance rather than behind its centre, where a hood duct or flue rises.
        at = scaled(appliance["at"], house.scale)
        point = {"trade": "power", "kind": "appliance_outlet", "room": appliance.get("room", ""), "at": [at[0] + 0.35, at[1]], "z": 0.6}
        devices.append(point)
        circuits.append({"name": f"{appliance['kind']} {appliance.get('id', '')}".strip(), "amps": amps, "points": [point]})
    assigned = {id(point) for circuit in circuits for point in circuit["points"]}
    general = [device for device in devices if id(device) not in assigned]
    general.sort(key=lambda device: (device["room"], device["at"][0], device["at"][1]))
    for index in range(0, len(general), POINTS_PER_GENERAL_CIRCUIT):
        circuits.append({"name": f"general {index // POINTS_PER_GENERAL_CIRCUIT + 1}", "amps": 15,
                         "points": general[index:index + POINTS_PER_GENERAL_CIRCUIT]})
    return circuits


def nearest_wall_point(house, point, interior_only=False):
    best = None
    for wall in house.walls.values():
        if interior_only and wall.get("kind") == "ext":
            continue
        spot, _ = closest_on_segment(point, wall["a_m"], wall["b_m"])
        if best is None or math.dist(spot, point) < math.dist(best, point):
            best = spot
    return best


def route_plumbing(house, plan, report):
    systems = plan["systems"]
    service = systems.get("service", {})
    fixtures = [{**item, "at_m": scaled(item["at"], house.scale)} for item in systems.get("fixtures", [])]
    heater = next((item for item in systems.get("appliances", []) if item["kind"] == "water_heater"), None)
    manifold = scaled(service.get("manifold", heater["at"] if heater else fixtures[0]["at"]), house.scale) if fixtures else None
    stacks = [scaled(stack["at"], house.scale) for stack in systems.get("stacks", [])]
    drained = [item for item in fixtures if FIXTURES[item["kind"]]["trap"]]
    if drained and not stacks:
        wet = centroid([item["at_m"] for item in drained])
        stacks = [nearest_wall_point(house, wet, interior_only=True) or wet]
        report["notes"].append("no stack in the plan: one vent stack placed in the interior wall nearest the wet rooms")
    runs, elements, checks = [], [], []
    slab_z = -0.15
    for stack in stacks:
        elements.append({"trade": "drain", "kind": "stack", "at": stack, "z": 0.0, "top": house.ceiling + 1.0})
    for item in drained:
        spec = FIXTURES[item["kind"]]
        stack = min(stacks, key=lambda candidate: manhattan(candidate, item["at_m"]))
        arm = manhattan(stack, item["at_m"])
        limit = TRAP_ARM_LIMIT_M[spec["trap"]]
        vent_at = stack
        if arm > limit:
            report["first_pass_clashes"].append(f"{item['id']} {item['kind']}: trap arm {arm:.2f} m over {limit:.2f} m")
            wall_spot = nearest_wall_point(house, item["at_m"])
            if wall_spot and manhattan(wall_spot, item["at_m"]) <= limit:
                vent_at = wall_spot
                elements.append({"trade": "vent", "kind": "individual_vent", "at": wall_spot, "z": 0.0, "top": house.ceiling + 0.3, "fixture": item["id"]})
                report["reroutes"].append(f"{item['id']}: individual vent in the nearest wall")
                arm = manhattan(wall_spot, item["at_m"])
            checks.append({"rule": "trap arm", "code": "IRC P3105.1", "item": item["id"], "value_m": round(arm, 2),
                           "limit_m": round(limit, 2), "status": "pass" if arm <= limit else "fail"})
        else:
            checks.append({"rule": "trap arm", "code": "IRC P3105.1", "item": item["id"], "value_m": round(arm, 2),
                           "limit_m": round(limit, 2), "status": "pass"})
        slope = DRAIN_SLOPE_LARGE if spec["trap"] >= 3 else DRAIN_SLOPE_SMALL
        fall = manhattan(stack, item["at_m"]) * slope
        runs.append({"trade": "drain", "kind": f"{spec['trap']} in drain", "fixture": item["id"], "fall_m": round(fall, 3),
                     "points": l_route(item["at_m"], stack, 0.0, slab_z - fall, slab_z, "x")})
        if vent_at is not stack:
            runs.append({"trade": "vent", "kind": "vent", "fixture": item["id"],
                         "points": l_route(vent_at, stack, house.ceiling, house.ceiling + 0.3, house.ceiling + 0.3, "y")})
    sewer = scaled(service["sewer"], house.scale) if "sewer" in service else None
    for stack in stacks:
        target = sewer or nearest_exterior_point(house, stack)
        fall = manhattan(stack, target) * DRAIN_SLOPE_LARGE
        runs.append({"trade": "drain", "kind": "building drain", "fall_m": round(fall, 3),
                     "points": l_route(stack, target, slab_z, slab_z - fall, slab_z - 0.05, "y")})
    depth = systems.get("drain_depth_m", 0.6)
    deepest = max((run.get("fall_m", 0) for run in runs if run["trade"] == "drain"), default=0)
    checks.append({"rule": "drain fall fits under the floor", "code": "IRC P3005.3", "value_m": round(deepest, 3),
                   "limit_m": depth, "status": "pass" if deepest <= depth else "fail"})
    supply_runs = []
    if manifold:
        elements.append({"trade": "water", "kind": "manifold", "at": manifold, "z": 1.2})
        for item in fixtures:
            spec = FIXTURES[item["kind"]]
            for temperature in ("cold", "hot"):
                if not spec[temperature]:
                    continue
                points = l_route(manifold, item["at_m"], 1.2, 0.5, slab_z + 0.05, "y" if temperature == "hot" else "x")
                run = {"trade": "water", "kind": f"{temperature} PEX home run", "fixture": item["id"], "size": "1/2", "points": points}
                if temperature == "hot":
                    volume = run_length(points) * PEX_LITRES_PER_METRE["1/2"]
                    if volume > HOT_WATER_LIMIT_L and item["kind"] in SMALL_PEX_FIXTURES:
                        report["first_pass_clashes"].append(f"{item['id']}: {volume:.2f} L of standing hot water in 1/2 in PEX")
                        run["size"] = "3/8"
                        volume = run_length(points) * PEX_LITRES_PER_METRE["3/8"]
                        report["reroutes"].append(f"{item['id']}: hot run down to 3/8 in PEX")
                    checks.append({"rule": "hot water wait", "code": "WaterSense 0.5 gal", "item": item["id"], "value_l": round(volume, 2),
                                   "limit_l": HOT_WATER_LIMIT_L, "status": "pass" if volume <= HOT_WATER_LIMIT_L else "fail"})
                supply_runs.append(run)
    return elements, runs + supply_runs, checks, fixtures


def nearest_exterior_point(house, point):
    best = None
    for wall in house.walls.values():
        if wall.get("kind") != "ext":
            continue
        spot, _ = closest_on_segment(point, wall["a_m"], wall["b_m"])
        if best is None or math.dist(spot, point) < math.dist(best, point):
            best = spot
    return best or point


def route_gas(house, plan, report):
    systems = plan["systems"]
    appliances = [item for item in systems.get("appliances", []) if item.get("fuel") == "gas"]
    if not appliances:
        return [], [], []
    meter = scaled(systems.get("service", {}).get("gas_in", appliances[0]["at"]), house.scale)
    elements = [{"trade": "gas", "kind": "meter", "at": meter, "z": 0.6}]
    runs, checks = [], []
    by_room = {}
    for item in appliances:
        at = scaled(item["at"], house.scale)
        room = house.room_at(at)
        inward = [0.0, 0.0]
        shutoff = [at[0] + 0.3, at[1]]
        if room and not inside(shutoff, room["poly_m"]):
            shutoff = [at[0] - 0.3, at[1]]
        same_room = room is not None and inside(shutoff, room["poly_m"])
        reach = math.dist(shutoff, at)
        elements.append({"trade": "gas", "kind": "shutoff", "at": shutoff, "z": 0.5, "appliance": item.get("id", item["kind"])})
        if item["kind"] in VENTED_GAS:
            elements.append({"trade": "gas", "kind": "sediment_trap", "at": shutoff, "z": 0.3})
        checks.append({"rule": "gas shutoff", "code": "IFGC 409.5.1", "item": item.get("id", item["kind"]), "value_m": round(reach, 2),
                       "limit_m": round(GAS_SHUTOFF_REACH_M, 2), "status": "pass" if same_room and reach <= GAS_SHUTOFF_REACH_M else "fail"})
        runs.append({"trade": "gas", "kind": "black iron", "appliance": item.get("id", item["kind"]),
                     "points": l_route(meter, shutoff, 0.6, 0.5, house.ceiling + 0.3, "x")})
        if room and item["kind"] in VENTED_GAS:
            by_room.setdefault(room["name"], []).append(item)
        del inward
    for name, items in by_room.items():
        room = house.room_named(name)
        volume = polygon_area(room["poly_m"]) * room["ceiling_m"]
        needed = sum(GAS_INPUT_KBTU.get(item["kind"], 40) for item in items) * ROOM_AIR_M3_PER_KBTU
        outdoor = name in plan["systems"].get("combustion_air_from_outdoors", [])
        if volume < needed and not outdoor:
            report["first_pass_clashes"].append(f"{name}: {volume:.1f} m3 of room air for {needed:.1f} m3 of appliance input")
            outer = [(point, room["poly_m"][(index + 1) % len(room["poly_m"])]) for index, point in enumerate(room["poly_m"])]
            outer = [edge for edge in outer if house.is_exterior_edge(*edge)]
            if outer:
                # IFGC 304.6.1: two openings to outdoors, one within 12 in of the top and one within 12 in of the floor.
                middle = point_along(outer[0][0], outer[0][1], math.dist(*outer[0]) / 2)
                for height in (0.2, room["ceiling_m"] - 0.2):
                    elements.append({"trade": "air", "kind": "combustion_air_opening", "room": name, "at": middle, "z": height})
                report["reroutes"].append(f"{name}: two combustion air openings to outdoors in its outer wall")
                outdoor = True
        status = "pass" if volume >= needed or outdoor else "fail"
        checks.append({"rule": "combustion air", "code": "IFGC 304.5.1", "item": name, "value_m3": round(volume, 1),
                       "limit_m3": round(needed, 1), "status": status})
    return elements, runs, checks


def route_air(house, plan, report):
    systems = plan["systems"]
    elements, runs, checks = [], [], []
    habitable = [room for room in house.rooms if room.get("kind") in RECEPTACLE_ROOMS | {"bath"}]
    heating = systems.get("heating", "ducted")
    source_item = next((item for item in systems.get("appliances", []) if item["kind"] in ("furnace", "boiler", "air_handler")), None)
    source = scaled(source_item["at"], house.scale) if source_item else centroid(house.rooms[0]["poly_m"])
    for room in habitable:
        area = polygon_area(room["poly_m"])
        if heating == "radiant":
            loop = area / RADIANT_LOOP_SPACING_M + 2 * manhattan(source, centroid(room["poly_m"]))
            loops = max(1, math.ceil(loop / RADIANT_LOOP_LIMIT_M))
            elements.append({"trade": "heat", "kind": "radiant_loop", "room": room["name"], "at": centroid(room["poly_m"]), "z": -0.05,
                             "length_m": round(loop, 1), "loops": loops})
            runs.append({"trade": "heat", "kind": "radiant leader", "room": room["name"],
                         "points": l_route(source, centroid(room["poly_m"]), 0.3, -0.05, -0.05, "x")})
            checks.append({"rule": "radiant loop length", "code": "maker limit 300 ft", "item": room["name"],
                           "value_m": round(loop / loops, 1), "limit_m": RADIANT_LOOP_LIMIT_M, "status": "pass"})
        else:
            registers = max(1, math.ceil(area / SUPPLY_AREA_PER_REGISTER_M2))
            edges = [(start, room["poly_m"][(index + 1) % len(room["poly_m"])]) for index, start in enumerate(room["poly_m"])]
            outer = [edge for edge in edges if house.is_exterior_edge(*edge)] or edges
            longest = max(outer, key=lambda edge: math.dist(*edge))
            inward = inward_normal(room["poly_m"], *longest)
            for slot in range(registers):
                spot = point_along(longest[0], longest[1], math.dist(*longest) * (slot + 0.5) / registers)
                at = [spot[0] + inward[0] * 0.3, spot[1] + inward[1] * 0.3]
                elements.append({"trade": "air", "kind": "supply_register", "room": room["name"], "at": at, "z": room["ceiling_m"] - 0.01})
                runs.append({"trade": "air", "kind": "supply duct", "room": room["name"],
                             "points": l_route(source, at, 1.8, room["ceiling_m"], house.ceiling + 0.35, "x")})
    if heating != "radiant" and habitable:
        hall = next((room for room in house.rooms if room.get("kind") == "hall"), max(house.rooms, key=lambda room: polygon_area(room["poly_m"])))
        elements.append({"trade": "air", "kind": "return_grille", "room": hall["name"], "at": centroid(hall["poly_m"]), "z": hall["ceiling_m"] - 0.01})
    for room in house.rooms:
        bathing = [item for item in systems.get("fixtures", []) if item.get("room") == room["name"] and item["kind"] in BATHING_FIXTURES]
        if not bathing:
            continue
        openable = 0.0
        for index, start in enumerate(room["poly_m"]):
            end = room["poly_m"][(index + 1) % len(room["poly_m"])]
            for low, high, opening in house.openings_on_edge(start, end, {"window"}):
                openable += (high - low) * (opening["head_m"] - opening["sill_m"]) * OPENABLE_SHARE.get(opening.get("sash", "fixed"), 0.0)
        fan = openable < BATH_OPENABLE_M2
        if fan:
            # Off the room centre, where the ceiling light sits, so the fan's duct and the light's feed do not meet.
            centre = centroid(room["poly_m"])
            at = [centre[0] + 0.6, centre[1]] if inside([centre[0] + 0.6, centre[1]], room["poly_m"]) else [centre[0] - 0.6, centre[1]]
            outlet = nearest_exterior_point(house, at)
            elements.append({"trade": "air", "kind": "exhaust_fan_50cfm", "room": room["name"], "at": at, "z": room["ceiling_m"] - 0.01})
            runs.append({"trade": "air", "kind": "exhaust duct", "room": room["name"],
                         "points": l_route(at, outlet, room["ceiling_m"], room["ceiling_m"] + 0.2, room["ceiling_m"] + 0.2, "x")})
        checks.append({"rule": "bathroom ventilation", "code": "IRC R303.3", "item": room["name"],
                       "value": "50 cfm fan" if fan else f"{openable:.2f} m2 openable", "status": "pass"})
    for item in systems.get("appliances", []):
        if item["kind"] != "range":
            continue
        at = scaled(item["at"], house.scale)
        room = house.room_at(at)
        outlet = nearest_exterior_point(house, at)
        elements.append({"trade": "air", "kind": "range_hood_100cfm", "room": room["name"] if room else "", "at": at, "z": 1.7})
        runs.append({"trade": "air", "kind": "hood duct", "points": l_route(at, outlet, 1.7, house.ceiling + 0.2, house.ceiling + 0.2, "y")})
        checks.append({"rule": "kitchen exhaust", "code": "IRC M1505.4.4", "item": item.get("id", "range"), "value": "100 cfm hood", "status": "pass"})
    return elements, runs, checks


def segments_cross(first, second):
    """Closest distance between two straight 3D segments, by sampling: plenty for layout clearances."""
    best = math.inf
    for step in range(11):
        fraction = step / 10
        point = [first[0][axis] + (first[1][axis] - first[0][axis]) * fraction for axis in range(3)]
        delta = [second[1][axis] - second[0][axis] for axis in range(3)]
        length_squared = sum(value * value for value in delta) or 1e-12
        along = max(0.0, min(1.0, sum((point[axis] - second[0][axis]) * delta[axis] for axis in range(3)) / length_squared))
        closest = [second[0][axis] + delta[axis] * along for axis in range(3)]
        best = min(best, math.dist(point, closest))
    return best


def runs_clash(first, second):
    return any(segments_cross((first["points"][index], first["points"][index + 1]), (second["points"][other], second["points"][other + 1])) < CROSSING_CLEARANCE_M
               for index in range(len(first["points"]) - 1) for other in range(len(second["points"]) - 1))


def swap_corner(run):
    """Turn an L run the other way round: along y then x instead of x then y."""
    start, corner, end = run["points"][1], run["points"][2], run["points"][3]
    corner[0], corner[1] = (start[0], end[1]) if math.isclose(corner[0], end[0]) and not math.isclose(start[0], end[0]) else (end[0], start[1])


def move_until_clear(later, earlier, moves, direction, others=()):
    """Lift or turn the later run until it clears this run and every other earlier run of another trade."""
    for move in moves:
        if move == "swap" and len(later["points"]) == 5:
            swap_corner(later)
        else:
            for point in later["points"][1:-1]:
                point[2] += TRADE_LIFT_M * direction
        if not runs_clash(later, earlier) and not any(runs_clash(later, other) for other in others):
            return True
    return False


def resolve_crossings(runs, report):
    """Runs of different trades closer than the clearance clash. Lift the later trade's travel leg; where a lift
    cannot clear (the other run is vertical there), turn the L the other way, then lift again."""
    order = {"drain": 0, "air": 1, "gas": 2, "water": 3, "heat": 4, "vent": 5, "power": 6}
    moves = ["lift", "lift", "swap", "lift", "lift", "swap"]
    clashes = 0
    for later_index, later in enumerate(runs):
        others = [earlier for earlier in runs[:later_index] if earlier["trade"] != later["trade"]]
        attempts = {}
        # Clearing one run can push this one back onto a run it already cleared, so keep going until none clash,
        # at most three tries against each run.
        while True:
            earlier = next((other for other in others if attempts.get(id(other), 0) < 3 and runs_clash(later, other)), None)
            if earlier is None:
                break
            if id(earlier) not in attempts:
                clashes += 1
            attempts[id(earlier)] = attempts.get(id(earlier), 0) + 1
            original = [list(point) for point in later["points"]]
            preferred = 1 if order[later["trade"]] > order[earlier["trade"]] else -1
            # Lifting toward the other run's plane can never clear it (a branch rising into vents above the
            # ceiling), so try the other direction from the original route before giving up.
            if not move_until_clear(later, earlier, moves, preferred, others):
                later["points"] = [list(point) for point in original]
                if not move_until_clear(later, earlier, moves, -preferred, others):
                    later["points"] = original
    report["first_pass_crossings"] = clashes
    # Moving one run can make it clash with a run it already cleared, so check every pair once more at the end.
    for later_index, later in enumerate(runs):
        for earlier in runs[:later_index]:
            if earlier["trade"] != later["trade"] and runs_clash(later, earlier):
                message = f"{later['trade']} {later.get('kind')} still crosses {earlier['trade']} {earlier.get('kind')}"
                if message not in report["unresolved"]:
                    report["unresolved"].append(message)
    if clashes:
        report["reroutes"].append(f"{clashes} crossings between trades lifted {TRADE_LIFT_M * 100:.0f} cm in their travel plane")


def electrical_checks(house, plan, devices):
    checks = []
    for room in house.rooms:
        kind = room.get("kind", "")
        if kind in RECEPTACLE_ROOMS:
            worst = check_receptacle_reach(house, room, room.get("_receptacles", []))
            checks.append({"rule": "receptacle spacing", "code": "NEC 210.52(A)", "item": room["name"], "value_m": round(worst, 2),
                           "limit_m": round(RECEPTACLE_REACH_M, 2), "status": "pass" if worst <= RECEPTACLE_REACH_M + 1e-6 else "fail"})
        for counter in room.get("_counters", [])[:1]:
            reach = counter["counter_length"] / counter["count_on_counter"] / 2
            checks.append({"rule": "counter receptacle spacing", "code": "NEC 210.52(C)", "item": room["name"], "value_m": round(reach, 2),
                           "limit_m": round(COUNTER_REACH_M, 2), "status": "pass" if reach <= COUNTER_REACH_M + 1e-6 else "fail"})
        if kind in GFCI_ROOMS or room.get("_counters"):
            unprotected = [device for device in devices if device["room"] == room["name"] and "receptacle" in device["kind"] and not device.get("gfci")]
            checks.append({"rule": "GFCI protection", "code": "NEC 210.8(A)", "item": room["name"], "value": f"{len(unprotected)} unprotected",
                           "status": "pass" if not unprotected else "fail"})
    for room in house.rooms:
        if room.get("kind") in SLEEPING_ROOMS:
            has = any(device["room"] == room["name"] and "smoke" in device["kind"] for device in devices)
            checks.append({"rule": "smoke alarm in bedroom", "code": "IRC R314.3", "item": room["name"], "status": "pass" if has else "fail"})
    gas = any(item.get("fuel") == "gas" for item in plan["systems"].get("appliances", []))
    if gas and any(room.get("kind") in SLEEPING_ROOMS for room in house.rooms):
        has = any(device["kind"] == "smoke_co_alarm" for device in devices)
        checks.append({"rule": "CO alarm outside sleeping areas", "code": "IRC R315.3", "item": "house", "status": "pass" if has else "fail"})
    return checks


def summary_markdown(report):
    marks = {"pass": "✓", "fail": "✕"}
    counts = report["counts"]
    lines = [f"# {report['title']}", "",
             f"- {counts['circuits']} circuits, {counts['devices']} devices",
             f"- {counts['water_runs']} PEX home runs, {counts['water_length_m']:.0f} m ({counts['water_length_m'] / FOOT:.0f} ft)",
             f"- {counts['drained_fixtures']} fixtures drained and vented through {counts['stacks']} stack(s)",
             f"- {counts['air_items']} air items ({report['heating']})",
             f"- {counts['gas_appliances']} gas appliances",
             f"- {counts['parts']} parts in total",
             f"- First pass: {len(report['first_pass_clashes'])} rule clashes and {report['first_pass_crossings']} trade crossings; "
             f"{len(report['reroutes'])} reroutes; {len(report['unresolved'])} unresolved", "",
             "| Rule | Code | Item | Value | Limit | Result |", "| --- | --- | --- | --- | --- | --- |"]
    for check in report["checks"]:
        value = next((check[key] for key in ("value_m", "value_l", "value_m3", "value") if key in check), "")
        limit = next((check[key] for key in ("limit_m", "limit_l", "limit_m3") if key in check), "")
        lines.append(f"| {check['rule']} | {check['code']} | {check.get('item', '')} | {value} | {limit} | {marks[check['status']]} {check['status']} |")
    lines += ["", "Layout and code checks only. No load calculations, no duct or pipe sizing beyond the tables used,",
              "and the generated layout is a first draft for a licensed designer, not a permit set.",
              "House rules that are not code: 10 points per 15 A general circuit, 14 m2 per supply register, 300 ft per radiant loop."]
    if report["notes"]:
        lines += ["", "Notes:"] + [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def run(plan):
    house = House(plan)
    report = {"title": plan.get("name", "House") + " services", "first_pass_clashes": [], "reroutes": [], "unresolved": [], "notes": [],
              "heating": plan["systems"].get("heating", "ducted"), "first_pass_crossings": 0}
    devices, circuits, power_runs, panel = route_power(house, plan, report)
    plumbing_elements, plumbing_runs, plumbing_checks, fixtures = route_plumbing(house, plan, report)
    gas_elements, gas_runs, gas_checks = route_gas(house, plan, report)
    air_elements, air_runs, air_checks = route_air(house, plan, report)
    runs = plumbing_runs + air_runs + gas_runs + power_runs
    resolve_crossings(runs, report)
    checks = electrical_checks(house, plan, devices) + plumbing_checks + gas_checks + air_checks
    water_runs = [run for run in runs if run["trade"] == "water"]
    elements = devices + plumbing_elements + gas_elements + air_elements + [{"trade": "power", "kind": "panel", "at": panel, "z": 1.5}]
    report.update({
        "checks": checks,
        "elements": [{key: value for key, value in element.items() if key not in ("edge",)} for element in elements],
        "runs": runs,
        "circuits": [{"name": circuit["name"], "amps": circuit["amps"], "points": len(circuit["points"])} for circuit in circuits],
        "counts": {
            "circuits": len(circuits),
            "devices": len(devices),
            "water_runs": len(water_runs),
            "water_length_m": sum(run_length(run["points"]) for run in water_runs),
            "drained_fixtures": len([item for item in fixtures if FIXTURES[item["kind"]]["trap"]]),
            "stacks": len([element for element in plumbing_elements if element["kind"] == "stack"]),
            "air_items": len(air_elements),
            "gas_appliances": len([element for element in gas_elements if element["kind"] == "shutoff"]),
            "parts": len(elements) + sum(len(run["points"]) - 1 for run in runs),
        },
        "passed": all(check["status"] == "pass" for check in checks) and not report["unresolved"],
    })
    return report


def main():
    plan_path = pathlib.Path(sys.argv[1])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if "systems" not in plan:
        print("plan has no systems section: see references/systems.md")
        sys.exit(1)
    report = run(plan)
    folder = plan_path.resolve().parent
    (folder / "systems_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (folder / "systems.md").write_text(summary_markdown(report), encoding="utf-8")
    failed = [check for check in report["checks"] if check["status"] == "fail"]
    print(summary_markdown(report).split("| Rule")[0].strip())
    print(f"SYSTEMS {'pass' if report['passed'] else 'FAIL'}: {len(report['checks']) - len(failed)}/{len(report['checks'])} rules, "
          f"{len(report['unresolved'])} unresolved")
    for check in failed:
        print(f"    ✕ {check['rule']} ({check['code']}) {check.get('item', '')}")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
