#!/usr/bin/env node
/**
 * Playtest probe for web games that expose the page hook:
 *   window.__game = { state() -> { status: 'playing'|'won'|'lost', progress: number, ... },
 *                     restart(), seed(n) }
 * Runs a bot, collects hard-gate evidence and writes report.json and sheet.png.
 * Exit 0: all hard gates pass. 1: a gate failed. 2: the probe could not run.
 */

import { parseArgs } from "node:util";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const USAGE = `Usage: node probe.mjs <url-or-file> --seconds 20 --seed 1 [options]
  --input FILE          replay JSON: [{t, type:'key'|'pointer', key?, x?, y?, action:'down'|'up'|'move'}]
  --bot idle|random|script   default: script when --input is given, else random
  --seeds N             run seeds seed..seed+N-1 and aggregate (default 1)
  --stall-seconds N     softlock limit (default 30, a default)
  --viewport WxH        default 1280x720
  --frame-budget-ms N   p95 frame time limit (default 16.7 for 60 Hz, a default)
  --out DIR             default ./probe-out
  --software            use SwiftShader instead of the GPU (for tests)
  --help`;

const { positionals, values } = parseArgs({
  allowPositionals: true,
  options: {
    seconds: { type: "string", default: "20" },
    seed: { type: "string", default: "1" },
    input: { type: "string" },
    bot: { type: "string" },
    seeds: { type: "string", default: "1" },
    "stall-seconds": { type: "string", default: "30" },
    viewport: { type: "string", default: "1280x720" },
    "frame-budget-ms": { type: "string", default: "16.7" },
    out: { type: "string", default: "probe-out" },
    software: { type: "boolean", default: false },
    help: { type: "boolean", short: "h" },
  },
});

if (values.help) {
  console.log(USAGE);
  process.exit(0);
}
if (positionals.length === 0) {
  console.error(USAGE);
  process.exit(2);
}

const targetArgument = positionals[0];
const runSeconds = Number(values.seconds);
const firstSeed = Number(values.seed);
const seedCount = Math.max(1, Number(values.seeds));
const stallLimitSeconds = Number(values["stall-seconds"]);
const frameBudgetMs = Number(values["frame-budget-ms"]);
const [viewportWidth, viewportHeight] = values.viewport.split("x").map(Number);
const botKind = values.bot ?? (values.input ? "script" : "random");
const outputFolder = resolve(values.out);
const POLL_INTERVAL_MS = 250;
const TICK_INTERVAL_MS = 50;

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

if (!["idle", "random", "script"].includes(botKind)) fail(`Unknown --bot ${botKind}`);
if (botKind === "script" && !values.input) fail("--bot script needs --input replay.json");

// Playwright comes from the project, or from PLAYWRIGHT_FROM: a folder whose node_modules has it.
async function loadChromium() {
  try {
    return (await import("playwright")).chromium;
  } catch {
    try {
      const { createRequire } = await import("node:module");
      const baseFolder = (process.env.PLAYWRIGHT_FROM ?? process.cwd()).replace(/[\\/]?$/, "/");
      return createRequire(baseFolder)("playwright").chromium;
    } catch {
      return null;
    }
  }
}
const chromium = await loadChromium();
if (!chromium) {
  fail(
    "playwright is not installed. Install it where you run the probe:\n" +
      "  npm install playwright && npx playwright install chromium\n" +
      "or point PLAYWRIGHT_FROM at a folder whose node_modules holds it.",
  );
}

const targetUrl = /^(https?|file):/i.test(targetArgument)
  ? targetArgument
  : pathToFileURL(resolve(targetArgument)).href;

const replayEvents = values.input ? JSON.parse(readFileSync(values.input, "utf8")) : [];

function createMulberry32(seedNumber) {
  let state = seedNumber >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), 1 | state);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

// Runs before page scripts: seeded Math.random and a frame-time loop with a GPU sync per frame.
function buildInitScript(seedNumber) {
  return `
(() => {
  let randomState = ${seedNumber} >>> 0;
  Math.random = () => {
    randomState = (randomState + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(randomState ^ (randomState >>> 15), 1 | randomState);
    mixed = (mixed + Math.imul(mixed ^ (mixed >>> 7), 61 | mixed)) ^ mixed;
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
  window.__probeFrames = [];
  const syncCache = new WeakMap();
  function forceSync() {
    const canvas = document.querySelector('canvas');
    if (!canvas || canvas.width === 0 || canvas.height === 0) return;
    let sync = syncCache.get(canvas);
    if (!sync) {
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      if (gl) {
        const pixel = new Uint8Array(4);
        sync = () => gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      } else {
        const context2d = canvas.getContext('2d');
        sync = context2d ? () => context2d.getImageData(0, 0, 1, 1) : () => {};
      }
      syncCache.set(canvas, sync);
    }
    try { sync(); } catch (error) {}
  }
  let previousTime = null;
  function onFrame() {
    forceSync();
    const afterSync = performance.now();
    if (previousTime !== null) window.__probeFrames.push(afterSync - previousTime);
    previousTime = afterSync;
    requestAnimationFrame(onFrame);
  }
  requestAnimationFrame(onFrame);
})();`;
}

function buildRandomBotEvents(seedNumber) {
  const nextRandom = createMulberry32(seedNumber + 1000);
  const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " "];
  const events = [];
  let timeMs = 100;
  while (timeMs < runSeconds * 1000) {
    if (nextRandom() < 0.25) {
      const x = Math.round(nextRandom() * viewportWidth);
      const y = Math.round(nextRandom() * viewportHeight);
      events.push({ t: timeMs, type: "pointer", x, y, action: "move" });
      events.push({ t: timeMs + 20, type: "pointer", x, y, action: "down" });
      events.push({ t: timeMs + 80, type: "pointer", x, y, action: "up" });
    } else {
      const key = keys[Math.floor(nextRandom() * keys.length)];
      const holdMs = 80 + Math.floor(nextRandom() * 400);
      events.push({ t: timeMs, type: "key", key, action: "down" });
      events.push({ t: timeMs + holdMs, type: "key", key, action: "up" });
    }
    timeMs += 100 + Math.floor(nextRandom() * 500);
  }
  return events.sort((first, second) => first.t - second.t);
}

function eventsForBot(seedNumber) {
  if (botKind === "idle") return [];
  if (botKind === "script") return [...replayEvents].sort((first, second) => first.t - second.t);
  return buildRandomBotEvents(seedNumber);
}

async function dispatchEvent(page, inputEvent) {
  if (inputEvent.type === "key") {
    if (inputEvent.action === "down") await page.keyboard.down(inputEvent.key);
    else await page.keyboard.up(inputEvent.key);
    return;
  }
  if (inputEvent.action === "move") await page.mouse.move(inputEvent.x, inputEvent.y);
  else if (inputEvent.action === "down") await page.mouse.down();
  else await page.mouse.up();
}

const sleep = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));
const percentile = (sortedValues, fraction) =>
  sortedValues.length === 0
    ? null
    : sortedValues[Math.min(sortedValues.length - 1, Math.floor(fraction * sortedValues.length))];

async function readState(page) {
  return page.evaluate(() => (window.__game?.state ? window.__game.state() : null)).catch(() => null);
}

async function runOnce(browser, seedNumber, { takeShots }) {
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: viewportHeight } });
  await context.addInitScript({ content: buildInitScript(seedNumber) });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (/favicon/i.test(message.location().url ?? "")) return;
    consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  const loadStart = Date.now();
  await page.goto(targetUrl, { waitUntil: "load" });
  const loadMs = Date.now() - loadStart;
  const hookPresent = await page.evaluate(() => Boolean(window.__game?.state));
  if (hookPresent) await page.evaluate((value) => window.__game.seed?.(value), seedNumber);

  const events = eventsForBot(seedNumber);
  const statusesSeen = new Set();
  const shots = [];
  let maxProgress = -Infinity;
  let roundBestProgress = -Infinity;
  let stallStartMs = null;
  let longestStallSeconds = 0;
  let restartAttempts = 0;
  let restartFailures = 0;
  let firstInputAtMs = null;
  let inputResponseMs = null;
  let baselineStateJson = null;
  let nextEventIndex = 0;
  let nextPollAtMs = 0;
  let nextShotAtMs = 0;
  const shotEveryMs = Math.max(1000, (runSeconds * 1000) / 6);
  const startedAt = Date.now();

  while (Date.now() - startedAt < runSeconds * 1000) {
    const elapsedMs = Date.now() - startedAt;
    while (nextEventIndex < events.length && events[nextEventIndex].t <= elapsedMs) {
      if (firstInputAtMs === null) {
        firstInputAtMs = Date.now();
        baselineStateJson = JSON.stringify(await readState(page));
      }
      await dispatchEvent(page, events[nextEventIndex]).catch(() => {});
      nextEventIndex += 1;
    }
    if (hookPresent) {
      const state = await readState(page);
      if (state) {
        if (firstInputAtMs !== null && inputResponseMs === null && JSON.stringify(state) !== baselineStateJson) {
          inputResponseMs = Date.now() - firstInputAtMs;
        }
        if (elapsedMs >= nextPollAtMs) {
          nextPollAtMs = elapsedMs + POLL_INTERVAL_MS;
          statusesSeen.add(state.status);
          const progress = Number(state.progress);
          if (Number.isFinite(progress)) maxProgress = Math.max(maxProgress, progress);
          if (state.status === "playing") {
            if (Number.isFinite(progress) && progress > roundBestProgress) {
              roundBestProgress = progress;
              stallStartMs = null;
            } else if (stallStartMs === null) {
              stallStartMs = Date.now();
            }
            if (stallStartMs !== null) {
              longestStallSeconds = Math.max(longestStallSeconds, (Date.now() - stallStartMs) / 1000);
            }
          } else if (state.status === "won" || state.status === "lost") {
            restartAttempts += 1;
            await page.evaluate(() => window.__game.restart?.()).catch(() => {});
            let backToPlaying = false;
            const restartDeadline = Date.now() + 2000;
            while (Date.now() < restartDeadline && !backToPlaying) {
              await sleep(100);
              backToPlaying = (await readState(page))?.status === "playing";
            }
            if (!backToPlaying) restartFailures += 1;
            roundBestProgress = -Infinity;
            stallStartMs = null;
          }
        }
      }
    }
    if (takeShots && elapsedMs >= nextShotAtMs) {
      nextShotAtMs = elapsedMs + shotEveryMs;
      shots.push(await page.screenshot({ type: "png" }).catch(() => null));
    }
    await sleep(TICK_INTERVAL_MS);
  }

  const finalState = hookPresent ? await readState(page) : null;
  const frameDeltas = await page.evaluate(() => window.__probeFrames.slice(5)).catch(() => []);
  const pageText = await page.evaluate(() => document.body?.innerText ?? "").catch(() => "");
  await context.close();
  return {
    seedNumber,
    hookPresent,
    consoleErrors,
    statusesSeen: [...statusesSeen],
    maxProgress: Number.isFinite(maxProgress) ? maxProgress : null,
    longestStallSeconds,
    restartAttempts,
    restartFailures,
    finalStateJson: JSON.stringify(finalState),
    frameDeltas,
    pageText,
    loadMs,
    inputResponseMs,
    shots: shots.filter(Boolean),
  };
}

function findControlsInReadme() {
  if (!targetUrl.startsWith("file:")) return false;
  const targetPath = fileURLToPath(targetUrl);
  const readmePath = ["README.md", "readme.md", "README.txt"]
    .map((name) => join(dirname(targetPath), name))
    .find((candidate) => existsSync(candidate));
  return Boolean(readmePath && /controls/i.test(readFileSync(readmePath, "utf8")));
}

async function writeContactSheet(browser, shots) {
  if (shots.length === 0) return;
  const images = shots.map((shot) => `<img src="data:image/png;base64,${shot.toString("base64")}">`).join("");
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  await page.setContent(
    `<body style="margin:0;background:#000;display:grid;grid-template-columns:repeat(3,1fr);gap:4px">` +
      `${images}<style>img{width:100%}</style></body>`,
  );
  await page.screenshot({ path: join(outputFolder, "sheet.png"), fullPage: true });
  await page.close();
}

const launchArguments = values.software
  ? ["--use-gl=swiftshader", "--mute-audio"]
  : process.platform === "win32"
    ? ["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist", "--mute-audio"]
    : ["--mute-audio"];

let browser;
try {
  browser = await chromium.launch({ headless: true, args: launchArguments });
} catch (error) {
  fail(`Could not launch chromium (${error.message}). Try: npx playwright install chromium`);
}

mkdirSync(outputFolder, { recursive: true });
let report;
try {
  const runs = [];
  for (let offset = 0; offset < seedCount; offset += 1) {
    runs.push(await runOnce(browser, firstSeed + offset, { takeShots: offset === 0 }));
  }
  const repeatRun = await runOnce(browser, firstSeed, { takeShots: false });
  await writeContactSheet(browser, runs[0].shots);

  const hookPresent = runs.every((run) => run.hookPresent);
  const allErrors = runs.flatMap((run) => run.consoleErrors).concat(repeatRun.consoleErrors);
  const statuses = new Set(runs.flatMap((run) => run.statusesSeen));
  const restartAttempts = runs.reduce((sum, run) => sum + run.restartAttempts, 0);
  const restartFailures = runs.reduce((sum, run) => sum + run.restartFailures, 0);
  const hashOf = (text) => createHash("sha256").update(text).digest("hex");
  const firstHash = hashOf(runs[0].finalStateJson);
  const secondHash = hashOf(repeatRun.finalStateJson);
  const frames = runs.flatMap((run) => run.frameDeltas).sort((first, second) => first - second);
  const frameP95 = percentile(frames, 0.95);
  const longestStall = Math.max(...runs.map((run) => run.longestStallSeconds));
  const controlsFound = runs.some((run) => /controls/i.test(run.pageText)) || findControlsInReadme();
  const noHook = "window.__game hook missing";

  report = {
    target: targetUrl,
    bot: botKind,
    seeds: runs.map((run) => run.seedNumber),
    gates: {
      console_errors: {
        pass: allErrors.length === 0,
        detail: allErrors.length === 0 ? "none" : `${allErrors.length}: ${allErrors.slice(0, 3).join(" | ")}`,
      },
      won_and_lost: {
        pass: hookPresent && statuses.has("won") && statuses.has("lost"),
        detail: hookPresent ? `statuses seen: ${[...statuses].join(", ")}` : noHook,
      },
      restart: {
        pass: hookPresent && restartAttempts > 0 && restartFailures === 0,
        detail: hookPresent
          ? `${restartAttempts} restarts, ${restartFailures} failed to return to playing within 2 s`
          : noHook,
      },
      determinism: {
        pass: hookPresent && firstHash === secondHash,
        detail: hookPresent ? `${firstHash.slice(0, 12)} vs ${secondHash.slice(0, 12)}` : noHook,
      },
      frame_time_p95: {
        pass: frameP95 !== null && frameP95 <= frameBudgetMs,
        detail:
          frameP95 === null
            ? "no frames recorded"
            : `p50 ${percentile(frames, 0.5).toFixed(1)} ms, p95 ${frameP95.toFixed(1)} ms, p99 ${percentile(frames, 0.99).toFixed(1)} ms, budget ${frameBudgetMs} ms${values["frame-budget-ms"] === "16.7" ? " (default)" : ""}`,
      },
      softlock: {
        pass: hookPresent && longestStall <= stallLimitSeconds,
        detail: hookPresent
          ? `longest stall ${longestStall.toFixed(1)} s, limit ${stallLimitSeconds} s${values["stall-seconds"] === "30" ? " (default)" : ""}`
          : noHook,
      },
      controls: {
        pass: controlsFound,
        detail: controlsFound ? "controls listed" : "no 'controls' text on the page or in a README beside the file",
      },
    },
    advisory: {
      load_ms: Math.round(runs[0].loadMs),
      input_response_ms: runs[0].inputResponseMs,
      input_response_note: "polled every 50 ms, so coarse",
      max_progress: Math.max(...runs.map((run) => run.maxProgress ?? -Infinity)),
    },
  };
} finally {
  await browser.close();
}

writeFileSync(join(outputFolder, "report.json"), JSON.stringify(report, null, 2));
let allPass = true;
for (const [gateName, gate] of Object.entries(report.gates)) {
  allPass = allPass && gate.pass;
  console.log(`${gate.pass ? "PASS" : "FAIL"}  ${gateName}: ${gate.detail}`);
}
process.exit(allPass ? 0 : 1);
