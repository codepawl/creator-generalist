// Runs the probe on the fixtures. Exit 0 on success or skip, 1 on a failed assertion.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const testsFolder = dirname(fileURLToPath(import.meta.url));
const probePath = join(testsFolder, "..", "scripts", "probe.mjs");
const fixturePath = join(testsFolder, "fixture-game.html");
const lateFixturePath = join(testsFolder, "fixture-2d-late.html");
const botPath = join(testsFolder, "fixture-bot.mjs");
const workFolder = mkdtempSync(join(tmpdir(), "probe-test-"));

// Wins at about 2.7 s; after the restart the bot idles and the timer loses.
const winningReplay = [
  { t: 300, type: "key", key: "ArrowRight", action: "down" },
  { t: 3600, type: "key", key: "ArrowRight", action: "up" },
];
const replayPath = join(workFolder, "replay.json");
writeFileSync(replayPath, JSON.stringify(winningReplay));

const replayArguments = ["--seconds", "14", "--input", replayPath];

function runProbe(url, outName, extraArguments = replayArguments) {
  const outFolder = join(workFolder, outName);
  const result = spawnSync(
    process.execPath,
    [probePath, url, "--seed", "1", "--software", "--frame-budget-ms", "50", "--out", outFolder, ...extraArguments],
    { encoding: "utf8", env: process.env },
  );
  const reportPath = join(outFolder, "report.json");
  const report = existsSync(reportPath) ? JSON.parse(readFileSync(reportPath, "utf8")) : null;
  return { status: result.status, report, output: result.stdout + result.stderr };
}

const failures = [];
function check(condition, message) {
  if (!condition) failures.push(message);
}

function checkAllGatesPass(run, label) {
  check(run.status === 0, `${label} exit ${run.status}\n${run.output}`);
  for (const [name, gate] of Object.entries(run.report?.gates ?? {})) {
    check(gate.status === "pass", `${label} gate ${name} is ${gate.status}: ${gate.detail}`);
  }
}

const good = runProbe(fixturePath, "good");
if (good.status === 2) {
  console.log(`SKIP: probe could not run (playwright or chromium missing).\n${good.output}`);
  process.exit(0);
}
checkAllGatesPass(good, "good fixture");
check(existsSync(join(workFolder, "good", "sheet.png")), "sheet.png missing");
check(good.report?.frame_time?.context_type === "2d", "good fixture should sync on its 2d context");

const broken = runProbe(`${pathToFileURL(fixturePath).href}?broken=1`, "broken");
check(broken.status === 1, `broken fixture exit ${broken.status}\n${broken.output}`);
check(broken.report?.gates.console_errors.status === "fail", "broken fixture console_errors should fail");
check(Boolean(broken.report?.gates.console_errors.why), "failed gate needs why");

const late = runProbe(lateFixturePath, "late");
checkAllGatesPass(late, "2d-late fixture");
check(late.report?.frame_time?.context_type === "2d", "2d-late fixture should get a non-null 2d context");
check(late.report?.frame_time?.method === "context-readback", "2d-late fixture should sync by readback");
check(late.report?.gates.determinism.status === "pass", "2d-late determinism should pass via step()");

const moduleBot = runProbe(fixturePath, "module", ["--seconds", "8", "--bot", botPath, "--expect", "won", "--gates", "1,2"]);
check(moduleBot.report?.gates.won_and_lost.status === "pass", `module bot should reach won\n${moduleBot.output}`);
check(moduleBot.report?.gates.won_and_lost.sub_checks.reached_won === true, "reached_won should be true");

const idle = runProbe(fixturePath, "idle", ["--seconds", "4", "--bot", "idle", "--gates", "5"]);
check(idle.report?.gates.softlock.status === "not_tested", "idle bot softlock should be not_tested");
check(Boolean(idle.report?.gates.softlock.why), "idle softlock needs why");

const noStep = runProbe(`${pathToFileURL(fixturePath).href}?nostep=1`, "nostep");
check(noStep.report?.gates.determinism.status === "not_tested", "no step(): determinism should be not_tested");
check(Boolean(noStep.report?.gates.determinism.try), "not_tested determinism needs try");
check(noStep.status === 3, `no step(): exit should be 3, got ${noStep.status}\n${noStep.output}`);

const throwBotPath = join(workFolder, "throwbot.mjs");
writeFileSync(throwBotPath, 'export function act() { throw new Error("boom"); }\n');
const throwing = runProbe(fixturePath, "throwbot", ["--seconds", "3", "--bot", throwBotPath]);
check(throwing.status === 2, `throwing bot: exit should be 2, got ${throwing.status}`);
check(/bot threw: boom/.test(throwing.output), "throwing bot: message should say 'bot threw: boom'");

const queryPath = runProbe(`${fixturePath}?nostep=1`, "query", ["--seconds", "3", "--gates", "3"]);
check(queryPath.status === 3, `local path with ?query: exit should be 3, got ${queryPath.status}\n${queryPath.output}`);

const subset = runProbe(fixturePath, "subset", ["--seconds", "3", "--gates", "1,6"]);
check(subset.status === 0, `--gates 1,6 on a good game: unselected gates must not force exit 3, got ${subset.status}\n${subset.output}`);

const badGates = runProbe(fixturePath, "badgates", ["--seconds", "3", "--gates", "9,x"]);
check(badGates.status === 2, `--gates 9,x: exit should be 2, got ${badGates.status}`);
const badSeeds = runProbe(fixturePath, "badseeds", ["--seconds", "3", "--seeds", "0"]);
check(badSeeds.status === 2, `--seeds 0: exit should be 2, got ${badSeeds.status}`);

const throwStepPath = join(workFolder, "throwstep.html");
writeFileSync(
  throwStepPath,
  `<canvas width="64" height="64"></canvas><script>
  const context = document.querySelector("canvas").getContext("2d");
  window.__game = {
    seed() {}, restart() {}, state() { return { status: "playing", tick: 0 }; },
    step() { throw new Error("stepboom"); },
  };
  (function draw() { context.fillRect(0, 0, 8, 8); requestAnimationFrame(draw); })();
  </script>`,
);
const throwStep = runProbe(throwStepPath, "throwstep", ["--seconds", "3", "--gates", "3"]);
check(throwStep.status === 1, `throwing step(): exit should be 1, got ${throwStep.status}\n${throwStep.output}`);
check(throwStep.report?.gates.determinism.status === "fail", "throwing step(): determinism should fail");
check(/step\(\) threw: .*stepboom/.test(throwStep.report?.gates.determinism.why ?? ""), "throwing step(): why should name the exception");

const noopBotPath = join(workFolder, "nopbot.mjs");
writeFileSync(noopBotPath, "export function act() { return []; }\n");
const noopBot = runProbe(fixturePath, "noopbot", ["--seconds", "3", "--gates", "2,5", "--expect", "won", "--bot", noopBotPath]);
check(noopBot.report?.input_response_ms == null, `no-op bot: input_response_ms should be null, got ${noopBot.report?.input_response_ms}`);

for (const badArguments of [
  ["--seconds", "abc"],
  ["--seconds", "0"],
  ["--viewport", "foo"],
  ["--seed", "1.5"],
  ["--stall-seconds", "-1"],
  ["--frame-budget-ms", "x"],
]) {
  const badRun = runProbe(fixturePath, "badinput", ["--gates", "1", ...badArguments]);
  check(badRun.status === 2, `${badArguments.join(" ")}: exit should be 2, got ${badRun.status}`);
  check(!/\n\s+at /.test(badRun.output), `${badArguments.join(" ")}: should print one line, not a stack trace`);
}

if (failures.length > 0) {
  console.error(`FAIL\n${failures.join("\n")}`);
  process.exit(1);
}
console.log("OK: good and 2d-late pass all gates, broken fails console_errors, module bot wins, idle softlock and missing step() are not_tested (exit 3)");
