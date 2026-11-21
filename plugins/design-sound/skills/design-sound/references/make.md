# Sounds made by code (make.py, resynth.py, designs.py)

Reading map: Why, The learned model, Controls, Designs, Checks, Placing a take, Measured, Limits.

## Why

A generation model (ElevenLabs, picture foley) can sound good, but each call gives a different sound and nothing in
it can be turned. A sound made by code is the same every time for the same seed and controls, a new take for a new
seed, and every part of it has a knob. So code is the default and the generators run only when the owner names them.

- sounds invented from formulas for real things (footsteps, punches, explosions, doors, switches) failed;
- designed gestures (risers, UI figures, chip sounds) passed.

## The learned model (resynth.py)

`make.py learn <recording> --name family/id` stores numbers, never samples, in `<library>/models/family/id.npz`:

- 56 bands from 40 Hz to 20 kHz on the ERB scale. Their half-cosine windows square-sum to one.
- Every band's level on a 0.25 ms grid, so onsets keep their speed and tails keep their grain.
- Every 2 ms, the share of each band that is one steady tone, and that tone's offset from the band centre.
- The coherence of the two channels in each band.

A render draws fresh band noise, with its own envelope divided out, and a phase-continuous oscillator for the tonal
share, and puts the model's envelope on them. It then measures the take's bands and corrects them toward the model
in one pass. Last, it clamps the 30 ms before each onset so the take never stands above the recording there. Band
filters ring before a strike, and a soft attack is the failure that made our SFX weak.

Learn a single event of one kind per model: cut it with `--from` and `--to`. A model keeps the recording's source,
licence and author. Takes from one model with different seeds count as different recordings for the house rule
against reusing one sound.

## Controls

| control | range | what it does |
|---|---|---|
| `--seed` | any | a new take; the same seed always gives the same samples |
| `--size` | 0.6-1.6 | a bigger thing: every frequency divided and every duration multiplied by it |
| `--pitch` | semitones | lower or higher, same length |
| `--length` | 0.6-1.8 | time between onsets stretched; onsets stay as sharp |
| `--bright` | -1..1 | tilt of 3 dB per octave around 1 kHz |
| `--hard` | -1..1 | onsets up to 6 dB louder and brighter, or softer and duller |
| `--ring` | 0.5-2 | decay time of every band after its peak |
| `--weight` | -1..1 | level under 150 Hz, 6 dB per unit |
| `--energy` | -1..1 | level ±6 dB with a harder, brighter strike |
| `--vary` | 0-1 | small random amounts of all of them, for a run of the same action |

A run of the same action (footsteps, pops, boxes) uses one model with `--n` and `--vary 0.3`, pitch stepping up one
semitone per item when the run builds.

## Designs (designs.py)

For gestures no recording holds; each is seeded:

- `riser` ends on its cut;
- `subdrop` is a sine glide with soft drive, so phones hear its harmonics;
- `whoosh` is band noise whose centre rises to the peak and falls, panned across;
- `blip` is a UI pop with a pitch step and a click;
- `tick` is a short band-passed burst.

Options are `--name value` pairs (see the module's header). A whoosh for a real object passing (a car, a sword) is

## Sources to learn from

A model can only sound as good as its recording. MP3 previews and meme files sound cheap, and the owner heard it
(2026-11-21: "cheap, fake"). `learn` refuses a lossy file under 128 kbps, a lossy file whose top end stops under
15 kHz, and clipping above 0.05 % of samples. `--allow-poor-source` overrides it. A WAV that is dark by nature, such
as an explosion or thunder, passes.

`fetch_bigsoundbank.py "<query>" --n 8` downloads full-quality CC0 WAVs (BigSoundBank, Joseph Sardin) into
`<library>/bank/bigsoundbank` with a manifest. `learn --around-peak S` learns only the loudest event: 0.15 s before
it to S seconds after it. Sonniss GDC bundles are free WAVs, but their licence forbids AI/ML training, so ask the
owner before learning from them.

## Layered hits (hit.py)

A hit that reads as one strong event has separate layers. They are a transient (HP 1800 Hz, 40 ms), the body (140 to
6000 Hz) and a tail (HP 300 Hz). Only the 2 or 3 biggest hits of a piece get a sub. Each layer comes from its own
model or design, aligned on its peak. Then `finish()` lifts the hit until its loudest 5 ms sit 3.5 dB under the peak.
It measures only the first 0.6 s and folds the spike with a tanh knee instead of a limiter. A cue sheet takes
`"hit": <spec>` (format in the module header). On three showreel shots, the loudest 50 ms rose 2.3 to 2.5 dB at the
same -14 LUFS.

More roles: `punch` (30 to 250 Hz) for the designed `kick`, `rumble` (under 500 Hz) for the designed `rumble`. A
layer can take `"drive"` (tanh saturation, so low layers reach phone speakers). The mix keeps everything under
150 Hz mono. hit.py prints each layer's share of the energy, the band shares and STACKED when the first 0.5 s holds
two separate attacks.

Match the band shares of a real recording of the same thing before trusting the ear. A real explosion holds about 90 %
of its energy in 80 to 250 Hz (BigSoundBank 1807 and 1808). The first blast build held 88 % under 80 Hz and the owner
heard "only a pulse, no boom" (2026-11-21). The cause was a long kick: `gain_db` sets a layer's peak, but a long low
layer carries far more energy than its peak shows. The per-layer report shows it. The fixed build holds 74 % boom.

A big, aggressive blast (owner asked for "a bigger blast", 2026-11-21) adds four things. Give it a high-passed
crunch copy of the body (900 to 5000 Hz, drive 0.9, -9 dB). Add a second body, the fireball, with `"offset": 0.12`
so it roars up after the flash. Let the tails run to 2.6 s. In the cue sheet, add `"duck_before": {"seconds": 0.09,
"db": -12}` so the bed and effects dip right before the hit. Recipe in `local.md`.
It mixes to sub 22 %, boom 61 %, body 12 %, crack 5 %.

## Physics (physics.py)

A moving or distant source gets its sound from its path. `pass` moves it on a straight line past the listener and
gives Doppler from the travel delay, 1/r level, air low-pass by distance and pan from the angle. The test tone at
30 m/s read 1087 and 913 Hz, against 1096 and 920 Hz from theory. A close fast pass of the designed `air` makes the
whip past the ear by itself. In a cue sheet, `"pass": {"speed", "closest", "at", "direction"}` with `"align": "peak"`
puts the closest point on the event. `"far": <metres>` places a sound at a distance.

Typical paths: past the ear under 1 m at 15 to 40 m/s. A train at 3 to 6 m and 10 to 25 m/s. A jet at 50 to 200 m.

## Every element has a sound

Each element that makes a sound in real life gets a cue on its first frame. That means a foot on the ground, a
landing, a pass, a burst, and the parts of an event (sparks, dust, smoke, embers, debris flying and landing). Before
writing cues, read every frame of the cut (`watch-video` `perceive.py --fps <film fps>`) through an image-reading
subagent. It returns one line per element: start, end, kind, what, the sound it makes and its prominence (lead,
support, detail). Write that list as `elements.json`. Then give each cue a `"covers": [ids]` list and run
`check_coverage.py elements.json cues.json` until it prints no MISSING.

The owner caught a silent creature step, passes with no whip, and a blast whose sparks, dust and smoke made no sound
(2026-11-21). One blast held 17 elements. The first cue sheet covered 6. Parts of an event take `"detail": true` cues
well under their lead (density.py leaves them out). Sources: `particles/spark-burst`, `spark-crackle`,
`gravel-spray`, `fireworks-crackle` models, and the `crackle` (embers) and `billow` (smoke, dust cloud) designs.

A shot that shows off sound must let the viewer see each event at phone size. The owner dropped a dark creature
shot because it was hard to make out (2026-11-21). Ask the image reader whether each lead element reads at phone size
before choosing the shot. Low-only hits (a kick under a pass) slip past spectral-flux onset checks, so `listen.py` also
finds jumps of 10 dB under 200 Hz. The kick that read 150 ms late now reads 0 ms.

## UI sounds

Many people dislike interface sounds that chirp or sound shrill. Before making UI sounds (clicks, keys, blocks
landing, notifications), ask the owner once what they like: soft or crisp, how loud, and a reference product if they
have one. Then build to that answer. Without an answer, start warm and quiet:
- Low-pass every UI sound under about 3 kHz. Put tick and blip centres at 600 to 1500 Hz, with a soft attack.
- Keep the UI stem well under the content, about 12 dB or more under a playing shot.
- Vary the tone: each kind of event gets its own pitch, and repeats vary a little, so a burst of events sounds like
  a soft patter, never one chirp repeated.

The owner heard the first showreel's timeline landings as "chirpy" and shrill (2026-11-22).

## Density (density.py)

Too many sounds read as a wall, not as design (2026-11-21: "messy, too thick"). `density.py cues.json` flags BUSY (more
than 1 moment per second in a 2 s window), CROWDED (2 strong cues under 0.25 s apart) and PILED (more than 2 cues at
once). Mark a quiet detail `"small": true`. Merge or drop cues until it prints `clean`: one strong moment per beat,
with room around it. The old showreel had 1.6 to 2.3 moments per second, and the rebuilt shots have 0.6 to 0.8.

## Checks

Every `learn` prints the take's distance from the recording against the model's own floor, which is two takes
against each other. Within 1.5 dB of the floor means good; above it, listen before using it. It also prints the rise
time of the take and of the recording.

Every `render` audits the take: DC, a cut tail, non-finite samples, and an attack more than twice as slow as the
recording's. A take that fails is rendered again on seed + 101, + 202 and + 303.

Ear checks stay the owner's call. The first blind A/B against the recordings (tick, punch, whoosh, blast) is listed in `local.md`.

## Placing a take

`render` prints `onset_s` and `peak_s`. To put the loudest moment on the event at t, start the file at t minus
`peak_s`. In a cue sheet (the showreel's `compose_sound.py`), a cue can take `"make": "family/id"` with `"seed"` and
`"controls"`, `"hit": <spec>`, or `"design": "riser"` with `"options"`, in place of `"file"`. Alignment, band limits, gate and pan
apply the same way.

## Measured

These were measured on 2026-11-21 on one CPU core. "Take" and "floor" are env_db in dB; rise is the 10-90 % rise.

| sound | take | floor | rise take / recording | analyse | render |
|---|---|---|---|---|---|
| small bell tick | 3.5 | 3.7 | 0.75 / 1.0 ms | 0.4 s | 0.2 s |
| body punch | 5.4 | 6.5 | 1.0 / 2.0 ms | 0.2 s | 0.3 s |
| fast whoosh | 7.0 | 7.6 | 1.5 / 1.25 ms | 1.5 s | 3.1 s |
| explosion, 3 s | 4.6 | 4.5 | 1.25 / 1.25 ms | 1.5 s | 3.8 s |

The spectral centroid of each take stays within 6 % of its recording's. Models take 0.2 to 1.4 MB.

## Limits

- A render costs about 500 band FFTs of the whole take: 1.5 s for a 1 s whoosh, 4 s for a 3 s blast. Learn only the
  span a cue keeps (`pre` + `length` + 1 s), not whole files.
- Models of long or dense sounds are large, about 450 kB per second. They are kept in the library, not in a skill.
- `--ring` above 1 extends a model by at most a quarter of its length. A very long ring cuts at the end.
- No learned beds or loops yet: for ambience, learn a 2 to 4 s cut and place takes back to back with crossfades.
- No model of a class (new sounds sampled between several recordings) yet.
- The measures are not ears: send the owner an A/B before a new kind of sound goes into a film.
