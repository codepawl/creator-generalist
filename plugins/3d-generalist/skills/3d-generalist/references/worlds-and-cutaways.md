# Worlds, Cutaways and Environment Effects (`worlds-and-cutaways.md`)

A 3D scene must read at a glance and never look empty. Every layer of the frame (sky, background, midground, foreground
and underground section) needs real depth and subtle motion.

## 1. Perspective cutaway staging

- **Perspective side camera, never flat orthographic 2D:** place the camera slightly off-axis and above so cylinders,
  domes, timber and terrain read round and solid.
- **World on top, cross-section below:** carve the build into a ground, rock, snow or water cross-section slab. Make
  all cutaway section meshes **double-sided** so no camera angle ever shows sky through the back of a cut wall.
- **No coplanar flicker:** where a floor meets a cutaway wall, rest the floor on a ledge or beam inside the wall and cut
  both on the exact same plane so wood never pokes or z-fights through stone.
- **Part inside a building stays inside:** if a pipe, flue or trap sits inside a wall or room, give that wall its own
  local lengthwise cutaway rather than pulling the interior part outside the building onto the main cut plane.
- **Object-driven shader cutaway in Blender:** to see inside an enclosed cabin, room or vehicle without destructive
  boolean meshes, mix `Principled BSDF` and `Transparent BSDF` with a `Mix Shader` whose factor comes from
  `Texture Coordinate (Object: Empty Sphere) -> Separate XYZ (Y)`. Move, rotate (`180 deg`) or scale the Empty Sphere
  to control the transparent cut plane interactively from any camera angle.

## 2. Dressing the world (real place, real period, moving life)

- **Pick a specific place and century first:** before placing a single tree or fence, decide where and when the build
  happens (for example 14th-century English mill valley, Polynesian coral shore, Roman river crossing). Dress the world
  with period-accurate carts, tracks, hedges, far cottages, rocks and tools.
- **Dress where the camera actually looks:** measure which `(x, z)` cells appear in frame across the timeline. Do not
  waste 50 props behind the camera while leaving the visible horizon bare; if a sailing or road shot sees 150 m back,
  dress the shore or road 150 m deep.
- **Ambient motion in every layer:** nothing in the background stays dead still.
  - *Sky:* drifting clouds, birds flying across the horizon.
  - *Land / Road:* tree leaves swaying gently, a truck or cart moving linearly between two keyframes in the far background,
    animals with real breathing/grazing idle clips (never a frozen statue).
  - *Water:* swimming fish, bounded sine-field caustics on the bed (0.1 to 0.2 emissive, ~40 cm cells, never raw division
    that produces `NaN` black blobs), foam at the waterline, and water clamped below rising beach sand.

## 3. Physics-true water, fire, weather and digging

- **Water obeys gravity on every frame:** still water in a U-bend, trap or well sits flat and level at the weir height
  in both legs, never clinging to a falling outlet slope. Underground water pockets look carved in rough PBR rock with a
  dark wet band along the wall, never a smooth blue sphere.
- **Standing in water:** place the character's feet on the stream or sea bed (or a flat bed shelf under both feet), with
  water at ankle or shin height and ripples around the legs, never walking on top of the water surface.
- **Realistic fire:** use a sourced CC0 fire flipbook or clip on camera-facing planes with additive blending, rising
  embers, soft smoke and a warm flickering point light. Never use an orange cone or falling orange spheres.
- **Weather and air lines:** wind, mist, rain and sun rays are a faint atmospheric hint (soft-edged, low opacity,
  stopped by solid walls). Flow arrows use a single clean style (either thin solid or thin dashed lines, never thick
  striped tubes), and pull their tail into the arrowhead when exiting.
- **Piece-by-piece building and digging:**
  - Digging happens one scoop at a time where the character stands: each scoop removes one chunk and throws it onto a
    growing spoil mound (`mound` surface) with its own dig sound. Holes never sink or fade smoothly on their own.
  - Masonry and timber assemblies seat piece by piece from the character's hands with a small settle and contact SFX,
    with zero gap (within 1 cm) between courses.

## 4. Layers, horizon and small effects

- **Never an empty void:** build a wide area around the set in layers (near ground cover and props, middle trees and huts,
  far hills or forest) with depth fog, ambient occlusion and a few foreground occluders, so every camera angle has depth
  behind the work. Dress every layer with small moving details: fish and caustics under water, shells and bushes on the
  shore, birds and clouds in the sky. Real CC0 or CC BY models; anything on screen reads at a glance as a real thing, so
  replace an unreadable prop with a sourced model or remove it.
- **Horizon haze:** fog does not touch the scene background, so fogged ground meeting an HDR sky ends in a hard straight line.
  Add a camera-centred sphere in the fog colour, solid at the horizon and fading out by direction.y about 0.16, and end the sea
  inside it, short of the camera far plane (a clipped sea edge drew a bright line through the bloom). Check with a
  row-brightness scan.
- **Grass:** a free Blender grass add-on baked to GLB and instanced, never a handful of tufts. Use a flat shelf of bed for
  standing in water.
- **Small effects are many faint particles:** drips, sparks and dust start at points spread along the source with a seeded
  random start, size and speed, denser and sparser in turns, ending in a tiny splash or fade; never one drop looping on a
  fixed beat. Particles that carry an action the voice names (salt thrown over a rack) are 2 cm or more and number in the
  hundreds, so the action reads at phone size; a tint change with 8 mm grains is invisible.
- **A failure beat shows its problem with a small real detail:** rot gives faint stink wisps, wet fish drip, cooking fish drip
  fat into the fire. Soft vapour sprites and drops, never cartoon stink lines.
- **Building moves like real work:** show what is being reached (water, bedrock) in the cutaway from the start, then dig to
  it layer by layer, never a smooth linear sink; water appears only when the dig reaches it. Dig the named hole itself.
- **Built things are square and even:** a hood, flue or tunnel is symmetric about its axis, courses the same height, walls the
  same thickness on both sides; check a close still from above and from the front. Joined parts (tunnel, porch, wing) run
  into the shell wall with no slot of sky or ground between them. A pipe or post beside a wall stands 5 cm or more clear of it
  with brackets, never sharing space with a corner post.
- **Rigging follows the real rig, checked against a reference** (a crab-claw sail's tack sits at the bow by the mast foot).
- **Failure of a structure takes everything attached with it** (a ramp stays standing after the hut falls reads as a bug); a
  storm stays readable, never black; wind moves leaves and trees with weight and lag, never a fast jitter; a key moment far
  away gets a closer camera.
- **Machines read the right way at a glance:** a pump's intake in the source, its spout toward the tank, the handle on the
  worker's side, the flow visible when it works.
