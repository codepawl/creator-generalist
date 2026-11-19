# Cinematic and trailer sound (loud, dense, re-scoring a reference)

<!-- skill-navigation:start -->
## Reading map

- [Cinematic and trailer sound (loud, dense, re-scoring a reference)](#cinematic-and-trailer-sound-loud-dense-re-scoring-a-reference)
- [When this applies](#when-this-applies)
- [Loop: measure against the reference every round](#loop-measure-against-the-reference-every-round)
- [Explosions and guns: thin versus heavy](#explosions-and-guns-thin-versus-heavy)
- [Tails, cuts and silences](#tails-cuts-and-silences)
- [Punch: make the hit jump, do not just make it loud](#punch-make-the-hit-jump-do-not-just-make-it-loud)
- [Reference match](#reference-match)
- [Music for a trailer](#music-for-a-trailer)
- [Owner notes from the Godzilla re-score (2026-11-19)](#owner-notes-from-the-godzilla-re-score-2026-11-19)
<!-- skill-navigation:end -->

Learned on a full re-score of an 84 s monster-film trailer: 14 rounds of owner notes, every round measured against the
original mix. Numbers are from that project; treat them as starting points.

## When this applies

A trailer, action scene, monster or war film, or any re-score of an existing cut where the original mix exists. Here
the gentle-top and no-reverb house rules give way to the brief: the owner asked for loud, dense and cinematic
(their note on round 9: the effects were "still too tame"). A project's own rule still wins.

## Loop: measure against the reference every round

1. Split the reference into dialogue and the rest (demucs `htdemucs`, `--two-stems vocals`). Keep both.
2. Every render, run `scripts/reference_gap.py ours.wav reference.wav --hits <times>`. It prints band shares over the
   whole piece (<60, 60-250, 250-2k, 2k-8k, 8k+) and, per hit, the peak and the jump over the 0.5 s before.
3. Fix what the numbers and the owner's words agree on; when they disagree, the owner's words win and the numbers
   tell you where to look.
4. Send a short A/B (reference, then ours, 3-5 s windows around each note) along with the full preview. Use
   `afade` on each window and burn in a label. Music-only questions get audio files, not video (the owner asked for
   "just the music, no video").
5. Say plainly that nobody listened; every claim in the report is measured or guessed.

## Explosions and guns: thin versus heavy

Two opposite failures, one after the other:
- **Too tame:** v8 had 4 % of its energy at 2-8 kHz against the original's 8.8 % (26 % under 60 Hz against 17 %). A
  subby boom with no crack reads as soft.
- **Too thin and harsh ("flat", "the explosion does not sound real"):** after a bright 1.5-9 kHz crack layer was added, the hit was
  a crack with nothing behind it.

What worked is layers, each from a different real recording:
1. Body, 80-400 Hz (up to 2 kHz), from a real blast, low-passed, with a 5-15 ms attack.
2. Crack, under 60 ms, mostly 1.5-5 kHz with a gentle tilt above.
3. Debris and rubble, plus glass and metal settling, over the 1-4 s after the hit.
4. A rolling rumble, thunder-like, for 2-5 s.
5. Sweeteners: a short air push or suck before the hit; fire roar after a fire blast.
6. Glue: gentle saturation plus parallel compression on the sum.

Aircraft and engines: one recording reads as a toy. Layer the real flyby with Doppler, a detuned second engine,
low body, mid rasp and air buffet, then saturate (owner: "the noisier the better, layer many layers").

Check every designed hit: its loudest point must be the hit itself. An echo layer at +4 dB moved one gun's peak to
0.745 s, so placing by "loudest point" would have fired it 0.75 s before the muzzle flash. Flag any recipe whose
returned lead is more than 0.15 s after its onset. Swells and whooshes are the exception, since their peak is meant
to come late.

Distance delay (light before sound) reads as lag past about 0.1 s in a trailer; cap it there.

## Tails, cuts and silences

- A black card or fade is not a reason to cut sound. Only a real silence in the reference is. Tails ring through
  black cards and over smash cuts, then fade (about 0.45 s for big ones). Owner: "a black frame does not mean cut the effects".
- A bed that belongs to the scene (crowd screams, fire, city) keeps running under an explosion and into the next
  black. It never ducks for a hit (owner: "the screaming is still going during the explosion, why did you drop it?").
- When the shot cuts mid-action, the sound runs a little past the cut; do not stop it on the frame.

## Punch: make the hit jump, do not just make it loud

The original's big hits peaked at the same level as ours or lower. Ours felt weaker because of what came just before
them. So measure the jump: the hit's peak over the 0.5 s before it.
- A pre-hit dip (both music and score layers drop 6-18 dB for 0.25-0.5 s, closing as the hit lands) restores the jump.
- Dip only where the reference also dips. Measure the reference's level inside the window against the level before
  it. The original rose 4.6 dB before one fireball; dipping there was wrong.
- Never dip ambience beds. Give sound-effect tails at most about 4 dB, so they duck instead of stopping.
- Apply the dip after any reference match, or the match's loudness contour will fill it back in.
- The bus compressor was gentle (1.3:1). Overlapping tails and the contour flattened the jumps more than compression did.

## Reference match

A match EQ plus fader ride against the reference with dialogue removed: one static gain per band, clamped ±8 dB, and
a 0.4 s loudness contour smoothed over 0.2 s, clamped ±12 dB at 0.8 strength. It took the band shares to within
2 points of the original. Apply the same gains to every bus so their balance holds. Using the original as a mix
reference is fine for study; before publishing, it is a decision for the owner.

## Music for a trailer

- A score built note by note from one-shot samples sounded boring and like a MIDI demo, even after it was re-chorded
  to match the original's harmony (chroma similarity 0.85 to 0.92). The owner still called it "boring" and "pretty bad". Chord
  similarity is the wrong target.
- Measure what makes it move: onsets per second, loudness movement and spectral centroid per section. Ours had 0.1-0.4
  onsets/s where the original had 2.4-3.2, and a centroid near 1300 Hz against 2000-3000 Hz.
- Better paths, in order: a produced track or stems edited to the cut (bars, downbeats on hits, dead stops at the
  rests, at most ±2 semitones); then a score whose lead is strings plus drums, with hybrid trailer FX (braams, risers
  into hits, sub drops, ticking pulses, whooshes on cuts, taiko grooves).
- The owner disliked pipe organ in a trailer ("the church instrument sounds weird"). Violins and drums lead.
- Free produced sources that downloaded without a sign-in, all CC BY 4.0 and needing a credit: Scott Buckley,
  Kevin MacLeod (incompetech) and Gregor Quendel's cinematic trailer collection. Free multitrack stems are rare;
  the polypix itch.io pack has 17 instrument tracks but is a 517 MB download.

## Owner notes from the Godzilla re-score (2026-11-19)

- "still too tame": match the reference's crack and level, using real impact recordings.
- "the explosion is flat, make it heavier, add layers": thin and harsh. Add body, debris and rumble; shorten the crack.
- "the planes are far too light, the noisier the better": layer the engines and push them up.
- "the gun sound comes late": cap the distance delay at about 0.1 s.
- "cutting at 0:50 like that is fine": a hard stop works only where the picture truly goes silent.
