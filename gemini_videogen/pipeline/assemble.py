"""
Video assembly — ffmpeg wrappers.

- assemble_video()   concatenate scene clips into a single episode
- prepend_intro()    prepend a brand intro using concat filter (handles fps mismatch)
- _run()             thin subprocess wrapper shared by this module and brand.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# ffmpeg helper
# ---------------------------------------------------------------------------

def _run(cmd: list[str], label: str) -> bool:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error ({label}):\n{result.stderr[-800:]}")
        return False
    return True


def _ffmpeg_available() -> bool:
    return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

def assemble_video(
    scene_paths: list[Path],
    output_path: Path,
    target_duration: int,
    source_total: Optional[int] = None,
) -> bool:
    """Concatenate clips and encode into a single video.

    Skips the hard trim when source overshoots target by 2 s or less —
    this avoids cutting mid-sentence on the last clip.
    """
    if not _ffmpeg_available():
        print("ERROR: ffmpeg not found. Install: brew install ffmpeg  or  apt install ffmpeg")
        return False

    tmp_dir = output_path.parent
    concat_txt = tmp_dir / "_concat_list.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p.absolute()}'" for p in scene_paths) + "\n"
    )

    overshoot = (source_total or 0) - target_duration
    trim_args = [] if overshoot <= 2 else ["-t", str(target_duration)]

    ok = _run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        *trim_args,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ], "assemble")

    concat_txt.unlink(missing_ok=True)

    if ok:
        size_mb = output_path.stat().st_size / 1_048_576
        print(f"  Final video: {output_path} ({size_mb:.1f} MB)")
    return ok


# ---------------------------------------------------------------------------
# Intro prepender
# ---------------------------------------------------------------------------

def prepend_intro(intro_path: Path, episode_path: Path, output_path: Path) -> bool:
    """Prepend intro_path to the front of episode_path → output_path.

    Uses concat FILTER (not demuxer) to handle fps/codec mismatches between
    the brand intro (still image encoded) and the Veo3 scene clips.
    """
    return _run([
        "ffmpeg", "-y",
        "-i", str(intro_path),
        "-i", str(episode_path),
        "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ], "prepend-intro")
