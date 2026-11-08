# Install and set up creator-generalist

This file is for an AI agent. The user asked you to install this skill pack and set up the tools it uses. Do each
step in order, then report what you installed, what was already there and what is still missing.

Ask the user before you install a program with a system package manager or change a setting outside the agent's own
folders. Do not ask for the skill files themselves: copying them is the task.

## 1. Find out which agent you are

Use the first row that matches you.

| Agent | Skills folder | Commands folder |
|---|---|---|
| Claude Code | installed as plugins (step 2) | comes with the plugins |
| Codex | `~/.agents/skills/` | none, the skills load by name |
| Cursor | `~/.cursor/skills/` | none |
| Gemini CLI | `~/.gemini/skills/` | `~/.gemini/commands/` |
| OpenCode | `~/.config/opencode/skills/` | `~/.config/opencode/commands/` |
| Other | the folder your agent reads `SKILL.md` files from | none |

## 2. Install the skills

**Claude Code.** Run these in a shell:

```bash
claude plugin marketplace add codepawl/creator-generalist
claude plugin install 3d-generalist@creator-generalist
claude plugin install 2d-generalist@creator-generalist
claude plugin install watch-video@creator-generalist
claude plugin install design-sound@creator-generalist
```

If the `claude` command is not on the PATH, tell the user to type the same four lines as `/plugin ...` in Claude Code.

**Any other agent.** If Node.js is installed, run `npx skills add codepawl/creator-generalist` and follow its prompts.
Otherwise:

1. Clone the repository to a temporary folder: `git clone --depth 1 https://github.com/codepawl/creator-generalist`.
2. Copy these twelve folders into the skills folder from step 1:
   - `plugins/3d-generalist/skills/3d-generalist`
   - `plugins/3d-generalist/skills/3dg`
   - `plugins/3d-generalist/skills/model-characters`
   - `plugins/3d-generalist/skills/use-3d-software`
   - `plugins/2d-generalist/skills/2d-generalist`
   - `plugins/2d-generalist/skills/2dg`
   - `plugins/2d-generalist/skills/edit-video`
   - `plugins/3d-generalist/skills/animate-characters`
   - `plugins/3d-generalist/skills/rig-characters`
   - `plugins/2d-generalist/skills/draw-and-paint-art`
   - `plugins/2d-generalist/skills/paint-stylized-backgrounds`
   - `plugins/watch-video/skills/watch-video`
   - `plugins/design-sound/skills/design-sound`
3. Gemini CLI: copy `harness/gemini/3dg.toml` and `harness/gemini/2dg.toml` to the commands folder.
   OpenCode: copy `harness/opencode/3dg.md` and `harness/opencode/2dg.md` to the commands folder.
4. Delete the temporary clone.

Check: each copied folder has a `SKILL.md` at its top.

## 3. Check the free tools

Run the audit script from the installed `2d-generalist` skill (Python 3.10 or later):

```bash
python <skills folder>/2d-generalist/scripts/check_vox_toolchain.py
```

It lists what is installed and prints an install command for each missing tool. The tools:

| Tool | Needed for | Required |
|---|---|---|
| Blender 4.2 or later (5.x preferred) | 3D scenes, characters, renders | yes for 3D |
| FFmpeg | encoding clips, GIFs and frame checks | yes |
| Node.js 20 or later | Remotion, Three.js and check scripts | yes |
| Python 3.10 or later | helper scripts | yes |
| DaVinci Resolve (free) | edit, Fusion effects, grade | optional |
| yt-dlp | reading reference videos | optional |
| Krita, Inkscape, GIMP, QGIS | painting, vector, maps | optional |

Show the user the missing required tools with the commands the script printed, and install them after the user says
yes. Optional tools are listed, not installed.

## 4. Smoke test

1. Ask your agent to list its skills, or check the folders. `3d-generalist`, `2d-generalist`,
   `model-characters`, `use-3d-software`, `edit-video`, `animate-characters`,
   `rig-characters`, `draw-and-paint-art`, `paint-stylized-backgrounds`, `watch-video` and `design-sound` must be there.
2. Run `/2dg audit` (Claude Code: `/2d-generalist:2dg audit`) if your agent has commands.
3. If Blender is installed, run `blender --version`.

## 5. Report

Tell the user, in a few lines: where the skills went, which tools are ready, which are missing, and two prompts to try:

- `/3dg cutaway a 14th-century water mill, wheel turning the millstones`
- `/2dg map the Silk Road from Chang'an to Constantinople`
