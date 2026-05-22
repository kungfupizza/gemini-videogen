"""
ShowConfig — loads a show's lore.md + characters/*.md into structured dataclasses.

Directory layout expected:
    <config_dir>/
        lore.md
        characters/
            protagonist.md
            companion.md
            ...
        brand/
            intro_waving_ig.png   (Instagram brand card)
            intro_card_yt.png     (YouTube brand card)
            chime.wav
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sections(text: str) -> dict[str, str]:
    """Split a markdown file into {heading: body} by ## headings.

    The top-level # heading is stored under the key "title".
    Uses a simple line-by-line scan — no heavy markdown library needed.
    """
    sections: dict[str, str] = {}
    current_key: Optional[str] = None
    current_lines: list[str] = []

    for line in text.splitlines():
        # Top-level title
        if line.startswith("# ") and "title" not in sections:
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = "title"
            current_lines = [line[2:].strip()]
        # Section heading
        elif line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CharacterConfig:
    name: str
    visual_description: str   # injected verbatim into Veo3 prompts
    voice_description: str    # injected into audio cues
    personality: str          # injected into story system prompt
    reference_image: Optional[Path] = None  # path to a PNG for Imagen seeding


@dataclass
class ShowConfig:
    title: str
    world_description: str
    universe_rules: str
    art_style: str
    ship_description: Optional[str]
    characters: list[CharacterConfig] = field(default_factory=list)
    brand_dir: Path = field(default_factory=Path)
    config_dir: Path = field(default_factory=Path)

    # ------------------------------------------------------------------
    # Loader
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, config_dir: Path) -> "ShowConfig":
        """Parse lore.md and all characters/*.md in config_dir."""
        config_dir = config_dir.resolve()
        lore_path = config_dir / "lore.md"
        if not lore_path.exists():
            raise FileNotFoundError(
                f"lore.md not found in {config_dir}. "
                "Run `gemini-videogen init` to create a show config."
            )

        lore = _parse_sections(lore_path.read_text())

        title = lore.get("title", "My Show")
        world_description = lore.get("world", "")
        universe_rules = lore.get("universe rules", "")
        art_style = lore.get("art style", "3D cartoon animation style, vibrant colours, Pixar-quality rendering")
        ship_description: Optional[str] = lore.get("ship / vehicle (optional)") or lore.get("ship / vehicle") or None

        # Load characters
        chars: list[CharacterConfig] = []
        chars_dir = config_dir / "characters"
        if chars_dir.exists():
            for md_file in sorted(chars_dir.glob("*.md")):
                char = _load_character(md_file, config_dir)
                if char is not None:
                    chars.append(char)

        if not chars:
            raise ValueError(
                f"No character files found in {chars_dir}. "
                "Add at least one *.md file under characters/."
            )

        brand_dir = config_dir / "brand"

        return cls(
            title=title,
            world_description=world_description,
            universe_rules=universe_rules,
            art_style=art_style,
            ship_description=ship_description if ship_description else None,
            characters=chars,
            brand_dir=brand_dir,
            config_dir=config_dir,
        )

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def characters_prompt(self) -> str:
        """One-line character block for Veo3 prompts.

        Format: "Name: visual description. Name2: visual description2."
        Strips a leading "Name:" from the visual_description if the character
        file author accidentally started the description with the character name.
        """
        parts = []
        for c in self.characters:
            desc = c.visual_description.rstrip(".")
            # Remove a leading "CharName:" prefix if present (common copy-paste)
            prefix = f"{c.name}:"
            if desc.startswith(prefix):
                desc = desc[len(prefix):].lstrip()
            parts.append(f"{c.name}: {desc}.")
        return " ".join(parts)

    def story_system_prompt(self) -> str:
        """Full system prompt for Gemini story generation."""
        char_block = "\n".join(
            f"- {c.name}: {c.personality}"
            for c in self.characters
        )
        voice_block = "\n".join(
            f"- {c.name}: {c.voice_description}"
            for c in self.characters
        )
        return f"""You are the creative director for "{self.title}", a kid-friendly animated series for ages 6-12.
You write tight, emotionally resonant micro-episodes.

WORLD:
{self.world_description}

CHARACTERS:
{char_block}

CHARACTER VOICES:
{voice_block}

UNIVERSE RULES:
{self.universe_rules}

SCENE FLOW RULES:
- Each scene must flow naturally into the next with no jarring cuts.
- The camera position and character location at the END of one scene must match the START of the next.
- Build a clear story arc: arrive → discover → react → explore deeper → challenge/funny moment → depart.
- The episode should feel like one continuous journey, not disconnected clips.
- Use transitional actions (walking toward something, following a sound, chasing something) to link scenes."""


def _load_character(md_file: Path, config_dir: Path) -> Optional[CharacterConfig]:
    """Parse a single character markdown file."""
    sections = _parse_sections(md_file.read_text())
    name = sections.get("title", md_file.stem.replace("_", " ").title())

    visual = sections.get("visual description", "")
    voice = sections.get("voice", "")
    personality = sections.get("personality", "")

    if not visual:
        return None

    # Optional reference image
    ref_image: Optional[Path] = None
    ref_str = sections.get("reference image", "")
    if ref_str:
        # Strip markdown formatting, take first non-empty line
        for raw_line in ref_str.splitlines():
            line = raw_line.strip().lstrip("`").rstrip("`")
            if line:
                candidate = config_dir / line
                if candidate.exists():
                    ref_image = candidate
                break

    return CharacterConfig(
        name=name,
        visual_description=visual,
        voice_description=voice,
        personality=personality,
        reference_image=ref_image,
    )
