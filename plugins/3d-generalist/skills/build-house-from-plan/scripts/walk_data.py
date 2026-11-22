"""Write the data a live walk page needs from plan.json: collision walls with door gaps, rooms, lamps, the sheet
calibration for a minimap, and start poses. Lengths come out in metres in the glTF frame (y up): a plan point
(x, y) at height z becomes (x, z, -y), the same frame scripts/export_web.py writes the house in.

Usage: uv run --no-project --with numpy python walk_data.py plan.json out/web/walk.json [house_build_report.json]
The build report (written by build_house.py next to the blend) adds each placed model's footprint as a collision
segment, so the walker cannot pass through sofas, tables and beds.
"""
import json
import math
import pathlib
import sys

import numpy

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

METRES_PER_UNIT = {"m": 1.0, "ft": 0.3048}
PASSABLE_OPENINGS = {"door", "cased"}
SMALLEST_WALL_PIECE_METRES = 0.02


def to_world(point, scale):
    """Plan (x, y) in plan units to world (x, z) in metres."""
    return [round(point[0] * scale, 4), round(-point[1] * scale, 4)]


def opening_span(opening):
    if "from" in opening:
        return opening["from"], opening["to"]
    half_width = opening["width"] / 2
    return opening["at"] - half_width, opening["at"] + half_width


def wall_pieces(wall, openings):
    """Split a wall's centreline at every door or cased opening, so the walker can pass through it."""
    start, end = wall["a"], wall["b"]
    length = math.dist(start, end)
    gaps = sorted(opening_span(opening) for opening in openings
                  if opening["wall"] == wall["id"] and opening["kind"] in PASSABLE_OPENINGS)
    pieces = []
    cursor = 0.0
    for gap_start, gap_end in gaps:
        if gap_start > cursor:
            pieces.append((cursor, gap_start))
        cursor = max(cursor, gap_end)
    if cursor < length:
        pieces.append((cursor, length))
    direction = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
    for piece_start, piece_end in pieces:
        yield ([start[0] + direction[0] * piece_start, start[1] + direction[1] * piece_start],
               [start[0] + direction[0] * piece_end, start[1] + direction[1] * piece_end])


def sheet_affine(plan, scale):
    """Least-squares affine from world metres (x, z) to source sheet pixels, for drawing the sheet on a minimap."""
    pairs = plan.get("calibration", {}).get("pairs", [])
    if len(pairs) < 3:
        return None
    world_rows = [[pair["plan"][0] * scale, -pair["plan"][1] * scale, 1.0] for pair in pairs]
    pixel_rows = [pair["px"] for pair in pairs]
    solution, *_ = numpy.linalg.lstsq(numpy.array(world_rows), numpy.array(pixel_rows, dtype=float), rcond=None)
    # pixel = [x, z, 1] @ solution, stored as the 2x3 matrix [[a, b, c], [d, e, f]]: px = a*x + b*z + c.
    return [[round(float(value), 6) for value in solution[:, column]] for column in range(2)]


def furniture_segments(report_path):
    """Each placed model's footprint (metres, plan axes) as a segment along its long side with half its short side as
    thickness, the same shape as a wall. Rugs and flat items below ankle height are left walkable."""
    segments = []
    for item in json.loads(report_path.read_text(encoding="utf-8")).get("placed", []):
        size_x, size_y, height = item["size_m"]
        if height < 0.12:
            continue
        centre_x, centre_y = item["at"]
        if size_x >= size_y:
            start, end, half = [centre_x - (size_x - size_y) / 2, centre_y], [centre_x + (size_x - size_y) / 2, centre_y], size_y / 2
        else:
            start, end, half = [centre_x, centre_y - (size_y - size_x) / 2], [centre_x, centre_y + (size_y - size_x) / 2], size_x / 2
        segments.append({"id": item["asset"], "a": to_world(start, 1.0), "b": to_world(end, 1.0), "half": round(half, 3),
                         "bottom": round(item["z"], 3), "top": round(item["z"] + height, 3), "kind": "furniture"})
    return segments


def main():
    plan_path = pathlib.Path(sys.argv[1])
    out_path = pathlib.Path(sys.argv[2])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scale = METRES_PER_UNIT[plan.get("units", "m")]
    levels = plan.get("levels", {})
    ceiling = levels.get("ceiling", 2.4 / scale) * scale
    openings = plan.get("openings", [])

    walls = []
    for wall in plan["walls"]:
        bottom = wall.get("z0", 0) * scale
        top = wall.get("h", levels.get("ceiling", 2.4 / scale)) * scale + bottom
        for piece_start, piece_end in wall_pieces(wall, openings):
            if math.dist(piece_start, piece_end) * scale < SMALLEST_WALL_PIECE_METRES:
                continue
            walls.append({"id": wall["id"], "a": to_world(piece_start, scale), "b": to_world(piece_end, scale),
                          "half": round(wall["t"] * scale / 2, 4), "bottom": round(bottom, 3), "top": round(top, 3),
                          "kind": wall.get("kind", "int")})

    rooms = [{"name": room["name"], "kind": room.get("kind", ""), "floor": round(room.get("floor_z", 0) * scale, 3),
              "poly": [to_world(point, scale) for point in room["poly"]]} for room in plan.get("rooms", [])]

    boxes = []
    for casework in plan.get("casework", []):
        if casework.get("kind") != "base":
            continue
        boxes.append({"a": to_world(casework["a"], scale), "b": to_world(casework["b"], scale),
                      "depth": round(casework.get("depth", 2) * scale, 3), "side": casework.get("side", 1),
                      "bottom": round(casework.get("z0", 0) * scale, 3), "top": round(casework.get("z1", 3) * scale, 3)})

    furniture = furniture_segments(pathlib.Path(sys.argv[3])) if len(sys.argv) > 3 else []

    lamps = [{"position": [round(lamp["at"][0] * scale, 3), round(lamp.get("z", ceiling / scale) * scale, 3),
                           round(-lamp["at"][1] * scale, 3)],
              "watts": lamp.get("watts", 60), "colour": lamp.get("colour")} for lamp in plan.get("lamps", [])]

    shots = [{"name": shot["name"], "kind": shot.get("kind", "exterior"),
              "eye": [round(shot["pos"][0] * scale, 3), round(shot["pos"][2] * scale, 3), round(-shot["pos"][1] * scale, 3)],
              "look": [round(shot["look"][0] * scale, 3), round(shot["look"][2] * scale, 3), round(-shot["look"][1] * scale, 3)]}
             for shot in plan.get("shots", []) if len(shot.get("pos", [])) == 3]

    # Stairs as ramps the walker follows: start is a corner, the flight runs along heading, the width to its left.
    stairs = []
    for stair in plan.get("stairs", []):
        heading = math.radians(stair["heading"])
        forward = (math.cos(heading), math.sin(heading))
        across = (-forward[1], forward[0])
        stairs.append({"start": to_world(stair["start"], scale), "forward": [round(forward[0], 5), round(-forward[1], 5)],
                       "across": [round(across[0], 5), round(-across[1], 5)], "length": round(stair["run"] * stair["steps"] * scale, 3),
                       "width": round(stair["width"] * scale, 3), "bottom": round(stair.get("z0", 0) * scale, 3),
                       "height": round(stair["rise"] * stair["steps"] * scale, 3)})

    points = [point for wall in walls for point in (wall["a"], wall["b"])]
    bounds = [[min(point[0] for point in points), min(point[1] for point in points)],
              [max(point[0] for point in points), max(point[1] for point in points)]]
    source = plan.get("source", {})
    data = {"plan": plan_path.name, "units": plan.get("units", "m"), "ceiling": round(ceiling, 3),
            "bounds": bounds, "walls": walls, "rooms": rooms, "casework": boxes, "furniture": furniture, "stairs": stairs, "lamps": lamps, "shots": shots,
            "sheet": {"image": pathlib.Path(source.get("image", "")).name, "affine": sheet_affine(plan, scale)},
            "site": {key: plan.get("site", {}).get(key) for key in ("centre", "flat_radius", "ground_level")}}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"WALK data saved: {out_path} walls={len(walls)} rooms={len(rooms)} lamps={len(lamps)} furniture={len(furniture)} shots={len(shots)}")


if __name__ == "__main__":
    main()
