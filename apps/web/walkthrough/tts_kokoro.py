"""Kokoro narration for tts.sh: one WAV per line of spoken.tsv (index<TAB>step<TAB>text).

Run with the Python of a venv that has kokoro-onnx and soundfile, from KOKORO_DIR (model files):
    python tts_kokoro.py spoken.tsv AUDIO_DIR VOICE SPEED
Each chapter is spoken sentence by sentence with a short pause between sentences, peak-normalised, and
written as NN_step.24k.wav (24 kHz float); tts.sh converts it to 48 kHz 16-bit.
"""

import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

PAUSE_S = 0.28  # between sentences
PEAK = 0.89  # -1 dBFS


def sentences(text: str) -> list[str]:
    guarded = re.sub(r"\b(?:Dr|Mr|Ms|Mrs|Prof|e\.g|i\.e|vs)\.", lambda m: m.group(0).replace(".", "\0"), text)
    parts = re.findall(r"[^.!?]+(?:[.!?]+|$)", guarded)
    return [p.replace("\0", ".").strip() for p in parts if p.strip()]


def main() -> None:
    tsv, audio_dir, voice, speed = sys.argv[1], Path(sys.argv[2]), sys.argv[3], float(sys.argv[4])
    kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    lang = "en-gb" if voice.startswith("b") else "en-us"
    for line in Path(tsv).read_text(encoding="utf-8").splitlines():
        index, step, text = line.split("\t", 2)
        if not text.strip():
            sys.exit(f"tts_kokoro.py: chapter {step} has no text")
        pieces, rate = [], 24000
        for sentence in sentences(text):
            samples, rate = kokoro.create(sentence, voice=voice, speed=speed, lang=lang)
            pieces += [samples, np.zeros(int(PAUSE_S * rate), dtype=np.float32)]
        audio = np.concatenate(pieces[:-1])
        audio = audio * (PEAK / max(1e-6, float(np.abs(audio).max())))
        sf.write(audio_dir / f"{index}_{step}.24k.wav", audio.astype(np.float32), rate, subtype="FLOAT")


if __name__ == "__main__":
    main()
