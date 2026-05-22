"""
gemini-videogen MCP server.

Exposes the video generation pipeline as Claude tools so Claude can orchestrate
Veo3 episode and series generation end-to-end.

Run via MCP:
    gemini-videogen-mcp

Or register in Claude Desktop's config:
    {
      "mcpServers": {
        "gemini-videogen": {
          "command": "gemini-videogen-mcp",
          "env": { "GOOGLE_API_KEY": "your_key_here" }
        }
      }
    }
"""

from __future__ import annotations

import io
import contextlib
import os
import sys
from pathlib import Path
from typing import Optional

import gemini_videogen  # triggers .env load  # noqa: F401

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "MCP SDK not installed. Run: uv sync --extra mcp",
        file=sys.stderr,
    )
    sys.exit(1)


mcp = FastMCP(
    "gemini-videogen",
    instructions=(
        "Generate AI-animated video episodes and series using Google Veo3. "
        "Start with init_show to create a show config, then use run_episode "
        "or generate_series to produce videos. "
        "Always confirm the show_dir exists before generating video. "
        "Video generation takes several minutes per scene — set dry_run=True first "
        "to preview the story and prompts without spending API quota."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture(fn, *args, **kwargs) -> str:
    """Run fn(*args, **kwargs), capture stdout, return it as a string."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            result = fn(*args, **kwargs)
        except SystemExit as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {e}"
    out = buf.getvalue()
    if result is not None:
        out += f"\nOutput file: {result}"
    return out.strip()


def _require_api_key() -> Optional[str]:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        return "ERROR: GOOGLE_API_KEY is not set. Add it to the MCP server env config."
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def init_show(
    idea: str,
    output_dir: str = "",
) -> str:
    """Generate a complete show config from a one-line show concept.

    Creates lore.md, characters/*.md, and brand/README.md in the output directory.
    Call this once to set up a new show, then use run_episode or generate_series.

    Args:
        idea: Your show concept, e.g. "A space adventure show for kids starring a
              young astronaut and her AI dog who explore the galaxy"
        output_dir: Where to write the config files. Defaults to a slug of the idea.

    Returns:
        Summary of created files and next steps.
    """
    err = _require_api_key()
    if err:
        return err

    from gemini_videogen.cli import cmd_init
    import argparse

    args = argparse.Namespace(idea=idea, output=output_dir or None)
    return _capture(cmd_init, args)


@mcp.tool()
def run_episode(
    idea: str,
    show_dir: str,
    platform: str = "instagram",
    dry_run: bool = False,
    skip_video: bool = False,
) -> str:
    """Generate a single AI-animated episode video using Google Veo3.

    Pipeline: idea → Gemini story → 6 scene prompts → Imagen frames → Veo3 clips → assembled MP4.
    Resumable: interrupted runs pick up from the last completed scene.

    Args:
        idea: The episode premise, e.g. "Chef Pip discovers edible flowers in Japan"
        show_dir: Path to show config directory (must contain lore.md and characters/).
                  Use the output_dir from init_show.
        platform: "instagram" (9:16, 45s) or "youtube" (16:9, 34s). Default: instagram.
        dry_run: If True, generates story + prompts only — no Veo3 API calls.
                 Use this to preview the episode plan before spending quota.
        skip_video: If True, stops after generating the story and Veo3 prompts.

    Returns:
        Progress log and path to the final assembled MP4 (or None on dry_run).
    """
    err = _require_api_key()
    if err:
        return err

    show_path = Path(show_dir)
    if not (show_path / "lore.md").exists():
        return (
            f"ERROR: {show_dir}/lore.md not found. "
            "Run init_show first to create a show config, or check the show_dir path."
        )

    from gemini_videogen.config import ShowConfig
    from gemini_videogen.pipeline.series import run_episode as _run_episode

    show_config = ShowConfig.load(show_path)

    return _capture(
        _run_episode,
        idea=idea,
        show_config=show_config,
        platform=platform,
        dry_run=dry_run,
        skip_video=skip_video,
    )


@mcp.tool()
def generate_series(
    storyline: str,
    show_dir: str,
    dry_run: bool = False,
    skip_video: bool = False,
) -> str:
    """Generate a full multi-episode series with Instagram Reels and YouTube variants.

    Phase A: all Instagram episodes (45s, 9:16) — ready to publish.
    Phase B: all YouTube clips (34s, 16:9) from the same stories.
    Final: YouTube compilation video + captions.md with ready-to-post captions.

    Storyline format:
        "Storyline description: Location1, Location2, Location3, Location4, Location5, Location6"
        The text before ':' is the series premise; after ':' is comma-separated episode locations.
        If no ':' is present, default locations are used.

    Args:
        storyline: Series premise with optional locations, e.g.
                   "Chef Pip travels the world learning recipes: Italy, Japan, Mexico, India, France, Peru"
        show_dir: Path to show config directory (must contain lore.md).
        dry_run: If True, generates series plan + stories only — no Veo3 API calls.
                 Recommended for a first run to review the episode plan.
        skip_video: If True, stops after story generation for all episodes.

    Returns:
        Full progress log, per-episode file paths, and captions summary.
    """
    err = _require_api_key()
    if err:
        return err

    show_path = Path(show_dir)
    if not (show_path / "lore.md").exists():
        return (
            f"ERROR: {show_dir}/lore.md not found. "
            "Run init_show first to create a show config, or check the show_dir path."
        )

    from gemini_videogen.config import ShowConfig
    from gemini_videogen.pipeline.series import DEFAULT_LOCATIONS, run_series

    show_config = ShowConfig.load(show_path)

    if ":" in storyline:
        premise, _, locs_str = storyline.partition(":")
        premise = premise.strip()
        locations = [loc.strip() for loc in locs_str.split(",") if loc.strip()]
    else:
        premise = storyline.strip()
        locations = DEFAULT_LOCATIONS

    return _capture(
        run_series,
        storyline=premise,
        locations=locations,
        show_config=show_config,
        dry_run=dry_run,
        skip_video=skip_video,
    )


@mcp.tool()
def list_outputs(output_dir: str = "output") -> str:
    """List generated episodes and series in the output directory.

    Args:
        output_dir: Base output directory to scan. Default: "./output"

    Returns:
        Tree of generated videos with file sizes.
    """
    base = Path(output_dir)
    if not base.exists():
        return f"Output directory '{output_dir}' does not exist yet. Generate an episode first."

    lines: list[str] = [f"Output directory: {base.absolute()}\n"]

    mp4s = sorted(base.rglob("*.mp4"))
    if not mp4s:
        lines.append("No videos generated yet.")
        return "\n".join(lines)

    for mp4 in mp4s:
        # Skip internal temp files
        if mp4.name.startswith("_"):
            continue
        rel = mp4.relative_to(base)
        size_mb = mp4.stat().st_size / 1_048_576
        lines.append(f"  {rel}  ({size_mb:.1f} MB)")

    lines.append(f"\nTotal: {len([m for m in mp4s if not m.name.startswith('_')])} video(s)")
    return "\n".join(lines)


@mcp.tool()
def show_episode_story(episode_dir: str) -> str:
    """Read the story.json for a generated episode — title, logline, moral, and scene plan.

    Useful for reviewing what was generated before or after video production.

    Args:
        episode_dir: Path to the episode output directory (contains story.json).

    Returns:
        Formatted episode story and scene breakdown.
    """
    import json

    story_path = Path(episode_dir) / "story.json"
    if not story_path.exists():
        return f"No story.json found in {episode_dir}. Has this episode been generated yet?"

    data = json.loads(story_path.read_text())
    lines = [
        f"Title:   {data['title']}",
        f"Logline: {data['logline']}",
        f"Moral:   {data['moral']}",
        "",
        "Scenes:",
    ]
    for scene in data.get("scenes", []):
        lines.append(f"\n  Scene {scene['number']}: {scene['title']} ({scene.get('duration', '?')}s)")
        lines.append(f"  Mood: {scene['mood']}")
        lines.append(f"  {scene['description']}")
        if scene.get("zara_says") or scene.get("protagonist_says"):
            line = scene.get("zara_says") or scene.get("protagonist_says", "")
            lines.append(f"  Protagonist: \"{line}\"")
        if scene.get("ant_says") or scene.get("companion_says"):
            line = scene.get("ant_says") or scene.get("companion_says", "")
            lines.append(f"  Companion: \"{line}\"")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
