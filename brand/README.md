# bluepuff brand

bluepuff is the working brand for the dinghy sail-racing forecast app. It is built on Bluepow's brand: same icon grid, wordmark build, fonts and voice. The full guide is `brand-guide.html` (live copy: https://claude.ai/artifact/Y7iXFs9RDrbgHdBCh5Ymqt).

Decided 9 Nov 2026: the name **bluepuff** and the **puff** mark (three wind streaks), replacing Bluepow's snowflake. Before launch: trademark and app-store search on the name.

## Assets (`assets/`)

Same files and sizes as the Bluepow app (`bluepow-app/app/assets/`), so an Expo app can use them as they are.

| File | Use |
|---|---|
| `icon.png`, `icon.svg` | iOS and store icon, 1024 px, full bleed (the OS rounds the corners) |
| `android-icon-foreground.png`, `-background.png`, `-monochrome.png` | Android adaptive icon (artwork at 62%, inside the safe zone) |
| `splash-icon.png` | Splash artwork on a `#0A4DA8` background |
| `favicon.png` | Web, 48 px |
| `wordmark-on-blue.svg/.png`, `wordmark-on-light.svg`, `wordmark-mono-white.svg`, `wordmark-mono-blue.svg` | Wordmark, outlined (no font needed) |

Regenerate with `npm install && npm run icons` in this folder.

## Tokens

| Token | Hex | Bluepow equivalent | Use |
|---|---|---|---|
| regatta | `#0A4DA8` | cobalt `#0B2BB0` | Primary, full-bleed |
| deep | `#063679` | navy | Cards on blue, 4Kasta tag |
| abyss | `#041F44` | night | Dark mode |
| raised | `#1563C9` | raised | Pressed, hourly cells |
| line | `#3C78CC` | line | Borders, chart grid |
| foam | `#F2F8FF` | snow | Text on blue |
| spray | `#D2E8FF` | ice | Light panels |
| mist | `#B5CDEE` | mist | Secondary text on blue |
| sun | `#FFD23F` | sun (same) | Only the race-on call and the PLUS pill |
| port | `#E5484D` | none | Port-tack advice only, always labelled |
| starboard | `#1FA971` | none | Starboard-tack advice only, always labelled |

Fonts are unchanged from Bluepow: Space Grotesk Bold (wordmark and 4Kasta tag), Bricolage Grotesque (numbers, headings), Figtree (text).
