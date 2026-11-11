// Runs the probe on the fixture. Exit 0 on success or skip, 1 on a failed assertion.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const testsFolder = dirname(fileURLToPath(import.meta.url));
const probePath = join(testsFolder, "..", "scripts", "probe.mjs");
const fixturePath = join(testsFolder, "fixture-game.html");
const workFolder = mkdtempSync(join(tmpdir(), "probe-test-"));

// Wins at about 2.7 s; after the restart the bot idles and the timer loses.
const winningReplay = [
  { t: 300, type: "key", key: "ArrowRight", action: "down" },
  { t: 3600, type: "key", key: "ArrowRight", action: "up" },
];
const replayPath = join(workFolder, "replay.json");
writeFileSync(replayPath, JSON.stringify(winningReplay));

function runProbe(url, outName) {
  const outFolder = join(workFolder, outName);
  const result = spawnSync(
    process.execPath,
    [probePath, url, "--seconds", "14", "--seed", "1", "--input", replayPath, "--software",
      "--frame-budget-ms", "50", "--out", outFolder],
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

const good = runProbe(fixturePath, "good");
if (good.status === 2) {
  console.log(`SKIP: probe could not run (playwright or chromium missing).\n${good.output}`);
  process.exit(0);
}
check(good.status === 0, `good fixture exit ${good.status}\n${good.output}`);
for (const [name, gate] of Object.entries(good.report?.gates ?? {})) {
  check(gate.pass, `good fixture gate ${name} failed: ${gate.detail}`);
}
check(existsSync(join(workFolder, "good", "sheet.png")), "sheet.png missing");

const broken = runProbe(`${pathToFileURL(fixturePath).href}?broken=1`, "broken");
check(broken.status === 1, `broken fixture exit ${broken.status}\n${broken.output}`);
check(broken.report?.gates.console_errors.pass === false, "broken fixture console_errors should fail");

if (failures.length > 0) {
  console.error(`FAIL\n${failures.join("\n")}`);
  process.exit(1);
}
console.log("OK: good fixture passes all gates, broken fixture fails console_errors");
