# Foley (foley.py)

<!-- skill-navigation:start -->
## Reading map

- [Foley (foley.py)](#foley-foleypy)
- [Event format](#event-format)
- [How an event becomes layers](#how-an-event-becomes-layers)
- [Query words](#query-words)
- [Size and distance maths](#size-and-distance-maths)
- [Alignment](#alignment)
- [Report](#report)
- [What the owner rejected (carry into every render)](#what-the-owner-rejected-carry-into-every-render)
- [Memes](#memes)
- [Limits](#limits)
<!-- skill-navigation:end -->

`PY foley.py events.json --out foley.wav [--report foley-report.csv] [--seconds N] [--seed 7] [--licence public]`
`PY` = the pass-1 run line (numpy scipy librosa soundfile pyloudnorm psutil torch transformers). Output is a stereo 48 kHz
24-bit stem; nothing is written next to the source recordings.

## Event format

`{t, what, material, other_material?, mass_kg?, speed_mps?, x?, distance_m?, intensity?, seed?, duration_s?, query?,
label?}` in a list or under `"events"`. `t` seconds of the visible event (from the sim or timeline, not guessed). `what`:
`drop`, `impact`, `slam`, `break`, `footstep`, `roll`, `scrape` or any verb (it goes into the query). `x` -1 left to 1
right, the event's screen position, clamped to ±0.75; an impact's body and tail sit at half of it, its transient at
the full position (`references/mix.md`, Evidence). `intensity` 0 to 1 (default 0.6). `duration_s` for rolls and scrapes. `query`
replaces the body query when the generated one finds the wrong thing. `label` is only read by mix.py, to name the cue for
the listen check. `files` (a list of paths) pins the body to those recordings, one whole file per event, rotated: use it for a
hand-picked set such as a game's variants of one action (the Minecraft pack, `sound-library/minecraft`, mapped from its
`sounds.json` event names). It skips search, so foley.py prints no licence warning for them: report it yourself.

## How an event becomes layers

Like a foley artist: a snap, a weight, then what falls after.

| Layer | What it is | Rules |
|---|---|---|
| transient | first 0.2 s of a sharp one-shot, high-passed at 300 Hz | the click that carries the sync |
| body | the main sound, up to 2.5 s (rolls: `duration_s`) | -3 dB under the transient |
| tail | debris, rattle, shards; starts 25 ms or more after the hit | -8 dB; later and softer with distance |

Count follows intensity: under 0.3 body only; under 0.65 transient + body; above that + tail. Breaks always get all
three. Slams never get a tail (nothing scatters). Footsteps are one body layer, plus a tail above 0.6. Rolls, scrapes
and slides are one long layer aligned on their first sound.

Every layer is a different recording, and none repeats in one render: each query is ranked with the pass-1 search
(duplicates collapsed), recordings whose tags carry the material word come first, the rest follow only when they score at
least 60% of the best. The best unused one is taken; repeated hits (footsteps, knocks) are cut out of their long
recording at detected onsets and one of the best three unused hits is taken. When the pool runs out the recording is
reused and the report says `reused, pitch varied` (pitch moves 1 to 2.5 semitones); there is no start-offset trick, since
cutting into a transient would break the sync.

## Query words

Built from `what` and the materials: `drop` -> "wood dropped on concrete"; `impact` -> "metal on concrete impact";
`break` -> "glass breaking"; `slam` -> "door slam"; `footstep` -> "footstep on gravel"; `roll` -> "metal pipe rolling".
Transient adds "sharp hit", tail adds "debris rattle settling" (breaks: "shards falling debris"). Use plain nouns the
library tags carry (wood, metal, glass, concrete, gravel, door, brick). Check what a query finds with `search.py` first
and pass `query` when the generated one misses.

## Size and distance maths

- Mass: pitch `-1 semitone per doubling` of mass relative to what the recording usually carries (footstep 70 kg, slam
  30, drop 5, break 0.5, others 2), clamped to +-6; low-pass `14 kHz x (mass/typical)^-0.15`, 3 to 16 kHz.
- Intensity: gain `-20 + 16 x intensity` dB (peak-normalised layers); speed adds `3 dB x log2(speed/2 m/s)`, +-6 dB.
- Distance: `-3.5 dB per doubling beyond 2 m`, capped at -18 dB; low-pass `16 kHz / (1 + d/6)` down to 1.8 kHz; tail
  delayed `25 ms + 6 ms per metre` (max 275 ms) and 3 dB softer at 50 m. No reverb.
- Soft top: every layer is low-passed at 8 kHz (house rule, gentle top). Pan: constant power from `x`.
- Each event gets seeded jitter (+-0.4 semitone, +-1 dB) from `seed` (default: its index), so repeats differ and a
  render is reproducible.

## Alignment

Each layer is aligned on its loudest attack (rolls: first sound at 10% of peak) after cutting everything more than 15 ms
before it, then placed so that attack lands on `t` (the tail on `t + delay`). The report measures the first point of the
event's own mix at -20 dB of its peak against `t`. Typical: 0 to -15 ms (early, never late). `listen.py` measures
again on the stem with librosa and can disagree by tens of ms on crunchy sounds (gravel steps have a faint pre-click);
sync is judged on frames in the picture, so under 42 ms either way is fine and a bigger gap is worth a look at the sheet.

## Report

One CSV row per event: `index, t, what, material, layers` (per layer: file, pitch shift, low-pass, gain; or
`NO CANDIDATE`), `onset_error_ms`, `flag` (CHECK when over 42 ms or no layer). The script also prints the rows.

## What the owner rejected (carry into every render)

- Reverb, and synthesised stand-ins when a recording exists; no drones or tones by default.
- Felt piano and marimba "answers" on cues (they read as eerie): answer an event with an object sound.
- One merged sound for several actions, a shared recording between two cues, filler sounds no action makes.
- A hit that plays before its frame; shrill 2 to 6 kHz build-up (the owner wants the gentle ASMR feel).
- Knocks, taps, clicks, glass or bell hits on UI and diagram cues in explainers (2026-11-07, agent-memory film:
  they sounded like tapping a glass): cues there are soft air, paper, pen or footstep sounds, and
  an element appearing needs no sound of its own.
- UI cues that are dense, all in one tone, or hissy (2026-11-22, a release reel: the owner found the SFX too noisy
  and all in one tone). Dense means a tick per typed letter or a counter ticking every 2 frames; hissy means recorded clicks and noisy
  whooshes. Keep cues sparse and under the music, rotate takes at different pitches, and let a run of cues (switches,
  a counter) climb the track's scale.
- UI takes that double, thump or drag (2026-11-22, a UI listening reel). A clock tick learned with its second strike
  sounded like 4 sounds in a run. A dark tilt on a bright key press moved 83 % of its energy under 300 Hz, so it
  sounded like a gunshot. A 443 ms swish was too long for an arrow. Check each take has one onset, high-pass dark
  takes of bright sources at about 220 Hz, and keep UI transitions under about 100 ms, or use short OS-style ones.

## Memes

A meme sound is a quote, so it is used as the original file. Change only its pitch or speed when placing it, and
never learn it into a model or render a new take of it.

The hard part is knowing when a meme fits. `memes.py` covers that in two steps:

- `build <folders> [--audit audit.json]` writes `<library>/memes.json`. Each entry holds the file, its audible length,
  the time of its peak and the moments it fits. The moments come from whole words in the file name (`TAG_RULES`).
  `memes-overrides.json` in the library replaces the tags of one file. Duplicates are skipped when they share a name,
  and also when an audit marks them.
- `detect words.json [--events events.json] --out cues.json` reads a word-timed transcript (the watch-video
  `words.json`) and an optional event list (`t`, `kind`: hit, fall, fail, win, reveal, throw, start, end). It finds:
  - trigger words, such as "broke" for fail, "worked" for win, "why" for confused, "cost" for money and "hours later"
    for later;
  - a pause of 1.6 s or more after a line (awkward);
  - an exclamation followed by a pause (punchline);
  - events.

  It picks one meme per moment and never uses the same file twice. A meme goes at the end of the phrase, in the
  pause. When the next word starts first, the cue fades at that word (`fade_at`). A hit puts its peak on the event,
  14 dB down if someone is speaking. A drum roll ends on the reveal, and a censor beep covers the word. When one
  phrase has two triggers, the later one wins, so "actually worked" is a win and not a shock. The defaults are 6 s
  between memes and 4 a minute.

Every cue gives its reason (`why`), and the cut decides whether to keep it. A project rule against memes always wins.
On a scripted test of 10 known moments, detect placed 8. The other 2 were dropped by the
gap rule. A 1,500-word tech talk got 1 cue, which is the right density for talk without jokes. Meme files have no
licence (`unknown`), so give the licence warning once.

## Limits

- The library is small (456 files): a wooden crate on concrete comes back as "metal drop on wood", a pipe rolling as a
  metal scrape. Read the sheet, fetch a licensed recording (`index.py --add`) when the pick is wrong.
- The demo's seven gravel steps used five hits cut from the one gravel recording; the other two came from the nearest
  material (rubble). A long walk needs more recordings (`index.py --add`) or accepts flagged reuse.
- CLAP cannot judge far, low-passed or short sounds well; label ranks are hints.
- A niche library pick goes wrong without a matching recording: for the roach film (2026-10-30) a per-event search put a radiation burst under palp taps, a flashlight under keystrokes and pigeons under a wing buzz. When the action set is known, give each action a fixed recording list instead and generate the missing sounds first.
  The roach film's list, as a pattern (action: recording, gain dB, low-pass Hz, mode): footfall: insect legs on tile plus fast
  scurry, -27, 7000, hits; leg landing: legs on tile, -29, 7000, hits; palp tap: two soft woodblock clicks, -33, 6000, hits;
  antenna flick: one loud woodblock click, -34, 6000, hits; groom scrub: fast scurry, -31, 6000, hits; wing cover opening:
  -16, 8000, whole; wings unfolding: paper rustle, -20, 7000, whole; takeoff: roach wing buzz, -14, 5500, loop; squeeze into a
  crevice: shell scrape, -14, 8000, whole; head detach: wood snap, -20, 7000, whole; head land: -15, 8000, whole; radiation
  pulse: -9, 8000, whole; flip: insect clatter, -14, 8000, whole; flashlight: click, -13, 8000, whole; light off: switch click,
  -13, 8000, whole; swarm: swarm bed, -14, 5000, loop; typing key: slow keyboard typing plus a plain keyboard, -24, 7000, hits;
  return key: single key press, -19, 7000, whole. Modes: "hits" cuts single hits from the recording at detected onsets (librosa
  onset detection), rotates through them and shifts each repeat by a pitch step in semitones (0, 0.7, -0.6, 1.2, -1.1, 0.3,
  -0.3) so neighbours differ; "whole" plays the full recording from its attack; "loop" repeats it with crossfades for the
  event's duration. Every sound is placed so its attack lands on the event time; the stem is stereo 48 kHz.

Rejected on a landing (2026-10-30: too shrill, and it ended before the landing did): a sound must last as long as
the action, so a rollout keeps its rumble until the plane stops; a short clip cut off mid-action reads as a mistake. Peak-normalised
beeps get a negative gain: +14 dB on one gave a +46 dB margin, which the margin check passed and the ear did not.
