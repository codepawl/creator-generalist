// Camera smoothness check for films whose camera is a function of time.
//
// Two causes make a keyed camera look stiff:
//   1. Kinks: the speed jumps at a key. Piecewise linear, or a per-segment ease mixed with linear, does this.
//   2. Zigzags: a channel turns back within a short time (yaw -30, -26, -32, -24).
// This script samples the camera densely and fails on both, so a stiff camera never reaches a preview.
//
// Usage:
//   node camera-smoothness.mjs <timeline module> [--export cameraAt] [--duration 38]
//        [--log width] [--relative targetX:width] [--min-dwell 1.5]
//
// The module must export a function (default name cameraAt) that returns an object of numbers for a time in
// seconds. If you do not pass --duration, the script reads DURATION from the module.
//   --log <channel>          measure the channel in decades (zoom width, for example)
//   --relative <a>:<b>       measure channel a in units of channel b (pan in frame widths)
//   --max <channel>:<speed>  fail when the channel's peak speed is over the limit. Defaults for a calm film:
//                            width 1.2 (decades/s, with --log), targetX 1.5 (frame widths/s, with --relative)
// Fix hints are printed with each failure.

import { pathToFileURL } from 'node:url';
import path from 'node:path';

function parseArguments(argv) {
  const options = { exportName: 'cameraAt', logChannels: [], relative: {}, maxSpeed: {}, minDwell: 1.5, duration: null, module: null };
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument === '--export') options.exportName = argv[++index];
    else if (argument === '--duration') options.duration = Number(argv[++index]);
    else if (argument === '--log') options.logChannels.push(argv[++index]);
    else if (argument === '--relative') {
      const [channel, scale] = argv[++index].split(':');
      options.relative[channel] = scale;
    } else if (argument === '--max') {
      const [channel, limit] = argv[++index].split(':');
      options.maxSpeed[channel] = Number(limit);
    } else if (argument === '--min-dwell') options.minDwell = Number(argv[++index]);
    else options.module = argument;
  }
  if (!options.module) {
    console.error('usage: node camera-smoothness.mjs <timeline module> [--export cameraAt] [--log width] [--relative targetX:width]');
    process.exit(2);
  }
  return options;
}

/** Velocity of every channel at a time, by central difference, in the measuring units of each channel. */
function velocities(cameraAt, time, step, options) {
  const before = cameraAt(time - step);
  const after = cameraAt(time + step);
  const middle = cameraAt(time);
  const result = {};
  for (const channel of Object.keys(middle)) {
    if (typeof middle[channel] !== 'number') continue;
    let delta;
    if (options.logChannels.includes(channel)) delta = Math.log10(after[channel]) - Math.log10(before[channel]);
    else delta = after[channel] - before[channel];
    const scaleChannel = options.relative[channel];
    if (scaleChannel) delta /= Math.abs(middle[scaleChannel]);
    result[channel] = delta / (2 * step);
  }
  return result;
}

const options = parseArguments(process.argv.slice(2));
const timelineModule = await import(pathToFileURL(path.resolve(options.module)).href);
const cameraAt = timelineModule[options.exportName];
const duration = options.duration ?? timelineModule.DURATION;
if (typeof cameraAt !== 'function' || !duration) {
  console.error(`the module needs an exported function ${options.exportName} and a DURATION (or pass --duration)`);
  process.exit(2);
}

const sampleRate = 1000;
const step = 1 / sampleRate;
const series = [];
for (let time = step; time < duration - step; time += step) series.push({ time, velocity: velocities(cameraAt, time, step / 4, options) });
const channels = Object.keys(series[0].velocity);

let failures = 0;
for (const channel of channels) {
  const speeds = series.map((sample) => Math.abs(sample.velocity[channel]));
  const peakSpeed = Math.max(...speeds);
  const peakTime = series[speeds.indexOf(peakSpeed)].time;
  if (peakSpeed < 1e-9) continue;

  // Kinks: a smooth curve changes speed by a tiny amount in 1 ms, so a jump of 1% of peak speed in 1 ms is a kink.
  const kinks = [];
  for (let index = 1; index < series.length; index++) {
    const jump = Math.abs(series[index].velocity[channel] - series[index - 1].velocity[channel]);
    if (jump > 0.01 * peakSpeed) kinks.push(series[index].time);
  }
  const kinkTimes = kinks.filter((time, index) => index === 0 || time - kinks[index - 1] > 0.05);

  // Zigzags: the channel moves one way at real speed, then turns back within the minimum dwell time.
  const moving = 0.15 * peakSpeed;
  const zigzags = [];
  let lastSign = 0;
  let lastMovingTime = -Infinity;
  for (const sample of series) {
    const velocity = sample.velocity[channel];
    if (Math.abs(velocity) < moving) continue;
    const sign = Math.sign(velocity);
    if (lastSign !== 0 && sign !== lastSign && sample.time - lastMovingTime < options.minDwell) zigzags.push(sample.time);
    lastSign = sign;
    lastMovingTime = sample.time;
  }

  const limit = options.maxSpeed[channel];
  const tooFast = limit !== undefined && peakSpeed > limit;
  const status = kinkTimes.length === 0 && zigzags.length === 0 && !tooFast ? 'PASS' : 'FAIL';
  if (status === 'FAIL') failures++;
  const format = (times) => times.slice(0, 12).map((time) => time.toFixed(2)).join(', ') + (times.length > 12 ? ', ...' : '');
  console.log(`${status} ${channel}: peak speed ${peakSpeed.toPrecision(3)}/s at ${peakTime.toFixed(2)} s, ${kinkTimes.length} kinks, ${zigzags.length} zigzags`);
  if (kinkTimes.length) console.log(`  kinks at ${format(kinkTimes)} s`);
  if (zigzags.length) console.log(`  zigzags at ${format(zigzags)} s`);
  if (tooFast) console.log(`  peak speed is over the limit of ${limit}/s`);
}

if (failures) {
  console.log('\nFix the root cause, never loosen this check:');
  console.log('- Kinks: interpolate keys with a C1 spline (monotone cubic Hermite, Fritsch-Carlson), never linear or a per-segment ease mixed with linear.');
  console.log('- Zigzags: remove keys that turn a channel back within a short time. One direction per move, then settle.');
  console.log('- Zoom width is keyed in log space, so its speed in decades per second stays smooth.');
  console.log('- Too fast a pan while zooming out: keep the target on the subject as it moves (follow the part), instead of panning to a fixed end point.');
  process.exit(1);
}
console.log('\nPASS: camera speed is continuous and no channel zigzags.');
