"""
Brand intro generator.

Produces a short branded intro clip:
    chime.wav + Kokoro TTS narration → brand card image with text overlay → .mp4

Assets expected in show_config.brand_dir/:
    intro_waving_ig.png   — Instagram (9:16) brand image
    intro_card_yt.png     — YouTube (16:9) brand image
    chime.wav             — short intro chime

Kokoro TTS (optional dep): pip install kokoro numpy
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from gemini_videogen.config import ShowConfig
from gemini_videogen.pipeline.assemble import _run


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

def _narrator_tts(episode_number: int, episode_title: str, output_path: Path) -> bool:
    """Kokoro TTS — runs in an isolated subprocess.
    PyTorch crashes with SIGBUS on exit during cleanup on some macOS builds;
    isolating it means the WAV is written before the crash and the caller survives."""
    import sys
    text = f"Hello everyone... Episode {episode_number}... {episode_title}."
    script = "\n".join([
        "import sys, numpy as np, wave as _wav",
        "from kokoro import KPipeline",
        "pipeline = KPipeline(lang_code='a')",
        f"text = {text!r}",
        "segments = [audio for _, _, audio in pipeline(text, voice='af_heart', speed=0.82)]",
        "if not segments: sys.exit(1)",
        "combined = np.concatenate(segments)",
        "pcm = (np.clip(combined, -1, 1) * 32767).astype(np.int16)",
        "with _wav.open(sys.argv[1], 'w') as wf:",
        "    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)",
        "    wf.writeframes(pcm.tobytes())",
    ])
    try:
        subprocess.run(
            [sys.executable, "-c", script, str(output_path)],
            capture_output=True,
            timeout=60,
        )
        return output_path.exists()
    except Exception as e:
        print(f"    Narrator TTS failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Brand intro
# ---------------------------------------------------------------------------

def generate_brand_intro(
    episode_number: int,
    episode_title: str,
    output_path: Path,
    show_config: ShowConfig,
    platform: str = "instagram",
) -> Optional[Path]:
    """Generate brand intro: chime + TTS over brand card image.

    Returns output_path on success, None if assets are missing.
    """
    brand_image = show_config.brand_dir / (
        "intro_waving_ig.png" if platform == "instagram" else "intro_card_yt.png"
    )
    chime = show_config.brand_dir / "chime.wav"

    if not brand_image.exists() or not chime.exists():
        print(f"    Brand assets not found in {show_config.brand_dir} — skipping intro.")
        print(f"    Expected: {brand_image.name}, chime.wav")
        return None

    if output_path.exists():
        return output_path

    tmp = output_path.parent
    tts_wav = tmp / "_intro_tts.wav"
    mixed_wav = tmp / "_intro_mix.wav"

    # 1. Narrator TTS
    tts_ok = _narrator_tts(episode_number, episode_title, tts_wav)

    # 2. Mix: chime at t=0, TTS starts 400ms later
    if tts_ok and tts_wav.exists():
        ok = _run([
            "ffmpeg", "-y",
            "-i", str(chime), "-i", str(tts_wav),
            "-filter_complex", "[1:a]adelay=400|400[d];[0:a][d]amix=inputs=2:duration=longest",
            str(mixed_wav),
        ], "intro-mix")
        audio = str(mixed_wav) if ok else str(chime)
    else:
        audio = str(chime)

    # 3. Measure audio length
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio],
        capture_output=True, text=True,
    )
    try:
        audio_dur = max(float(probe.stdout.strip()), 2.0) + 0.4
    except Exception:
        audio_dur = 4.5

    # 4. Pillow composite: scale brand image + text overlay
    from PIL import Image as PILImage, ImageDraw, ImageFont

    if platform == "instagram":
        w, h = 720, 1280
    else:
        w, h = 1280, 720

    img = PILImage.open(brand_image).convert("RGB")
    img.thumbnail((w, h), PILImage.LANCZOS)
    canvas = PILImage.new("RGB", (w, h), (0, 0, 0))
    offset = ((w - img.width) // 2, (h - img.height) // 2)
    canvas.paste(img, offset)

    draw = ImageDraw.Draw(canvas, "RGBA")
    ep_label = f"Episode {episode_number}  |  {episode_title}"
    font_size = 36
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), ep_label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 18
    bar_top = h - th - pad * 2 - 20
    draw.rectangle([0, bar_top, w, h], fill=(0, 0, 0, 160))
    draw.text(((w - tw) // 2, bar_top + pad), ep_label, font=font, fill=(255, 255, 255, 255))

    labelled_img = tmp / "_intro_frame.png"
    canvas.save(str(labelled_img))

    # 5. Encode: still image + audio → video (keep full audio length, min 5s)
    video_dur = max(audio_dur, 5.0)

    ok = _run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(labelled_img),
        "-i", audio,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(video_dur),
        "-shortest",
        str(output_path),
    ], "intro-video")

    labelled_img.unlink(missing_ok=True)
    for p in [tts_wav, mixed_wav]:
        p.unlink(missing_ok=True)

    if ok and output_path.exists():
        sz = output_path.stat().st_size / 1_048_576
        print(f"    Intro: {output_path.name} ({sz:.1f} MB, {audio_dur:.1f}s audio)")
        return output_path
    return None
