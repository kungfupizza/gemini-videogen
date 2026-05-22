"""
Story generation — uses Gemini to produce a scene-by-scene episode plan in JSON.

All prompts are built from ShowConfig — no hardcoded show-specific content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as gentypes

from gemini_videogen.config import ShowConfig
from gemini_videogen.models import Episode, Scene

GEMINI_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_SCENE_DURATIONS = [8, 8, 8, 8, 8, 6]  # Instagram default — matches series.py constant


def generate_story(
    client: genai.Client,
    idea: str,
    show_config: ShowConfig,
    scene_durations: list[int] | None = None,
) -> Episode:
    """Use Gemini to produce a scene-by-scene episode plan in JSON."""
    durations = scene_durations or _DEFAULT_SCENE_DURATIONS
    num_scenes = len(durations)
    duration_list = ", ".join(f"{d}s" for d in durations)

    char_names = [c.name for c in show_config.characters]
    char_says_schema = "\n".join(
        f'      "char{i}_says": "{c.name}\'s spoken line (max 10 words) — or empty string"'
        for i, c in enumerate(show_config.characters)
    )

    system_prompt = show_config.story_system_prompt()

    prompt = f"""{system_prompt}

EPISODE IDEA: "{idea}"

Write exactly {num_scenes} scenes with durations [{duration_list}] (total ~{sum(durations)}s).

Return ONLY valid JSON — no markdown, no commentary:
{{
  "title": "Episode title (max 8 words)",
  "logline": "One exciting sentence summary",
  "moral": "The lesson or feeling the episode leaves with",
  "scenes": [
    {{
      "number": 1,
      "title": "Short scene title",
      "description": "2-3 sentence visual description of what the viewer sees. WHERE we are and HOW this scene connects to the previous one.",
      "action": "Specific physical actions — what characters are doing, and how they move into the next scene",
{char_says_schema},
      "mood": "Single emotional tone word (wonder | excitement | nervous | funny | triumph | curious)",
      "camera_style": "Camera framing and movement that flows naturally from the previous scene",
      "duration": {durations[0]},
      "narration": "Narrator voiceover (1-2 sentences, warm storytelling voice, bridges this scene to the next)"
    }}
  ]
}}

Durations must be exactly: {', '.join(str(d) for d in durations)} for scenes 1-{num_scenes}.
Ensure the episode follows the universe rules above for opening and closing scenes."""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gentypes.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    raw = json.loads(response.text)
    raw_scenes = raw["scenes"]

    # Sort by scene number and re-number 1..N to guard against Gemini skipping
    raw_scenes.sort(key=lambda s: s.get("number", 99))
    for i, s in enumerate(raw_scenes):
        s["number"] = i + 1

    if len(raw_scenes) < num_scenes:
        raise ValueError(
            f"Gemini returned {len(raw_scenes)} scenes, expected {num_scenes}. Re-run to retry."
        )

    scenes: list[Scene] = []
    for i, s in enumerate(raw_scenes[:num_scenes]):
        scenes.append(
            Scene.from_dict(
                s,
                fallback_duration=durations[i] if i < len(durations) else 8,
                character_names=char_names,
            )
        )

    return Episode(
        title=raw["title"],
        idea=idea,
        logline=raw["logline"],
        moral=raw["moral"],
        scenes=scenes,
    )


def generate_series_plan(
    client: genai.Client,
    storyline: str,
    locations: list[str],
    show_config: ShowConfig,
) -> dict:
    """Ask Gemini to expand a storyline into per-location episode ideas.

    Returns raw dict with keys: title, tagline, episodes (list of dicts).
    """
    locations_json = json.dumps(locations)

    prompt = f"""You are the creative director for "{show_config.title}", a kid-friendly animated series for ages 6-12.

SERIES STORYLINE: "{storyline}"
WORLD: {show_config.world_description}
LOCATIONS / EPISODES: {locations_json}

Expand this storyline into exactly {len(locations)} episodes, one per location.
Each episode idea must be vivid and specific to the location. Keep ideas punchy — one sentence max.

Return ONLY valid JSON — no markdown, no commentary:
{{
  "title": "Series title (max 6 words, catchy)",
  "tagline": "One-line series tagline (max 12 words)",
  "episodes": [
    {{
      "number": 1,
      "location": "{locations[0]}",
      "idea": "Specific punchy episode idea for {locations[0]}",
      "hook": "One punchy sentence that makes you want to watch"
    }}
  ]
}}

Generate exactly {len(locations)} episodes, one for each location in order: {', '.join(locations)}."""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gentypes.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return json.loads(response.text)


def generate_instagram_caption(
    client: genai.Client,
    show_config: ShowConfig,
    location: str,
    hook: str,
    episode: Episode,
) -> str:
    prompt = f"""Write an Instagram Reels caption for this episode of "{show_config.title}".

EPISODE: "{episode.title}"
LOCATION: {location}
HOOK: {hook}
LOGLINE: {episode.logline}
MORAL: {episode.moral}

Requirements:
- Start with an emoji-rich hook line that grabs attention instantly
- 2-3 lines of warm, fun storytelling about what happens
- Mention {location} and the main characters
- 20-25 relevant hashtags (mix of broad and niche)
- End with a clear CTA: "Follow for more episodes!" or similar
- Tone: warm, fun, family-friendly, maximum 400 words
- No extra explanation — just the caption text ready to post"""

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


def generate_youtube_caption(
    client: genai.Client,
    show_config: ShowConfig,
    series_title: str,
    tagline: str,
    storyline: str,
    episodes: list[dict],
    episode_duration: int,
) -> str:
    episode_list = "\n".join(
        f"  Episode {ep['number']}: {ep['location']} — {ep['idea']}"
        for ep in episodes
    )
    timestamps = []
    for ep in episodes:
        secs = (ep["number"] - 1) * episode_duration
        mm, ss = divmod(secs, 60)
        timestamps.append(f"  {mm:02d}:{ss:02d} — {ep['location']}: {ep['idea']}")

    prompt = f"""Write a YouTube video description for this compilation video of "{show_config.title}".

SERIES TITLE: "{series_title}"
SERIES TAGLINE: "{tagline}"
STORYLINE: "{storyline}"

EPISODES:
{episode_list}

TIMESTAMPS:
{chr(10).join(timestamps)}

Requirements:
- Start with an SEO-optimised title suggestion [Suggested Title: ...]
- Include the timestamps section exactly as provided
- 3-4 engaging paragraphs about the series
- 15-20 hashtags optimised for YouTube search
- Tone: engaging, optimised for search, family-friendly
- No extra explanation — just the description text ready to post"""

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# Dry-run placeholder
# ---------------------------------------------------------------------------

def _placeholder_episode(idea: str, show_config: ShowConfig, scene_durations: list[int]) -> Episode:
    """Minimal offline episode for dry-run testing."""
    chars = show_config.characters
    scenes = [
        Scene(
            number=i + 1,
            title=f"Scene {i + 1}",
            description=f"[Placeholder] Scene {i + 1} of: {idea}",
            action="The characters explore their surroundings.",
            mood=["wonder", "excitement", "curious", "nervous", "triumph", "joy"][i % 6],
            camera_style=["wide establishing shot", "close-up", "tracking shot",
                          "two-shot", "over-the-shoulder", "wide shot"][i % 6],
            duration=scene_durations[i] if i < len(scene_durations) else 8,
            narration=f"And so the adventure of scene {i + 1} began…",
            dialogue={c.name: f"Placeholder line for {c.name}!" for j, c in enumerate(chars) if j < 2},
        )
        for i in range(len(scene_durations))
    ]
    return Episode(
        title=f"{show_config.title}: {idea}",
        idea=idea,
        logline="An adventure unfolds one scene at a time.",
        moral="Curiosity and friendship make any challenge possible.",
        scenes=scenes,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def save_progress(episode_dir: Path, episode: Episode) -> None:
    """Persist story + prompts so a run can be resumed after interruption."""
    story_data = {
        "title": episode.title,
        "idea": episode.idea,
        "logline": episode.logline,
        "moral": episode.moral,
        "scenes": [s.to_dict() for s in episode.scenes],
    }
    (episode_dir / "story.json").write_text(json.dumps(story_data, indent=2))

    prompts_data = [
        {"scene": s.number, "title": s.title, "duration": s.duration, "prompt": s.veo_prompt}
        for s in episode.scenes
    ]
    (episode_dir / "prompts.json").write_text(json.dumps(prompts_data, indent=2))


def load_episode_from_file(
    path: str | Path, idea: str, character_names: list[str] | None = None
) -> Episode:
    """Resume from a previously saved story.json."""
    data = json.loads(Path(path).read_text())
    scenes = [Scene.from_dict(s, character_names=character_names) for s in data["scenes"]]
    return Episode(
        title=data["title"],
        idea=idea or data.get("idea", ""),
        logline=data["logline"],
        moral=data["moral"],
        scenes=scenes,
    )
