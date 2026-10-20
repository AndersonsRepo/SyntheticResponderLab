#!/usr/bin/env bash
# Narration for the walkthrough video: one WAV per chapter of script.json, plus durations.json.
#
#   BUILD_DIR=/path/outside/the/repo [KOKORO_DIR=~/.cache/kokoro] ./tts.sh
#
# The voice comes from script.json's "voice":
#   {"engine": "kokoro", "name": "af_heart", "speed": 1.0}  Kokoro-82M, an open-weights voice model run locally
#       (kokoro-onnx). KOKORO_DIR holds kokoro-v1.0.onnx, voices-v1.0.bin and a venv/ with kokoro-onnx and
#       soundfile; the model files are the "model-files-v1.0" release of github.com/thewh1teagle/kokoro-onnx.
#   {"engine": "say", "name": "Samantha", "rate": 175}     the macOS voice.
# Either way `afconvert` writes 16-bit 48 kHz WAV and `afinfo` reports each duration. Output lands in
# $BUILD_DIR/audio/: NN_step.wav and durations.json ({step: seconds}).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_JSON="${SCRIPT_JSON:-$HERE/script.json}"
: "${BUILD_DIR:?Set BUILD_DIR to a folder outside the repository}"
# Absolute paths: the Kokoro step runs from KOKORO_DIR, and node's require() reads a bare name as a module.
SCRIPT_JSON="$(cd "$(dirname "$SCRIPT_JSON")" && pwd)/$(basename "$SCRIPT_JSON")"
BUILD_DIR="$(mkdir -p "$BUILD_DIR" && cd "$BUILD_DIR" && pwd)"
KOKORO_DIR="${KOKORO_DIR:-$HOME/.cache/kokoro}"
AUDIO_DIR="$BUILD_DIR/audio"
mkdir -p "$AUDIO_DIR"

for tool in afconvert afinfo node; do
  command -v "$tool" >/dev/null || { echo "tts.sh: $tool not found" >&2; exit 1; }
done

voice() { node -e 'const v=(require(process.argv[1]).voice)||{}; process.stdout.write(String(v[process.argv[2]] ?? process.argv[3]))' "$SCRIPT_JSON" "$1" "$2"; }
ENGINE="$(voice engine say)"
VOICE="$(voice name Samantha)"

# One line per chapter: index<TAB>step<TAB>spoken text. The spoken text is the caption text with a few
# pronunciation fixes, so captions keep the on-screen spelling ("Demo (no AI)") and the voice reads it well.
# Kokoro already says "AI", "US" and "Minh" correctly; `say` needs them spelled out.
node -e '
const [scriptPath, engine] = process.argv.slice(1);
const s = require(scriptPath);
const common = (t) => t.replace(/Demo \(no AI\)/g, "Demo, no AI,").replace(/\bDr\. /g, "Doctor ");
const forSay = (t) => t.replace(/\bAI\b/g, "A.I.").replace(/\bUS\b/g, "U.S.").replace(/\bMinh\b/g, "Min");
const spoken = (t) => (engine === "say" ? forSay(common(t)) : common(t)).replace(/\s+/g, " ").trim();
s.chapters.forEach((c, i) => {
  process.stdout.write([String(i + 1).padStart(2, "0"), c.step, spoken(c.text)].join("\t") + "\n");
});
' "$SCRIPT_JSON" "$ENGINE" > "$AUDIO_DIR/spoken.tsv"

case "$ENGINE" in
  kokoro)
    SPEED="$(voice speed 1.0)"
    for f in kokoro-v1.0.onnx voices-v1.0.bin venv/bin/python; do
      [ -e "$KOKORO_DIR/$f" ] || { echo "tts.sh: missing $KOKORO_DIR/$f (see the header of this script)" >&2; exit 1; }
    done
    (cd "$KOKORO_DIR" && ./venv/bin/python -I "$HERE/tts_kokoro.py" "$AUDIO_DIR/spoken.tsv" "$AUDIO_DIR" "$VOICE" "$SPEED")
    ;;
  say)
    command -v say >/dev/null || { echo "tts.sh: say not found" >&2; exit 1; }
    RATE="$(voice rate 175)"
    ;;
  *)
    echo "tts.sh: unknown voice engine '$ENGINE'" >&2
    exit 1
    ;;
esac

DURATIONS="{"
SEP=""
while IFS=$'\t' read -r idx step text; do
  base="$AUDIO_DIR/${idx}_${step}"
  if [ "$ENGINE" = say ]; then
    say -v "$VOICE" -r "$RATE" -o "$base.aiff" -- "$text"
    afconvert -f WAVE -d LEI16@48000 "$base.aiff" "$base.wav"
  else
    afconvert -f WAVE -d LEI16@48000 "$base.24k.wav" "$base.wav"
  fi
  dur="$(afinfo "$base.wav" | awk '/estimated duration/ {print $3}')"
  [ -n "$dur" ] || { echo "tts.sh: no duration for $base.wav" >&2; exit 1; }
  printf '%s  %-20s %6.2fs\n' "$idx" "$step" "$dur"
  DURATIONS="$DURATIONS$SEP\"$step\": $dur"
  SEP=", "
done < "$AUDIO_DIR/spoken.tsv"
DURATIONS="$DURATIONS}"

node -e '
const d = JSON.parse(process.argv[1]);
const total = Object.values(d).reduce((a, b) => a + b, 0);
require("fs").writeFileSync(process.argv[2], JSON.stringify(d, null, 2) + "\n");
console.log(`narration total ${total.toFixed(1)} s -> ${process.argv[2]}`);
' "$DURATIONS" "$AUDIO_DIR/durations.json"
