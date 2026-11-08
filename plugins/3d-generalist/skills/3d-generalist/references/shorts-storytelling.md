# High-Retention 3D Shorts Storytelling (`shorts-storytelling.md`)

`@BarelyInvented`).

## 1. Premise selection (what gets 20M vs what flops at 20k)

- **Start from a mess or everyday thing everyone knows, end on a basic human need:**
  - *Hits (1M to 20M views):* Muddy Puddle -> Village Well, Snow -> Igloo, Hole in the Ground -> Bunker / Skyscraper,
    Box on a Rope -> Elevator, Staircase -> Escalator, Porta-Potty in a Storm.
  - *Flops (16k to 54k views):* Retractable Stadium Pitch, Airplane Door, Wood Block -> Car Brakes, Seabed Trench.
- **Literal transformation:** the starting object or mess must literally become the finished structure step by step in the
  same set. When a small object inspires a big one (a paper pinwheel -> windmill sails), say the link explicitly in the
  voice (*"you take the pinwheel's idea and build a bigger one"*) and build the transition across 2 to 3 beats—never
  drop the whole finished building onto the ground in one sentence.
- **Consistency wins:** keep one visual format, one recurring character, one steady camera style and a regular cadence.

## 2. The 60-second script recipe (~230 words at 3.4 to 3.6 words/s)

Write `script.md` as a beat table (`| id | role (hook/hold/close) | narration | picture |`) before touching 3D code:

1. **Second 0 Hook (0 to 3 s):** open on the naive first build or immediate danger in one sentence while the picture is
   already moving. No intro, no title card. Example: *"If you dig a hole and put a roof over it, you have a bunker."*
2. **5 to 7 rounds of `"But <real failure>. So <one fix>."` (~7 to 9 s per round):**
   - Show the physical failure first (2 to 4 s: it floods, collapses, fills with smoke, tips over).
   - Build the fix piece by piece in place (4 to 6 s) as a real builder would (if well water is contaminated by dung,
     dig a new well uphill rather than patching polluted water).
3. **Weave technical terms into the sentence:** say *"You build a **cold trap** to..."* or *"You need a **gooseneck**..."*.
   Never say *"This is a <term>"* (sounds childish). Teach **one named part per round**, with at most 1 or 2 plausible,
   sourced numbers in the voice (viewers fact-check weights and sizes in the comments).
4. **One real-life `"that is why"` fact:** connect a part to something viewers see every week (*"that is why pipes in
   fields are bent like candy canes"*).
5. **The Flip:** late in the build, a problem turns out to be the fix (melting inside walls refreeze into an airtight
   ice shell; blast pressure pushes the bunker door tighter; trapped air pockets in snow insulate the dome). When the
   twist is about something tiny (trapped air pockets), fill the visible face with glowing pockets popping in one by one.
6. **Final stress test:** throw a storm, 3-day blizzard, depth pressure or drought at the finished build and show it
   working while the character stays safe and comfortable inside.
7. **Closer + Meme Dance Outro (under 3 s):**
   - Close with a clean result + payoff line (*"Put it all together, and you have a <thing>."*), followed by a short ask
     (*"Like and subscribe to see what we build next"*).
   - Pop in 3D/2D Like & Subscribe buttons while the character performs a celebration meme dance (such as Gangnam Style)
     with its instrumental riff playing quietly (-2 dB under the main music, panned and low-passed to the character's
     position on screen while the main music keeps playing).

## 3. On-screen UI, 3D labels, captions and sound

- **3D leader-line part chips only:** when the voice names a technical part (`ADOBE`, `COLD TRAP`, `U-BEND`), extend a
  3D leader line from the object to a small label panel sitting next to it in 3D space:
  - *Primary / next part:* solid line, dark strong colour.
  - *Secondary / previous part:* dashed line, light colour.
  - Fade and shrink the leader line back into the dot **1.5 to 2 s after the word** is spoken.
  - **No number chips, date chips, place chips or final-object chips:** never float `"62 BC"`, `"2 M"` or `"IGLOO"`
    cards on screen; let the voice and captions carry numbers and plain words.
- **Side gauges only when a changing number is the point:** bring a temperature or depth bar in with motion only for the
  beat where the mercury or level climbs into the red/yellow striped danger zone, then animate it out.
- **One-word centred captions (`~80 px` at `1080` width, `9 px` stroke):** display one word at a time at `Y = 1010`,
  synced within **±0.05 s** of the spoken word start (verified by ASR transcription against `timing.json`).
- **Sound carries 50% of realism:** no silence over `0.3 s` in the voice (`trim_tail` cuts beat tails 0.12 s after the
  last sound above -40 dB). Layer soft, real foley cues (stone set, gravel dig, water splash, wood knock, wind gust,
  fire crackle) for every visible action, mixed at **-14 LUFS / -1 dBTP** with music 10 dB under the voice. Drop
  continuous sandy footsteps that sound like white-noise hiss.
- **Repeated sounds vary:** a run of the same action (blocks set, pegs tapped, salt thrown) gets soft short pops that
  change pitch and level a little each time. One loud sample repeated sounds like a machine.
- **Show what the camera cannot see:** a smell, heat or cold is a problem the viewer cannot see. Show it with a soft
  visual (faint green wisps and a few flies for rot, shimmer for heat, breath fog and frost for cold) and the
  character's reaction (pinches the nose, wipes the brow, rubs the arms).
- **No dead air in the picture either:** a Short never holds a still, empty frame. If the voice pauses, something on
  screen still moves: the character works, reacts or walks, or the camera moves.
