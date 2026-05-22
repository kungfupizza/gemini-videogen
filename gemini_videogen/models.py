"""
Data models shared across the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Scene:
    number: int
    title: str
    description: str
    action: str
    mood: str
    camera_style: str
    duration: int          # 4 | 6 | 8 seconds
    narration: str         # narrator voiceover text
    veo_prompt: str = ""   # filled by build_veo_prompt()

    # Per-character dialogue — keys are character names as they appear in lore.md.
    # The pipeline stores the first two characters under the generic keys
    # "char0_says" and "char1_says" when serialising to JSON for backwards compat.
    dialogue: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties used by the original source's naming scheme
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict, fallback_duration: int = 8, character_names: list[str] | None = None) -> "Scene":
        """Deserialise a scene dict.

        Accepts the generic ``dialogue`` mapping **or** the legacy
        ``char0_says`` / ``char1_says`` keys that older story.json files
        (and the Gemini prompt output) may produce.
        """
        names = character_names or []

        # Build dialogue dict from whatever keys are present
        dialogue: dict[str, str] = dict(d.get("dialogue") or {})

        # Accept char0_says / char1_says as fallback
        for idx, name in enumerate(names[:2]):
            key = f"char{idx}_says"
            if key in d and name not in dialogue:
                dialogue[name] = d[key]

        # Also accept legacy single-field "dialogue" string
        if not dialogue and names and isinstance(d.get("dialogue"), str):
            dialogue[names[0]] = d["dialogue"]

        return cls(
            number=d["number"],
            title=d["title"],
            description=d["description"],
            action=d["action"],
            mood=d["mood"],
            camera_style=d["camera_style"],
            duration=d.get("duration", fallback_duration),
            narration=d["narration"],
            veo_prompt=d.get("veo_prompt", ""),
            dialogue=dialogue,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Episode:
    title: str
    idea: str
    logline: str
    moral: str
    scenes: list[Scene] = field(default_factory=list)


@dataclass
class SeriesEpisode:
    number: int
    location: str
    idea: str
    hook: str
    instagram_path: Optional[Path] = None
    youtube_clip_path: Optional[Path] = None
    instagram_caption: str = ""


@dataclass
class Series:
    storyline: str
    title: str
    tagline: str
    episodes: list[SeriesEpisode]
    youtube_caption: str = ""
