// Generates the bluepuff (sail racing app) icon set and wordmark, using the same grid as Bluepow's make-icons.mjs:
// a white Bricolage "b" with a yellow puff top-right on Regatta blue. Brand guide: sail/brand/README.md
//   cd brand && npm install && npm run icons
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import opentype from "opentype.js";
import sharp from "sharp";

const here = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(here, "assets");
fs.mkdirSync(outDir, { recursive: true });
const REGATTA = "#0A4DA8", FOAM = "#F2F8FF", SUN = "#FFD23F";
const fonts = path.join(here, "node_modules", "@expo-google-fonts");
const load = (f) => { const b = fs.readFileSync(path.join(fonts, f)); return opentype.parse(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)); };
const bricolage = load("bricolage-grotesque/800ExtraBold/BricolageGrotesque_800ExtraBold.ttf");
const space = load("space-grotesk/700Bold/SpaceGrotesk_700Bold.ttf");

// The puff: three wind streaks, the middle one curling. Same 24-unit box, stroke and round caps as the snowflake.
const PUFF = "M2.5 7.5h9.5a3 3 0 1 0-3-3M2.5 12h15a3.2 3.2 0 1 1-3.2 3.2M2.5 16.5h6";
const puff = (color, x, y, size) =>
  `<g transform="translate(${x} ${y}) scale(${size / 24})" fill="none" stroke="${color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="${PUFF}"/></g>`;

// Artwork on the 120-unit grid of the Bluepow icon (glyph 88px, mark 34px top-right).
function artwork({ glyph = FOAM, mark = SUN }) {
  const size = 88;
  const bb = bricolage.getPath("b", 0, 0, size).getBoundingBox();
  const dx = 60 - (bb.x1 + bb.x2) / 2 - 4;
  const dy = 66 - (bb.y1 + bb.y2) / 2;
  return `<path d="${bricolage.getPath("b", dx, dy, size).toPathData(2)}" fill="${glyph}"/>${puff(mark, 73, 11, 36)}`;
}

function svg({ bg, scale = 1, ...colors }) {
  const s = 1024 / 120 * scale, off = (1024 - 120 * s) / 2;
  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
    ${bg ? `<rect width="1024" height="1024" fill="${bg}"/>` : ""}
    <g transform="translate(${off} ${off}) scale(${s})">${artwork(colors)}</g></svg>`);
}

// Wordmark: Space Grotesk Bold, tracking -2%, puff at the shoulder at half the font size (as in ui.tsx Logo).
function wordmark({ text = FOAM, mark = SUN, bg }) {
  const fs_ = 200, pad = 40;
  let x = 0; const parts = [];
  for (const ch of "bluepuff") {
    parts.push(space.getPath(ch, Math.round(x), fs_, fs_).toPathData(2));
    x += space.getAdvanceWidth(ch, fs_) - fs_ * 0.02;
  }
  const bb = space.getPath("bluepuff", 0, fs_, fs_).getBoundingBox();
  const m = fs_ * 0.5, mx = x + fs_ * 0.02, my = bb.y1 + fs_ * 0.02;
  const w = Math.ceil(mx + m + pad * 2), h = Math.ceil(bb.y2 - bb.y1 + pad * 2 + fs_ * 0.05);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
  ${bg ? `<rect width="${w}" height="${h}" fill="${bg}"/>` : ""}
  <g transform="translate(${pad} ${pad - bb.y1})"><path d="${parts.join("")}" fill="${text}"/></g>
  ${puff(mark, pad + mx, pad - bb.y1 + my, m)}
</svg>
`;
}

const out = async (name, buf, size = 1024) => {
  await sharp(buf).resize(size, size).png().toFile(path.join(outDir, name));
  console.log("wrote", name);
};

await out("icon.png", svg({ bg: REGATTA }));
await out("android-icon-background.png", svg({ bg: REGATTA, glyph: "none", mark: "none" }));
await out("android-icon-foreground.png", svg({ scale: 0.62 }));
await out("android-icon-monochrome.png", svg({ scale: 0.62, glyph: "#FFFFFF", mark: "#FFFFFF" }));
await out("splash-icon.png", svg({ scale: 0.9 }));
await out("favicon.png", svg({ bg: REGATTA }), 48);
fs.writeFileSync(path.join(outDir, "icon.svg"), svg({ bg: REGATTA }));
for (const [name, opts] of [
  ["wordmark-on-blue.svg", { bg: REGATTA }],
  ["wordmark-on-light.svg", { text: REGATTA }],
  ["wordmark-mono-white.svg", { text: "#FFFFFF", mark: "#FFFFFF" }],
  ["wordmark-mono-blue.svg", { text: REGATTA, mark: REGATTA }],
]) { fs.writeFileSync(path.join(outDir, name), wordmark(opts)); console.log("wrote", name); }
await sharp(Buffer.from(wordmark({ bg: REGATTA }))).resize({ width: 1600 }).png().toFile(path.join(outDir, "wordmark-on-blue.png"));
console.log("wrote wordmark-on-blue.png");
