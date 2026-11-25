# Character Acting, Motion and Physics (`acting-and-motion.md`)

Technical accuracy (no floating, no foot sliding) is only half of non-slop 3D animation. The other half is **acting,
anticipation and staggered timing** so the character never moves like a linear robot.

<!-- skill-navigation:start -->
[Character Acting, Motion and Physics (`acting-and-motion.md`)](#character-acting-motion-and-physics-acting-and-motionmd): read only the section for the step in front of you, whole:
- [1. Anti-stiffness and comedic / reaction acting](#1-anti-stiffness-and-comedic--reaction-acting)
- [2. Grounded feet, walks, steps and turns](#2-grounded-feet-walks-steps-and-turns)
- [3. Hands, tools, props and baked physics](#3-hands-tools-props-and-baked-physics)
- [4. Where the worker stands and what his hands do](#4-where-the-worker-stands-and-what-his-hands-do)
<!-- skill-navigation:end -->

## 1. Anti-stiffness and comedic / reaction acting

From our study of 19M to 20M view 3D Shorts:

- **Never freeze all joints on the same frame:** when blocking pose-to-pose or blending clips, offset the head, torso
  and arms by **3 to 6 frames**. If the character stops walking or finishes sitting down, let the head turn 4 frames
  early and let one hand settle a few frames after the hips.
- **Lead every notice or turn with the head (`looks`):** when a problem starts (water leaks in, wind hits, smoke fills
  the cave), whip the character's head toward the problem **4 to 6 frames before** the body turns or steps back.
- **Reaction and slapstick beats on `"But <failure>"` rounds:**
  - Never transition linearly from calm work to a failure state.
  - Insert a **0.2 to 0.5 s anticipation/reaction beat**: a sudden flinch, catching balance (`"Whoa"`), or a 4-frame
    upward head look right before falling or getting knocked over.
  - When a fall or gag happens (falling through a roof into a hearth, or tipping with a cabin), exaggerate the landing
    pose (spread feet, face-plant 3 frames after the structure hits, patting out a singed backside, funny and bloodless)
    followed by a slow recovery where the character props up on one hand and looks left, then right, in confusion.
- **React to danger like a real person:** when a flood, rockfall or collapse comes, the character gets out of the way
  first (runs or walks to the bank/ledge) and watches the failure from safety.

## 2. Grounded feet, walks, steps and turns

- **Walk speed matches stride:** time every walk by `distance / stride_speed` (keep normal walks under **1.8 m/s**, and
  loaded cart pushes near **1.4 m/s** with `Push` upper body layered on `Walk` legs). Faster walks slide the toes.
- **Stop with feet together (`arrive: "together"`):** a default walk cycle stops mid-stride with the front toe 0.5 m
  ahead of the hips, putting a foot straight through a closed door, hearth or stool. Start the walk at the phase that
  ends on the passing pose so both feet plant together within 15 cm of the hips.
- **Turns over 45 degrees get a pivot beat:** blending a sharp turn directly into the first stride surges the hips and
  skates the planted foot. Give any turn over 45 degrees a **0.35 s stand/pivot beat** on the balls of the feet before
  walking. Round path corners into smooth arcs.
- **Kneel-to-walk and sit-to-walk transitions:** never go straight from `Kneel_Work` into a walk (it drags the toe 7 cm).
  Insert a **0.3 s stand-up idle** (`blend: 0.3`) between kneeling and walking. For seats (`sit_on`), walk up side-on to
  25 to 29 cm ahead of the seat, turn, and sit; keep post-exit turns under 30 degrees so the shin clears the stool.
- **Both feet on their own surface:** on steps, blocks or slopes (ramps 30 degrees or less), place the root on the
  carrying foot's height and use leg IK to lift the other foot and knee onto its own surface so neither foot hangs in
  mid-air over an edge. Make standing blocks at least `0.8 m x 0.56 m`.
- **Walk starts keep the hips up:** blending from an idle into a walk can dip the hips for a few frames (one case dropped a
  1.8 m character's hips to 0.48 m). Outside kneel, sit and crouch beats, hips stay above about **0.65 m** for a 1.8 m
  character, and a check fails any frame below it.

## 3. Hands, tools, props and baked physics

- **Work at arm's length (under 15 cm):** kneel right at the fire ring with hands in the kindling; stand beside a crank
  with the shoulder level with its axle (never behind it where the far half of the turn is 0.8 m away).
- **Fit the worker to the machine, never the machine to his reach:** keep chains, levers and spouts where the real
  machine puts them, and walk the character to them.
- **Both hands have a job:** a one-handed pour or interact clip often leaves the free arm sticking straight out
  sideways. Put a second grip point on the load (for example palm up under the bucket base) so both arms read naturally.
- **Every piece travels from the hands:** stones, blocks, roof timbers, furs and lamps start in the character's hands
  and travel to their seat. When building many pieces, speed the sequence up as a **time-lapse** (`fit: "timelapse"`),
  but still carry and set each piece by hand.
- **Deterministic baked physics (`f(t)`):** loose planks, falling stones, carts and drifting timber move by real rigid-body
  physics (Jolt in JS, which beat Rapier side by side, or Rigid Body in Blender), baked to keyframes ahead of capture so
  any frame `t` renders identically in any order. Jolt: step 1/120, convex radius 5 mm, masses set explicitly. A Jolt
  cylinder for a log, pipe or barrel lying on another sinks up to 55 mm into it, so build those as 12-sided convex prisms.
  A chain or rope with a heavy end stretches (1.4 m to 2.15 m under an 11 kg bucket): keyframe it instead.
- **Grip mechanics live in one place:** for pick-up and put-down without a pop, dynamic parenting, two-handed props, heavy
  lifts and finger posing, read `rig-characters` `references/props-grip-and-contact.md`.
- **Hand to face needs its own elbow:** a default arm IK pole points the elbow down and back, which is right for
  handles and loads but lays the forearm across the chest when the hand goes to the nose, mouth or brow. For any
  grip at face height, aim the elbow pole **low and forward** (about 0.3 m down and 0.4 m ahead of the elbow) and
  keep the forearm midpoint at least **3 cm** off the chest.
- **Pick the finger shape for the action:** fist for handles and ropes, **pinch** to hold the nose (index curled,
  thumb folded in to meet it within about 2 cm, other fingers relaxed), **flat palm** with fingers together to cover
  mouth and nose. A fist on the face reads as a punch, an open relaxed hand reads as a wave.
- **Bend the knees to reach low:** to set something on the floor or a low course, the character squats or kneels
  with a straight back. Folding in half at the waist with straight legs looks wrong at once.
- **Tools face the worker:** an oven mouth, a hatch, a tap or a crank faces the side the character works from, not
  the camera. If the camera needs to see it, move the camera, never turn the tool.
- **Loose objects come to rest:** a dropped bag, plank or stone settles within about a second and then stays still.
  Damp spin and sliding (angular and linear damping, a sleep threshold) and check the last frames of each bake for
  leftover rotation. An object that keeps spinning on the floor reads as a bug.

## 4. Where the worker stands and what his hands do

- **Never teleport:** he walks every move through a real opening (a door, tunnel or ramp), stooping where it is low. A camera
  framing that hides him does not excuse a jump. Time a walk by its length at a steady pace, never by pinning its last key
  to a word: after the voice was trimmed a word-anchored key jumped him 0.9 m. A clip change is a jump too: blend over 0.25 s.
- **He works where the piece goes and stays where the work put him:** a block going in high is reached standing at it, facing
  and looking up at it; never stand below pointing at a lower part while the piece lands elsewhere. After a step that ends
  with him inside, later steps happen from inside. A quiet moment gets a small playful action, never a jump to a new spot.
  He never stands in front of the thing being built, and he keeps his size everywhere (a stair climb puts a foot on each step).
- **Sit on something real:** a stool, stone or log, never air; in a boat or vehicle the hips sit low in the hollow with legs
  inside. Hold tools with elbows down by the body and both hands on a paddle or oar; a handle held seated sits beside or
  ahead of the hip, never behind the seat.
- **A prop moves only in his hand:** grip first, carry in hand mode, ease the last few cm into the fingers. No arc that flies a
  prop on its own. Thrown particles leave from the hand at each grain's release time. A kneeling worker reaches down to about
  0.2 m, so small things he takes from a kneel sit on a low stump or crate. Both palms stay within about 3 cm of a rolled,
  pushed or lifted thing on every frame; a heavy item such as a pot is held with both flat palms on its widest band.
- **The free hand hangs loose at his side** (a body-frame grip about 0.25 m out and 0.86 m up) instead of curling into the belly.
  Take a thing off a shoulder or out of a pocket with the hand on that side; the opposite hand puts the forearm into the chest.
- **Carts and loads:** he holds the handle or tongue at hand height and the cart goes the way it is built to go. Time his
  walk from the distance moved (never slide a `Push` clip that steps in place) and keep a loaded cart near 1.4 m/s.
- **Bent over low work, his head bows with him** and `looks` aim at his hands; a head turned up out of the bend to face the
  camera reads as creepy. A gesture at the face is filmed from the front, or his head hides the hand.
- **Cloth and loose gear never parks on his body as a stain:** a carried cloth goes in a pocket or over a bucket rim, never on
  his back or sunk in the bucket. A cloth wrapped over fruit covers each piece with a margin and is flat again once lifted.
- **Foot planting rules for a baked walk:** a foot on the ground holds position and direction (heel, then ball when the
  heel lifts); if a clip drags a foot over 12 cm or turns it over 20 degrees, that foot steps to the new spot in 0.3 s, one
  foot at a time. A step lifts before it moves and lands straight down. A turn over about 148 degrees needs about 0.5 s
  before the walk or the first strides go backwards. Walk legs under 12 cm are path corners: stop and turn instead. Do not end
  a walk on a leg under about 1.8 m, and spots stand outside rings and crates by the clip's own step (about 0.4 m for Interact).
- **Smooth the bend:** pick a stoop per frame only with a smoothing window (about 6 frames), or a turn or target switch drops
  the head 22 cm in one frame. Two grips on one hand never overlap in time; bridge into the next grip over at least 0.25 s.
- **Fast pace by blocking, not by cheating:** every second shows something new, and once the build is done the film keeps
  showing new things, or it is cut shorter.
