#!/usr/bin/env bash
# Assembles the walkthrough video from record.mjs (full mode) and tts.sh outputs.
#
#   BUILD_DIR=/path/outside/the/repo [VERSION=v1] [CRF=24] ./compose.sh
#
# Reads   $BUILD_DIR/$VERSION/frames/*.jpg + frames.json   screencast frames and their capture times
#         $BUILD_DIR/$VERSION/marks.json                    chapter start times
#         $BUILD_DIR/audio/NN_step.wav + durations.json      narration
# Writes  $BUILD_DIR/$VERSION/walkthrough_$VERSION.mp4       1280x800, 30 fps, H.264 (yuv420p) + AAC 96k mono
#         $BUILD_DIR/$VERSION/walkthrough_${VERSION}_poster.jpg   a frame from the end of the intro
#         $BUILD_DIR/$VERSION/walkthrough_$VERSION.vtt       captions: each chapter's sentences, timed in proportion
#         $BUILD_DIR/$VERSION/chapters.json                  CALIPER shape: {url, duration, chapters: [{step,label,t}]}
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
: "${BUILD_DIR:?Set BUILD_DIR to a folder outside the repository}"
VERSION="${VERSION:-v1}"
CRF="${CRF:-24}"
FPS=30
OUT="$BUILD_DIR/$VERSION"
AUDIO="$BUILD_DIR/audio"
FFMPEG="${FFMPEG:-ffmpeg}"
FFPROBE="${FFPROBE:-ffprobe}"
MP4="$OUT/walkthrough_$VERSION.mp4"
WORK="$OUT/compose"

for f in "$OUT/frames.json" "$OUT/marks.json" "$AUDIO/durations.json"; do
  [ -f "$f" ] || { echo "compose.sh: missing $f (run tts.sh and record.mjs in full mode first)" >&2; exit 1; }
done
mkdir -p "$WORK"

# 1. Frame list (concat demuxer, each frame shown until the next one), narration inputs, captions and chapters.
node --input-type=module - "$HERE/script.json" "$OUT" "$AUDIO" "$WORK" "$FPS" <<'NODE'
import fs from "node:fs";
import path from "node:path";

const [scriptPath, out, audio, work, fpsArg] = process.argv.slice(2);
const fps = Number(fpsArg);
const script = JSON.parse(fs.readFileSync(scriptPath, "utf8"));
const { end, frames } = JSON.parse(fs.readFileSync(path.join(out, "frames.json"), "utf8"));
const marks = JSON.parse(fs.readFileSync(path.join(out, "marks.json"), "utf8"));
const durations = JSON.parse(fs.readFileSync(path.join(audio, "durations.json"), "utf8"));

// Frames: keep the last one captured before t=0 as the opening frame, then everything after.
let start = 0;
for (let i = 0; i < frames.length; i += 1) if (frames[i].t <= 0) start = i;
const kept = frames.slice(start).map((f, i) => ({ ...f, t: i === 0 ? 0 : f.t })).filter((f) => f.t < end);
const lines = ["ffconcat version 1.0"];
for (let i = 0; i < kept.length; i += 1) {
  const next = i + 1 < kept.length ? kept[i + 1].t : end;
  const duration = Math.max(1 / 1000, next - kept[i].t);
  lines.push(`file '${path.join(out, "frames", kept[i].file).replace(/'/g, "'\\''")}'`, `duration ${duration.toFixed(4)}`);
}
// The concat demuxer ignores the last entry's duration unless the file is listed once more.
lines.push(`file '${path.join(out, "frames", kept[kept.length - 1].file).replace(/'/g, "'\\''")}'`);
fs.writeFileSync(path.join(work, "frames.ffconcat"), lines.join("\n") + "\n");

// Narration: one input per chapter, delayed to its mark.
const chapters = script.chapters.map((c, i) => {
  const mark = marks.chapters.find((m) => m.step === c.step);
  if (!mark) throw new Error(`no mark for ${c.step}`);
  const wav = path.join(audio, `${String(i + 1).padStart(2, "0")}_${c.step}.wav`);
  if (!fs.existsSync(wav)) throw new Error(`missing ${wav}`);
  return { ...c, t: mark.t, dur: durations[c.step], wav };
});
fs.writeFileSync(path.join(work, "audio_inputs.txt"), chapters.map((c) => c.wav).join("\n") + "\n");
const filters = [`[0:v]fps=${fps},scale=1280:800:flags=lanczos,format=yuv420p[v]`];
chapters.forEach((c, i) => filters.push(`[${i + 1}:a]aformat=sample_rates=48000:channel_layouts=mono,adelay=delays=${Math.round(c.t * 1000)}:all=1[a${i}]`));
filters.push(
  `${chapters.map((_, i) => `[a${i}]`).join("")}amix=inputs=${chapters.length}:normalize=0:dropout_transition=0:duration=longest,apad=whole_dur=${end.toFixed(3)}[a]`
);
fs.writeFileSync(path.join(work, "filter.txt"), filters.join(";\n") + "\n");

// Captions: split each chapter into sentences (long ones at a comma or colon) and share its narration time by length.
const stamp = (s) => {
  const ms = Math.max(0, Math.round(s * 1000));
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), sec = Math.floor((ms % 60000) / 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
};
const WIDTH = 42; // characters per caption line; a cue has at most two lines
// One line when it fits, otherwise two lines broken at the space nearest the middle (balanced, not greedy).
const wrap = (text) => {
  if (text.length <= WIDTH) return text;
  const spaces = [...text.matchAll(/ /g)].map((m) => m.index);
  const ok = spaces.filter((i) => i <= WIDTH && text.length - i - 1 <= WIDTH);
  const pool = ok.length ? ok : spaces;
  const at = pool.sort((a, b) => Math.abs(a - text.length / 2) - Math.abs(b - text.length / 2))[0];
  return at === undefined ? text : `${text.slice(0, at)}\n${text.slice(at + 1)}`;
};
// Sentences, without breaking after abbreviations such as "Dr." or "e.g.".
const sentences = (text) => {
  const guarded = text.replace(/\b(?:Dr|Mr|Ms|Mrs|Prof|e\.g|i\.e|vs)\./g, (m) => m.replace(/\./g, "\u0000"));
  return (guarded.match(/[^.!?]+(?:[.!?]+|$)/g) || [])
    .map((s) => s.replace(/\u0000/g, ".").trim())
    .filter(Boolean);
};
// Split a piece that would need more than two lines: at the punctuation nearest its middle, else at a space.
const fit = (piece) => {
  if (wrap(piece).split("\n").every((line) => line.length <= WIDTH)) return [piece];
  const middle = piece.length / 2;
  const marks = [...piece.matchAll(/[,:;] /g)].map((m) => m.index + 1);
  // Without punctuation, prefer the space before a joining word ("before", "so", "which"...) near the middle.
  const joins = /^(and|but|or|so|before|after|which|that|with|from|to|on|in|at|for|because|while|once)\b/;
  const score = (i) => Math.abs(i - middle) - (joins.test(piece.slice(i + 1)) ? 14 : 0);
  const spaces = [...piece.matchAll(/ /g)].map((m) => m.index);
  const pool = marks.filter((i) => i > 12 && piece.length - i > 12);
  const at = pool.length
    ? pool.sort((a, b) => Math.abs(a - middle) - Math.abs(b - middle))[0]
    : spaces.sort((a, b) => score(a) - score(b))[0];
  if (!at) return [piece];
  return [...fit(piece.slice(0, at).trim()), ...fit(piece.slice(at).trim())];
};
const pieces = (text) => sentences(text).flatMap(fit);
const cues = ["WEBVTT", ""];
let n = 1;
for (const c of chapters) {
  const parts = pieces(c.text);
  const total = parts.reduce((sum, p) => sum + p.length, 0);
  let t = c.t;
  for (const p of parts) {
    const span = (c.dur * p.length) / total;
    cues.push(String(n), `${stamp(t)} --> ${stamp(t + span)}`, wrap(p), "");
    n += 1;
    t += span;
  }
}
fs.writeFileSync(path.join(out, `walkthrough_${marks.version}.vtt`), cues.join("\n"));

// Chapter list and the poster time (just before the second chapter: the Demo switch is on, the hero is in view).
fs.writeFileSync(
  path.join(work, "chapters.partial.json"),
  JSON.stringify({ chapters: chapters.map((c) => ({ step: c.step, label: c.label, t: Math.round(c.t * 10) / 10 })) })
);
const second = chapters[1] ? chapters[1].t : Math.min(end, 5);
fs.writeFileSync(path.join(work, "poster_time.txt"), String(Math.max(0, second - 0.4).toFixed(3)));
console.log(`frames: ${kept.length} kept of ${frames.length}; video ${end.toFixed(2)} s; ${chapters.length} narration clips; ${n - 1} caption cues`);
NODE

# 2. Video + narration.
AUDIO_ARGS=()
while IFS= read -r wav; do AUDIO_ARGS+=(-i "$wav"); done < "$WORK/audio_inputs.txt"
"$FFMPEG" -hide_banner -loglevel error -y \
  -f concat -safe 0 -i "$WORK/frames.ffconcat" \
  "${AUDIO_ARGS[@]}" \
  -/filter_complex "$WORK/filter.txt" \
  -map "[v]" -map "[a]" \
  -c:v libx264 -preset slow -crf "$CRF" -tune stillimage -pix_fmt yuv420p -r "$FPS" \
  -c:a aac -b:a 96k -ac 1 -ar 48000 \
  -movflags +faststart \
  "$MP4"

# 3. Poster from the end of the intro.
"$FFMPEG" -hide_banner -loglevel error -y -ss "$(cat "$WORK/poster_time.txt")" -i "$MP4" -frames:v 1 -q:v 3 \
  "$OUT/walkthrough_${VERSION}_poster.jpg"

# 4. chapters.json in CALIPER's shape, with the encoded duration.
DURATION="$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$MP4")"
node -e '
const fs = require("fs");
const partial = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const out = { url: "/media/walkthrough.mp4", duration: Math.round(Number(process.argv[2]) * 10) / 10, chapters: partial.chapters };
fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 2) + "\n");
' "$WORK/chapters.partial.json" "$DURATION" "$OUT/chapters.json"

echo "wrote $MP4 ($(du -h "$MP4" | cut -f1), ${DURATION}s)"
