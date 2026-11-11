# Playtest gates (`playtest-gates.md`)

Six hard gates block the preview. Advisory checks are reported and never block. Fun and a clear goal are a human call: the user plays the greybox at step 4 and the preview at step 8 (`references/pipeline-spine.md`). An agent never claims a game is fun.

Every number below is a default. Set the real value per game and per target machine in `brief.md` and mark it "default" until it is calibrated.

<!-- skill-navigation:start -->
## Reading Map

- [Playtest gates (`playtest-gates.md`)](#playtest-gates-playtest-gatesmd)
- [Page hook contract](#page-hook-contract)
- [Hard gates](#hard-gates)
- [Run the gates on a web build](#run-the-gates-on-a-web-build)
- [Advisory checks](#advisory-checks)
- [Engine builds](#engine-builds)
- [What bots cannot judge](#what-bots-cannot-judge)
- [Optional human playtest](#optional-human-playtest)
<!-- skill-navigation:end -->

## Page hook contract

A web build exposes this before the first frame is drawn:

```js
window.__game = {
  state() { /* JSON: at least { status: 'playing'|'won'|'lost', progress: number } */ },
  restart() { /* back to the exact initial state */ },
  seed(seedNumber) { /* reseed every random source the game uses */ }
}
```

- `progress` rises as the player advances (score, distance, rooms cleared). The softlock gate reads it.
- `state()` also carries every value a replay should assert (position, health, score). The state hash is taken over this JSON.
- All game randomness comes from the seeded source. Never call `Math.random()` in game code.
- Game logic runs on a fixed timestep, not on wall time.

Input replay JSON, an array of events:

```json
[
  { "t": 0, "type": "key", "key": "ArrowRight", "action": "down" },
  { "t": 800, "type": "key", "key": "ArrowRight", "action": "up" },
  { "t": 900, "type": "pointer", "x": 640, "y": 360, "action": "move" }
]
```

`t` is milliseconds from the start of the run. `key` is used by key events, `x` and `y` by pointer events.

## Hard gates

| # | Gate | Passes when |
|---|---|---|
| 1 | No errors | zero console errors and zero uncaught script errors over a full run |
| 2 | Win, lose, restart | the bot reaches `won` and `lost`, and `restart()` returns to the initial state |
| 3 | Determinism | same seed and same input replay give the same final state hash twice |
| 4 | Frame time | p95 frame time at or under the budget in `brief.md` (default 16.7 ms for 60 Hz), measured with a sync per frame |
| 5 | No softlock | `progress` never stalls longer than N seconds under the bot (default 30) |
| 6 | Controls shown | the controls are listed on screen or in the README, checked by a string test |

A failing gate blocks the preview. Fix and rerun. A gate that fails twice means cut a feature, not tune the gate (`references/pipeline-spine.md`, critique loops).

## Run the gates on a web build

Serve the build locally (or pass a file path). `scripts/probe.mjs` needs Node 18 or newer and Playwright with Chromium. When either is missing it exits 2 with a clear message.

```
node scripts/probe.mjs <url-or-file> --seconds 20 --seed 1 [--input replay.json] [--bot idle|random|script] [--seeds 8] [--stall-seconds 30] [--viewport 1280x720] [--out DIR]
```

It writes `DIR/report.json` and `DIR/sheet.png`. Exit code: 0 all hard gates pass, 1 a gate failed, 2 cannot run.

| Gate | Command |
|---|---|
| 1 and 5 | `node scripts/probe.mjs {{WORK_DIR}}/build/index.html --seconds 120 --seed 1 --bot random --stall-seconds 30 --out {{WORK_DIR}}/qa/run1` |
| 2 | `node scripts/probe.mjs <url> --seconds 60 --seed 1 --bot script --input {{WORK_DIR}}/qa/win.json --out {{WORK_DIR}}/qa/win`, then the same with `lose.json`. Reaching `won`, `lost` and then calling `restart()` is recorded in `report.json` |
| 3 | `node scripts/probe.mjs <url> --seconds 20 --seed 1 --input replay.json --out {{WORK_DIR}}/qa/a`, rerun into `qa/b`. The probe also runs the pair itself and reports `deterministic: true or false` |
| 4 | any run above. The probe reads a pixel (a sync) after every frame, then takes p50, p95, p99 and the worst frame. Headless `requestAnimationFrame` alone over-reports fps, so never use it for this gate |
| 6 | `grep -iE "controls|wasd|arrow|click|tap" README.md` or a string test on the page text |
| all seeds | add `--seeds 8` to a random-bot run: eight seeds, crashes and stalls logged per seed |

Features: `uv run --no-project python scripts/check_features.py {{WORK_DIR}}/features.json` (exit 0 ok, 1 a feature lacks a verify step or a pass flag changed wrongly, 2 file unreadable). Run it before flipping any `passes` value.

Run real measurements on a GPU browser. Software rendering (SwiftShader) is for the script's own unit tests only, because it changes frame time.

Native dialogs and UI drawn off the canvas are invisible to browser automation. Add one scripted manual check for each (title screen, pause, any `alert`).

## Advisory checks

Report these in `report.json` and the preview note. They never block, because their numbers are uncalibrated defaults.

| Check | How | Default |
|---|---|---|
| Input to response | inject one input, count frames until the picture changes | 2 frames at 60 Hz |
| Load time | time from navigation to the first interactive frame, plus bytes shipped | 5 s |
| Restart time | time from `restart()` to a playable frame | 2 s |
| First input | seconds from load to the first thing the player can do | 10 s |
| Readability | contact sheet at 360x640 and 1920x1080; player, threat and goal against the background | contrast 3:1 |
| Audio | every input verb and outcome has a cue; peak under 1.0; limiter before the output; the game stays playable muted | n/a |

- Readability: judge the sheet with a subagent that returns text. Run the critique two or three times and act on items flagged twice. A model judge is good at filtering and weak at absolute scores.
- Audio tests run muted on a speaker-less path: tap an analyser node, never play to the real output in a test.
- A forgiveness window (accept a jump a few frames late or early) is a feel default, around 5 frames. Tune it by playing, not by a gate.

## Engine builds

Engine gates come from logs plus a capture and are partly manual. Say which in the report.

| Engine | Run | Automatic | Manual |
|---|---|---|---|
| Godot | `godot --headless --fixed-fps 60 --quit-after 1800 --path {{WORK_DIR}}/project` | exit code and stderr for gate 1; state lines in stdout for gates 2, 3, 5 | frame time reading from the profiler; controls check |
| Godot capture | `godot --path {{WORK_DIR}}/project --fixed-fps 60 --write-movie capture.avi --quit-after 3600` (needs a display) | the movie file | judging it |
| Unity | `Unity -batchmode -nographics -projectPath <dir> -executeMethod <TestEntry> -logFile <log>` | the log and exit code for gates 1, 2, 3 | frame time, capture |
| Unreal | packaged build, or `UnrealEditor <uproject> -game -ExecCmds="<console commands>" -log` | the log for gates 1, 2, 3, 5 | frame time (`stat unit`), capture |

- The game writes one log line per state change: `GATE state status=<status> progress=<n> hash=<hash>`. The gates read those lines. Seeds and input replays are fed through a launch argument or a config file (see `references/engine-and-ship.md`).
- Gate 3 compares the last `hash` of two runs. Gate 5 compares `progress` over time in the log.
- Wrapper scripts for the engine commands are not shipped until someone has run them on a real game. Keep the commands as notes and record what was run.
- More than 5 screenshots always go to a subagent that returns text.

## What bots cannot judge

- Fun. Whether the loop is worth repeating.
- Whether the goal is clear in the first seconds.
- Whether the difficulty feels fair.
- Whether the look matches the user's taste.

Hand these to the user at step 4 (greybox plus style frames) and step 8 (preview plus capture). Ask for one line of reason. A bot that plays through is not a fun check; a model that plays by screenshots is exploratory only and never a gate.

## Optional human playtest

After the preview, the user can send the link to a few people and note where each quit or got stuck. Several small rounds beat one large one. This is not a pipeline gate, and an agent cannot run it.

Sources: studio playtest practice and usability research on small repeated rounds; agent game-benchmark papers showing automated checks beat model judges on behaviour.
