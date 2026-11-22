# House services: route them, then check the whole house

A house only "works" when its services do: power reaches every wall, every fixture drains and is vented, hot water
arrives without a long wait, gas appliances get a shutoff and air, wet rooms and the range are exhausted, and no two
trades run through the same spot. `scripts/systems_check.py` lays all of that out from `plan.json` as a first draft and
checks it against the residential code rules a first draft must meet.

It checks layout and code rules only. It does no load calculations, does not size pipes or ducts beyond the tables in
the script, and does not replace a licensed designer. Say this in any report that quotes it.

```bash
uv run --no-project python scripts/systems_check.py plan.json
uv run --no-project python scripts/test_systems_check.py
```

It writes `systems_report.json` (every element, run, check and reroute) and `systems.md` (the summary) beside the plan.
It exits 1 when a rule still fails or two trades still cross after rerouting.

## Reading map

- Plan keys: the `systems` section below.
- What it routes and the rules it checks: "Rules".
- How a clash is fixed: "Reroutes".
- What to put in the report: "Report".

## The `systems` section

Coordinates use the plan's own units and frame. Rooms are matched by `name`, and their `kind` decides the rules.

```json
"systems": {
  "heating": "radiant",
  "service": {"panel": [53.0, 24.6], "manifold": [55.9, 23.0], "gas_in": [59.6, 22.4], "sewer": [62.0, 27.0]},
  "fixtures": [{"id": "lav", "kind": "lavatory", "room": "Bath", "at": [43.3, 23.0]}],
  "appliances": [{"id": "boiler", "kind": "boiler", "fuel": "gas", "room": "Heater Rm", "at": [53.6, 23.2]}],
  "stacks": [{"at": [45.0, 24.0]}],
  "drain_depth_m": 0.9,
  "combustion_air_from_outdoors": false
}
```

- `heating`: `radiant` (slab loops) or `ducted` (supply registers).
- `service`: panel, water manifold, gas entry and sewer exit. Any of them may be left out; the script then picks the first
  room's centre, the water heater or the nearest outside wall.
- `fixtures[].kind`: `lavatory`, `sink`, `dishwasher`, `shower`, `tub`, `toilet`, `washer`, `laundry_tub`, `floor_drain`,
  `hose_bib`.
- `appliances[].kind`: `furnace`, `boiler`, `water_heater`, `range`, `dryer`, `fireplace`, with `fuel` `gas` or `electric`.
- `stacks`: optional. Without one, a vent stack goes in the interior wall nearest the wet rooms, and the report says so.
- `drain_depth_m`: how deep drains may fall below the floor (the slab or crawl space).
- Most drawings show none of this. Place fixtures where the drawing or the room's use puts them, and list every placement
  in `provenance.inferred`.

## Rules

| Trade | Rule | Code |
| --- | --- | --- |
| Power | No point along a wall space more than 6 ft from a receptacle; wall spaces of 2 ft and up count | NEC 210.52(A) |
| Power | No point along a counter more than 24 in from a receptacle | NEC 210.52(C) |
| Power | GFCI on bath, laundry, garage, carport, utility and every kitchen receptacle | NEC 210.8(A) |
| Power | A smoke alarm in each bedroom; a CO alarm outside the sleeping rooms, reached through doors, cased openings and `open_to` | IRC R314, R315 |
| Drain | Trap arm within the length for its trap size (5 ft at 1 1/4 in up to 16 ft at 4 in) | IRC P3105.1 |
| Drain | Fall of 1/4 in per ft below 3 in, 1/8 in per ft from 3 in, within `drain_depth_m` | IRC P3005.3 |
| Water | At most 0.5 gal (1.89 L) between the heater and a hot fixture | WaterSense |
| Gas | A shutoff in the same room, within 6 ft of each appliance | IFGC 409.5.1 |
| Gas | 50 cu ft of room per 1,000 Btu/h of vented input, or air from outdoors | IFGC 304.5.1 |
| Air | A bath with under 3 sq ft of glazing (half openable) gets a 50 cfm fan | IRC R303.3 |
| Air | A range gets a hood ducted outdoors | IRC M1505.4.4 |
| Heat | Radiant loops at 9 in spacing, at most 300 ft each | House rule |

House rules (loop spacing and length, 10 points per general circuit, a register per 150 sq ft) are not code. The report
marks them.

## Reroutes

The first pass places everything the simple way, then fixes each clash and records it:

- A receptacle on floor-to-ceiling glass slides to solid wall while it still reaches both ends of its slot; otherwise it
  becomes a floor receptacle within 18 in of the glass.
- A trap arm that is too long gets an individual vent in the nearest wall.
- A hot run over the water limit drops to 3/8 in PEX.
- A gas appliance in a room too small for its air gets two openings to outdoors in its outer wall.
- A light and a fan, or a range outlet and its hood, never share a point: devices are offset so their runs do not meet.
- Runs of different trades closer than 3 cm cross. The later trade lifts 8 cm in its travel plane, or turns its L the other
  way. A move only counts when it clears every earlier run, so a run cannot ping-pong between two others. Moves are tried
  upward and downward. A final scan of every pair feeds `unresolved`.

## Report

Quote the summary line (`SYSTEMS pass: 33/33 rules, 0 unresolved`), the first-pass clash count and the reroutes, and
the honest limit above. `systems_report.json` carries every element and run in metres in the plan frame, ready for an
X-ray view in a render or on a walk page.
