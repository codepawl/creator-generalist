# Code build-up film: code on one side, the scene growing on the other

A 30 to 60 s film that shows how a technique works. The scene grows one rule at a time while the code that makes it
fills a column beside it. Each beat drops one code block into `build()`, drags one number, and the picture changes
on the same frame. Use it for "how it's made from code" clips, technique explainers, generative art reveals, shader or
algorithm demos, and any "watch the code build this" post. Any engine works if every frame is a pure function of time.

Reading map: "Layout and one table" first, then "Time and pointer", "Captions", "Ending", "Sound", "Checks". A
worked recipe (triangles to a glowing core) sits at the end.

## Layout and one table

- Split the frame: code column on the left (about 38% of the width), the stage on the right. When the subject takes
  over (the climax), the stage fills the frame and the code shrinks onto a small glass panel in a corner.
- One timeline table drives everything: beats (caption words and times), blocks (name, carry time, the line it adds to
  `build()`, the function the column scrolls to), number drags (setting, start, seconds, target value) and layout
  times. The stage, the code overlay, the pointer, the captions and the sound all read the same table, so the picture,
  the code and the sound can never drift apart.
- Code is visual-programming blocks on a shelf (Scratch-style), picked up and carried into `build()` in about 1 s.
  The column then scrolls to that function's body. The body is the scene's real steps written short, 4 to 7 lines.
- Numbers change by a sideways drag on the value in a pinned `settings` block. A setting keeps its last value between
  drags. The stage reads the eased value: `value += (to - value) * smoothstep(start, start + seconds, t)` per drag.
- One block and one drag per beat. The viewer sees one cause and one effect at a time.

## Time and pointer

- Author everything in film time, then play the slow opening faster in the video: a playback speed of 2x until the
  first big change, easing back to 1x over about 1.4 s. Integrate `1 / speed` into a table of video time per film time
  (1 ms steps), and invert it by binary search when rendering video frame `n`. Stage constants never change.
- Sound events and caption times map from film time to video time through the same table. Export it with the events.
- The pointer waits, then moves fast: hold at the last spot, then glide in 0.35 to 0.75 s of video time (about
  `0.3 + distance / 1300` s), smoothstep eased. Scale the film-time move by the playback speed at its end, so a sped-up
  opening does not make the hand fly. Slow, drifting moves read as boring.

## Captions

- One plain sentence per beat in a bottom band, naming the change and its result ("More depth folds the flat
  triangles onto a cube and a sphere"). No colon, no full stop at the end, no filler words.
- The last caption states the payoff, never a summary or a slogan.

## Ending

- End on a payoff, never a fade or a hold: build to the most intense state, then a short reverse. A strong one returns
  to the opening picture: the finished subject implodes to a point, then bursts back into the flat first frame. The
  loop closes and the viewer sees how far the rules went.
- The code folds down to the `build()` lines only during the climax, so the last frame shows the whole recipe.

## Sound

- No interface sounds: no clicks for block pick-ups, drags or scrolls. Sound only where the subject transforms.
- Parts snapping together get many small metal clamps and latches with a few heavy clunks among them, like a suit
  of armour assembling itself, never one big hit. Cycle the pitch per clamp and climb through a run.
- A lock sound goes where the piece looks settled: about 80% through its smoothstep move (90% of the distance). The
  end of the ease is 0.3 s or more late and reads as out of sync.
- A molten or glowing subject gets a low bubbling bed that rises with its power value.
- Music sits under all of it, calm and warm; a creepy or tense bed fights a playful build. Send 2 or 3 music options.
- Details and commands: the `design-sound` skill, `references/foley.md`, "Motion graphics weight".

## Checks

- Pointer smoothness: sample the pointer every video frame. Fail when the change between two neighbouring steps is
  over 30 px (a jerk), not when one step is large (a fast move is wanted).
- Every sound cue lands within one frame of its event in video time; read one frame sheet with timestamps against
  the cue list.
- Render by seeking: frame `n` is `f(filmTimeAt(n / fps))`. Never record the screen.

## Worked recipe: scattered points to a glowing core

Six blocks, one per beat. Every function below is a few lines in the column.

1. `triangulate(points, gradient)`: scatter points that drift slowly, join them with Delaunay triangulation, colour
   each triangle from a gradient sampled at its centre. Drag `points` from 0 to about 300.
2. `lift(triangles, [cube, sphere], depth)`: match each triangle to a face of the target shapes and mix its corners
   from flat to the face corners by `depth`. Stagger the lift per triangle so the sheet folds in a sweep.
3. `morph(shapes, amount, time)`: push each corner along its normal by `amount * sin(time * 2 + height * 6)`.
4. `collide(shapes, floor, gravity)`: the shapes fall, touch the floor and each other, dent at the hit and bounce
   with restitution 0.4.
5. `glow(shapes, core, amount)`: pull both shapes into one core, raise facet emission and bloom with `amount`.
6. `react(core, power, time)`: colour by power (blue, green, red), and each facet hops when
   `random(facet, time) < power * 0.11`; rings push out with the hops. At the top value it never settles.

Ending: implode the core to a point, then burst every triangle back to its flat start position, staggered by a hash
of its index over about 0.1 s.

Ideas that reuse the same rules: a crystal that grows a facet per event, a paper creature that folds itself up from a
flat sheet, a force field that cracks along its triangles and then heals.
