# Game UI reference: Game UI Database

Use https://www.gameuidatabase.com/ to look at real shipped game UI before you design a screen. It holds about
80,000 screenshots and 2,500 videos from 2,000 games (checked 2026-11-19), and it is free with no account.

## When to read it

- Step 2 (Reference) of the spine: for every screen the game has (title, pause, HUD, inventory, results, game over),
  look at 5 to 10 games of the same genre and theme. Write one "take / leave" line per game in `refs/NOTES.md`.
- Any non-game UI that has the same job as a game screen: settings, onboarding, loadout or picker, shop, map,
  leaderboard, achievements, a viewer with a 3D model, a photo mode. Crucible Studio and tool UIs count.

## How to search

Browse by screen type with `index.php?scrn=<id>`. Add `&set=1` to list screenshots instead of games, and `&vid=1` for
videos. Useful ids:

| Screen | id | Screen | id |
|---|---|---|---|
| Title screen | 1 | Pause | 44 |
| Loading screen | 3 | Failure and game over | 51 |
| Settings menu | 26 | Level complete | 52 |
| UI and accessibility settings | 30 | Results screen | 53 |
| All gameplay and HUDs | `set=0&scrn=904` | Leaderboards | 55 |
| Player vitals (health bars) | 133 | All inventory | 100 |
| Enemy health and damage | 143 | Skill tree | 64 |
| Scoring and combos | 136 | Character select | 41 |
| Clock and timer | 137 | World map | 6 |
| Tutorials and hints (HUD) | 159 | Dialogue and speech | 162 |
| Notification (HUD) | 156 | 3D model viewer | 117 |
| Item get | 33 | Photo and camera mode | 24 |

The left filter panel narrows by platform (PC and console, mobile, VR, Playdate), genre, theme (horror, cartoon,
futuristic and others), age rating and aesthetic. The ids for screens not in this table come from the category menu
on the home page.

Tools on a screenshot: a hex colour search (find games that use one colour), a grid overlay (12, 18 or 24 columns,
rule of thirds, mobile portrait), colour-blind filters (protanopia, deuteranopia, tritanopia, greyscale) and a font
suggestion for text in the image. Use the colour-blind filters to check that a HUD state is not only told by colour.

## Reading the site

WebFetch gets HTTP 403 from this site. Open it in the built-in browser and read it with `get_page_text` or a short
`javascript_tool` query of the links. When you must look at more than about 5 screenshots, hand them to a subagent
that reads images and returns text, and work from that text.

## Rules

- The screenshots belong to their games. Use them only as reference. Never put one in a build, a post, a trailer or a
  pack, and never copy a layout one to one: take the idea (what the screen shows first, how a state is marked) and
  draw it in the game's own style.
- The project's own UI rules still win over what a game does.
