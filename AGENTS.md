# Agent guide for `codepawl/creator-generalist`

This repository is the `creator-generalist` skill pack for content creators: `3d-generalist` (3D studio across
Blender, Three.js and 67js, with `model-characters` for 3D characters in any style), `2d-generalist` (2D
editorial motion graphics) and `game-generalist` (playable games on web, Godot, Unity or Unreal). To use a skill, read its `SKILL.md` under `plugins/<plugin>/skills/<skill>/`.

## Hard rules when editing this repository

- Every `SKILL.md` stays at or under 100 lines. Its frontmatter has only `name`, `description` and `license`, with
  `description` in double quotes so it parses as YAML. Put detailed rules in `references/`.
- Skills load on their own: never add `disable-model-invocation` to a skill other than the commands `3dg`, `2dg` and `gameg`.
- `skills/3dg/SKILL.md`, `skills/2dg/SKILL.md` and `skills/gameg/SKILL.md` are commands: their frontmatter also carries `argument-hint` and
  `disable-model-invocation: true`, and their `agents/openai.yaml` files keep `allow_implicit_invocation: false`
  under a top-level `policy:` block (not under `interface:`).
- There is no `local.md` in this pack, by design: machine paths and personal rules never ship.
- Only `3d-generalist`, `2d-generalist` and `game-generalist` are main skills. Every other skill is a craft or tool skill they call.
- `model-characters` is a craft skill for 3D characters in every style. It lives only inside the `3d-generalist` plugin. Do not add a separate
  plugin for it.
- `use-3d-software` lives in the `3d-generalist` plugin and `edit-video` in the `2d-generalist` plugin.
  They are tool skills the generalists call. Do not add a separate plugin for them.
- The craft skills `animate-characters` and `rig-characters` live in the `3d-generalist` plugin, `draw-and-paint-art`
  and `paint-stylized-backgrounds` in the `2d-generalist` plugin. They own one craft across tools and link to the
  tool skills for software recipes.
- `watch-video` is its own plugin: the learning skill (watch a video, remake recipe, tutorial channel into a verified
  skill). It ships `scripts/transcribe.py` and `data/blender-names.json`; regenerate the JSON with
  `scripts/blender_names_dump.py` when Blender's version changes.
- `design-sound` is its own plugin: the sound skill both generalists call (library search, web and ElevenLabs
  fetching, video-to-foley, foley stem, music fit, mix and checks). Machine paths and the owner's own rules stay in
  a local `local.md`, never in the pack; `house-defaults.json` ships with values only, no listening history.
- A new plugin gets an entry in `.claude-plugin/marketplace.json`, a row in the README skill table and its install line.
- A new or renamed skill folder goes into the folder lists of both `README.md` (Install by hand) and `INSTALL.md`.
- 3D mode names (`cutaway`, `story`, `world`, `character`, `asset`) must match across `SKILL.md`, `skills/3dg/SKILL.md`,
  `harness/gemini/3dg.toml`, `harness/opencode/3dg.md` and `README.md`.
- No private data: no personal names, home folders, internal keys or tokens. Use `{{WORK_DIR}}` and `{{SKILL_DIR}}`.
  Default install paths are allowed only inside tool-detection scripts.
- Every frame of a rendered scene or check script must be a pure function of time `f(t)`.
- 2D mode names (`vox-now`, `script`, `photos`, `map`, `chart-timeline`, `archival-collage`, `design`, `audit`) must match across the 2d-generalist
  `SKILL.md`, `skills/2dg/SKILL.md`, `harness/gemini/2dg.toml`, `harness/opencode/2dg.md` and `README.md`.
- Game mode names (`prototype`, `game`, `polish`) must match across `plugins/game-generalist/skills/game-generalist/SKILL.md`,
  `skills/gameg/SKILL.md`, `harness/gemini/gameg.toml`, `harness/opencode/gameg.md` and `README.md`.
- Game examples never use the names of existing commercial games: every example idea is original.
- Game scripts have tests that skip, not fail, when `playwright` or a browser is missing.
