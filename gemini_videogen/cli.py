"""
gemini-videogen — Idea to Video CLI powered by Google Veo3.

Commands:
    gemini-videogen init "My show idea" [--output ./my_show]
    gemini-videogen run  "Episode idea" --show ./my_show [--platform instagram|youtube] [--dry-run] [--skip-video] [--frames-only]
    gemini-videogen series "Storyline: loc1, loc2, ..." --show ./my_show [--dry-run] [--skip-video]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    """Generate a show config from a natural language idea using Gemini."""
    import gemini_videogen  # trigger .env load

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("ERROR: Set GOOGLE_API_KEY or GEMINI_API_KEY before running init.")

    from google import genai
    from google.genai import types as gentypes
    from gemini_videogen.pipeline.story import GEMINI_MODEL

    idea = args.idea
    output_dir = Path(args.output) if args.output else _idea_to_dir(idea)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating show config for: {idea!r}")
    print(f"Output directory: {output_dir}\n")

    client = genai.Client(api_key=api_key)

    prompt = f"""You are a creative director. A user wants to create an animated series with this concept:

"{idea}"

Generate a complete show config. Return ONLY valid JSON — no markdown, no commentary:
{{
  "show_title": "Catchy show title (3-5 words)",
  "world_description": "2-3 paragraphs describing the show's world, setting, tone, and what makes it unique. This is injected into every story generation prompt.",
  "universe_rules": "Bullet list of 4-6 rules:\\n- How episodes open\\n- How episodes close\\n- Recurring elements\\n- Content tone and limits\\n- Any recurring vehicle or location",
  "art_style": "One sentence describing the visual style for Veo3 video generation. E.g. '3D cartoon animation style, vibrant kid-friendly colours, bold clean outlines, Pixar-quality rendering, expressive faces, smooth motion, cinematic lighting'",
  "ship_description": "Optional: description of a recurring vehicle or base (null if none)",
  "characters": [
    {{
      "name": "Character name",
      "visual_description": "Full visual description injected verbatim into Veo3 prompts. Be specific about appearance, clothing, distinguishing features. At least 3 sentences.",
      "voice_description": "One sentence: voice gender, accent, tone, quirks. E.g. 'Warm upbeat American girl voice, age 10, curious and expressive'",
      "personality": "2-3 sentences for story generation context — what drives them, how they react, their relationship with others."
    }}
  ]
}}

Generate 2-4 characters appropriate for the concept. Make the config rich enough to produce compelling episodes."""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gentypes.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    raw = json.loads(response.text)

    # Write lore.md
    lore_path = output_dir / "lore.md"
    ship_section = ""
    if raw.get("ship_description"):
        ship_section = f"\n## Ship / Vehicle (optional)\n{raw['ship_description']}\n"

    lore_path.write_text(
        f"# {raw['show_title']}\n\n"
        f"## World\n{raw['world_description']}\n\n"
        f"## Universe Rules\n{raw['universe_rules']}\n\n"
        f"## Art Style\n{raw['art_style']}\n"
        f"{ship_section}"
    )
    print(f"  Created: {lore_path}")

    # Write characters/*.md
    chars_dir = output_dir / "characters"
    chars_dir.mkdir(exist_ok=True)

    for char in raw["characters"]:
        slug = "".join(c if c.isalnum() else "_" for c in char["name"].lower()).strip("_")
        char_path = chars_dir / f"{slug}.md"
        char_path.write_text(
            f"# {char['name']}\n\n"
            f"## Visual Description\n{char['visual_description']}\n\n"
            f"## Voice\n{char['voice_description']}\n\n"
            f"## Personality\n{char['personality']}\n\n"
            f"## Reference Image\n"
            f"<!-- Optional: add a PNG at characters/{slug}.png and update this path -->\n"
        )
        print(f"  Created: {char_path}")

    # Write brand/README.md
    brand_dir = output_dir / "brand"
    brand_dir.mkdir(exist_ok=True)
    (brand_dir / "README.md").write_text(
        f"# Brand Assets for {raw['show_title']}\n\n"
        "Add the following files to this directory to enable the brand intro:\n\n"
        "## Required files\n\n"
        "| File | Size | Description |\n"
        "|------|------|-------------|\n"
        "| `intro_waving_ig.png` | 720x1280 | Instagram (9:16) brand card image |\n"
        "| `intro_card_yt.png`   | 1280x720 | YouTube (16:9) brand card image |\n"
        "| `chime.wav`           | any      | Short intro chime sound |\n\n"
        "## Optional: character reference images\n\n"
        "Add character PNGs to the `characters/` directory and update the "
        "`## Reference Image` section in each character's `.md` file.\n\n"
        "```\n"
        "characters/\n"
    )
    for char in raw["characters"]:
        slug = "".join(c if c.isalnum() else "_" for c in char["name"].lower()).strip("_")
        with open(brand_dir / "README.md", "a") as f:
            f.write(f"    {slug}.png\n")
    with open(brand_dir / "README.md", "a") as f:
        f.write("```\n")
    print(f"  Created: {brand_dir}/README.md")

    print(f"\nShow config created in: {output_dir.absolute()}")
    print("\nNext steps:")
    print(f"  1. Review and edit {output_dir}/lore.md and characters/*.md")
    print(f"  2. Add brand assets to {output_dir}/brand/  (see brand/README.md)")
    print(f"  3. Run an episode:")
    print(f"       gemini-videogen run \"Your episode idea\" --show {output_dir}")


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    import gemini_videogen  # trigger .env load

    from gemini_videogen.config import ShowConfig
    from gemini_videogen.pipeline.series import run_episode

    show_dir = Path(args.show)
    show_config = ShowConfig.load(show_dir)
    output_dir = Path(args.output) if args.output else None

    run_episode(
        idea=args.idea,
        show_config=show_config,
        platform=args.platform,
        dry_run=args.dry_run,
        skip_video=args.skip_video,
        frames_only=args.frames_only,
        story_file=args.story_file if hasattr(args, "story_file") else None,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# series command
# ---------------------------------------------------------------------------

def cmd_series(args: argparse.Namespace) -> None:
    import gemini_videogen  # trigger .env load

    from gemini_videogen.config import ShowConfig
    from gemini_videogen.pipeline.series import DEFAULT_LOCATIONS, run_series

    show_dir = Path(args.show)
    show_config = ShowConfig.load(show_dir)
    output_dir = Path(args.output) if args.output else None

    # Parse "Storyline: loc1, loc2, loc3" format
    raw = args.storyline
    if ":" in raw:
        storyline, _, locs_str = raw.partition(":")
        storyline = storyline.strip()
        locations = [l.strip() for l in locs_str.split(",") if l.strip()]
    else:
        storyline = raw.strip()
        locations = DEFAULT_LOCATIONS

    if not locations:
        locations = DEFAULT_LOCATIONS

    run_series(
        storyline=storyline,
        locations=locations,
        show_config=show_config,
        dry_run=args.dry_run,
        skip_video=args.skip_video,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _idea_to_dir(idea: str) -> Path:
    slug = "".join(c if c.isalnum() else "_" for c in idea.lower())[:30].strip("_")
    return Path(slug)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gemini-videogen",
        description="Idea to Video CLI powered by Google Veo3.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new show from an idea
  gemini-videogen init "A cooking adventure show for kids"

  # Generate a single episode
  gemini-videogen run "Chef Pip discovers edible flowers" --show ./example_show

  # Generate a series
  gemini-videogen series "Kitchen Adventures: Italy, Japan, Mexico" --show ./example_show

  # Dry run (story + prompts, no video API calls)
  gemini-videogen run "..." --show ./my_show --dry-run

  # YouTube format
  gemini-videogen run "..." --show ./my_show --platform youtube
        """,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── init ──
    init_p = sub.add_parser("init", help="Generate a show config from a show idea using Gemini")
    init_p.add_argument("idea", metavar="IDEA", help='Your show concept, e.g. "A cooking adventure show"')
    init_p.add_argument("--output", "-o", metavar="DIR",
                        help="Output directory (default: slug of idea)")
    init_p.set_defaults(func=cmd_init)

    # ── run ──
    run_p = sub.add_parser("run", help="Generate a single episode")
    run_p.add_argument("idea", metavar="IDEA", help='Episode idea, e.g. "Chef Pip discovers edible flowers"')
    run_p.add_argument("--show", required=True, metavar="DIR",
                       help="Path to show config directory (must contain lore.md)")
    run_p.add_argument("--platform", choices=["instagram", "youtube"], default="instagram",
                       help="Target platform — controls aspect ratio (default: instagram)")
    run_p.add_argument("--output", "-o", metavar="DIR",
                       help="Output base directory (default: ./output)")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Generate story and prompts only; skip all Veo3 API calls")
    run_p.add_argument("--skip-video", action="store_true",
                       help="Stop after prompt generation (no video API calls)")
    run_p.add_argument("--frames-only", action="store_true",
                       help="Generate Imagen base frames only; skip Veo3 video generation")
    run_p.add_argument("--story-file", metavar="PATH",
                       help="Load story from an existing story.json to skip story generation")
    run_p.set_defaults(func=cmd_run)

    # ── series ──
    series_p = sub.add_parser("series", help="Generate a multi-episode series")
    series_p.add_argument("storyline", metavar="STORYLINE",
                          help='"Storyline: loc1, loc2, loc3"  or just a storyline (uses default locations)')
    series_p.add_argument("--show", required=True, metavar="DIR",
                          help="Path to show config directory")
    series_p.add_argument("--output", "-o", metavar="DIR",
                          help="Output base directory (default: ./output)")
    series_p.add_argument("--dry-run", action="store_true",
                          help="Generate stories and prompts only; skip all API video calls")
    series_p.add_argument("--skip-video", action="store_true",
                          help="Stop after prompt generation")
    series_p.set_defaults(func=cmd_series)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
