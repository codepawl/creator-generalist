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
  seed(seedNumber) { /* reseed every random source the game uses */ },
  step(ticks, keysDown) { /* optional: advance the fixed-step sim synchronously with these keys held */ }
}
```

- `progress` rises as the player advances (score, distance, rooms cleared). The softlock gate reads it.
- `state()` also carries every value a replay or a bot needs (position, health, score, target positions), plus
  `tick` and `dt` (seconds per tick, default 1/60) when the game has `step()`. The state hash is taken over this JSON.
- All game randomness comes from the seeded source. Never call `Math.random()` in game code.
- Game logic runs on a fixed timestep, not on wall time. Keep the rules in a pure module (`sim.js`) that the page and
  a Node check both import: unit checks and `step()` then run the same code as the browser.
- `step()` is what makes gate 3 testable: without it a wall-clock replay drifts by a frame and the hash differs on a
  deterministic game, so the probe reports gate 3 `not_tested`.
- A `?speed=N` debug query param (sim ticks per frame) lets a 3-minute lose clock fit in a short probe run. Write the
  factor used in `brief.md`.

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
| 2 | Win, lose, restart | runs reach `won` and `lost` (one run each with `--expect`, or both in one), and `restart()` returns to the initial state |
| 3 | Determinism | same seed and same inputs, run by ticks through `step()`, give the same state hash twice |
| 4 | Frame time | p95 frame time at or under the budget in `brief.md` (default 16.7 ms for 60 Hz), measured with a sync per frame |
| 5 | No softlock | `progress` never stalls longer than N seconds under an acting bot (default 30); end screens pause the clock |
| 6 | Controls shown | the controls are listed on screen or in the README, checked by a string test |

Each gate reports `pass`, `fail` or `not_tested`, and every gate that is not `pass` carries a `why` (the cause, with
numbers) and a `try` (the next action). A failing or untested hard gate blocks the preview; `not_tested` needs the
missing hook or run, not a fix to the game. Fix and rerun. A gate that fails twice means cut a feature, not tune the gate (`references/pipeline-spine.md`, critique loops).

## Run the gates on a web build

Serve the build locally or pass a file path (a prototype's `index.html` works; `build/` is for `game` mode). The probe
needs Node 18 or newer and Playwright with Chromium; when either is missing it exits 2 with a clear message. Run it
through the machine's GPU queue if it has one, in the background when it runs longer than about 2 minutes (machine
paths: `local.md`).

```
node {{SKILL_DIR}}/scripts/probe.mjs <url-or-file> --seconds 20 --seed 1 [--input replay.json]
  [--bot idle|random|script|<bot.mjs>] [--expect won|lost|both] [--gates 1,2,4] [--seeds 8]
  [--stall-seconds 30] [--viewport 1280x720] [--wallclock-determinism] [--out DIR]
```

It prints the expected wall time first, then writes `DIR/report.json` and `DIR/sheet.png`. Exit code: 0 all judged
gates pass, 1 a gate failed, 3 nothing failed but a gate is `not_tested`, 2 cannot run. The probe never creates a
canvas context: it syncs on the one the page made (WebGL or 2D).

| Gate | Command (`P` = `node {{SKILL_DIR}}/scripts/probe.mjs`) |
|---|---|
| 1, 4 and 5 | `P <build> --seconds 120 --bot random --seeds 3 --gates 1,4,5 --out {{WORK_DIR}}/qa/random` |
| 2, won | `P <build>?speed=4 --bot {{WORK_DIR}}/tools/bot.mjs --expect won --gates 2 --out {{WORK_DIR}}/qa/win` |
| 2, lost | `P <build>?speed=4 --bot idle --expect lost --gates 2 --out {{WORK_DIR}}/qa/lose` |
| 3 | `P <build> --input {{WORK_DIR}}/replays/run.json --gates 3 --out {{WORK_DIR}}/qa/determinism`: run by ticks through `step()`, twice per seed |
| 4 | any run above. The probe reads a pixel back after every frame, then takes p50, p95, p99 and the worst frame. Headless `requestAnimationFrame` alone over-reports fps, so never use it for this gate. Note how busy the GPU was |
| 6 | `grep -iE "controls|wasd|arrow|click|tap" README.md` or a string test on the page text |

- Bots: `idle` presses nothing, `random` mashes the game's keys, `script` plays `--input`. A goal-seeking game (reach,
  collect, aim, steer) needs a closed-loop module bot: a `.mjs` file exporting `act(state, elapsedMs)` that returns
  the held key names (or `{keys, pointer: {x, y, down}}`), called every poll. Open-loop replays drift and miss. The
  bot reacts once per poll of wall time, so keep `?speed` at 3 or lower for it; idle lose runs can go faster.
- Gates left out of `--gates` do not count toward the exit code.
- Wall time is about `--seconds` times the number of seeds; `--wallclock-determinism` (engines without `step()`)
  doubles it.

Features: `uv run --no-project python {{SKILL_DIR}}/scripts/check_features.py {{WORK_DIR}}/features.json` (exit 0 ok,
1 a feature lacks a verify step, or with `--start` any `passes` is true, 2 file unreadable). Run it before flipping
any `passes` value.

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
| Input hygiene | a script: hold a key and blur the window (keys must release), click or mash during the end screen (no instant skip), resize mid-run, hide the tab (the sim pauses) | all four behave |
| Session length | a competent closed-loop bot's win time against the session length in `brief.md` | within the brief's range |

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
