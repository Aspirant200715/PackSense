"""Regenerate editable PackSense narration and a self-made ambient score.

Narration needs `edge-tts` installed separately. The committed MP3 files let
Remotion render without contacting a speech service.
"""

import asyncio
import json
import math
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "audio"
OUT.mkdir(parents=True, exist_ok=True)


async def make_voice() -> None:
    import edge_tts

    lines = json.loads((ROOT / "narration.json").read_text())
    for i, line in enumerate(lines, 1):
        dest = OUT / f"voice-{i:02}.mp3"
        await edge_tts.Communicate(line, "en-US-AndrewNeural", rate="-4%").save(str(dest))
        print(dest.name, flush=True)


def make_score() -> None:
    sample_rate = 22050
    duration = 64
    t = np.arange(sample_rate * duration, dtype=np.float64) / sample_rate
    score = np.zeros_like(t)
    chords = [
        (130.81, 164.81, 196.00, 246.94),  # Cmaj7
        (110.00, 130.81, 164.81, 220.00),  # Am7
        (87.31, 130.81, 174.61, 196.00),   # Fmaj7
        (98.00, 146.83, 196.00, 220.00),   # Gadd9
    ]
    for bar in range(8):
        start = bar * 8
        local = t - start
        active = (local >= 0) & (local < 8)
        if not active.any():
            continue
        env = np.minimum(np.maximum(local, 0) / 1.3, 1) * np.minimum(np.maximum(8 - local, 0) / 1.4, 1)
        chord = chords[bar % 4]
        for j, freq in enumerate(chord):
            phase = 2 * np.pi * freq * t
            pad = np.sin(phase) + 0.16 * np.sin(2 * phase) + 0.05 * np.sin(3 * phase)
            score += active * env * pad * (0.047 if j == 0 else 0.022)
        for beat in range(8):
            on = local - beat
            pluck_env = np.exp(-np.maximum(on, 0) * 5) * (on >= 0) * (on < 1)
            freq = chord[(beat + 1) % 4] * 2
            score += active * pluck_env * 0.019 * np.sin(2 * np.pi * freq * t)
    fade = np.minimum(t / 2, 1) * np.minimum((duration - t) / 3, 1)
    score = np.clip(score * np.maximum(fade, 0), -0.95, 0.95)
    wav_path = OUT / "score.wav"
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes((score * 32767).astype("<i2").tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-b:a", "128k", str(OUT / "score.mp3")], check=True)
    wav_path.unlink()


if __name__ == "__main__":
    if os.environ.get("PACKSENSE_NO_VOICE") != "1":
        asyncio.run(make_voice())
    make_score()
