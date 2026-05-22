"""
Episode and series orchestrators.

run_episode()  — single episode: story → prompts → frames → video → assemble → brand intro
run_series()   — multi-episode: Phase A (Instagram all eps) → Phase B (YouTube all eps) → compilation
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Optional

from google import genai

from gemini_videogen.config import ShowConfig
from gemini_videogen.models import Episode, Series, SeriesEpisode
from gemini_videogen.pipeline.assemble import assemble_video, prepend_intro
from gemini_videogen.pipeline.brand import generate_brand_intro
from gemini_videogen.pipeline.story import (
    GEMINI_MODEL,
    _placeholder_episode,
    generate_instagram_caption,
    generate_series_plan,
    generate_story,
    generate_youtube_caption,
    load_episode_from_file,
    save_progress,
)
from gemini_videogen.pipeline.video import (
    GEMINI_IMAGE_MODEL,
    VEO_MODEL_FAST,
    VEO_MODEL_FALLBACK,
    VEO_MODEL_LITE,
    VEO_MODEL_PRIMARY,
    build_veo_prompt,
    generate_scene_frame,
    generate_scene_video,
)

# ---------------------------------------------------------------------------
# Platform configs
# ---------------------------------------------------------------------------

PLATFORMS: dict[str, dict] = {
    "instagram": {
        "label": "Instagram Reels",
        "aspect_ratio": "9:16",
        "resolution": "720p",
    },
    "youtube": {
        "label": "YouTube",
        "aspect_ratio": "16:9",
        "resolution": "720p",
    },
}

INSTAGRAM_SCENE_DURATIONS = [8, 8, 8, 8, 8, 6]   # 46s source (overshoot ≤2 → no trim)
YOUTUBE_SCENE_DURATIONS   = [6, 6, 6, 6, 6, 4]   # 34s per episode
YOUTUBE_TARGET_DURATION   = 34
INSTAGRAM_TARGET_DURATION = 45

DEFAULT_LOCATIONS = ["Location 1", "Location 2", "Location 3", "Location 4", "Location 5", "Location 6"]

SEP = "=" * 62


# ---------------------------------------------------------------------------
# Single episode
# ---------------------------------------------------------------------------

def run_episode(
    idea: str,
    show_config: ShowConfig,
    platform: str = "instagram",
    dry_run: bool = False,
    skip_video: bool = False,
    frames_only: bool = False,
    story_file: Optional[str] = None,
    episode_number: Optional[int] = None,
    scene_durations: Optional[list[int]] = None,
    episode_dir: Optional[Path] = None,
    platform_suffix: str = "",
    existing_episode: Optional[Episode] = None,
    target_duration: Optional[int] = None,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Run the full episode pipeline.

    Returns the path to the final assembled video, or None on failure / dry-run.
    """
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    needs_api = not (dry_run or skip_video or frames_only)
    if not api_key and needs_api:
        sys.exit("ERROR: Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.")

    cfg = PLATFORMS[platform]
    client = genai.Client(api_key=api_key or "dry-run-placeholder")

    base_output = output_dir or Path("output")
    if episode_dir is None:
        slug = "".join(c if c.isalnum() else "_" for c in idea.lower())[:40].strip("_")
        episode_dir = base_output / slug
    episode_dir.mkdir(parents=True, exist_ok=True)

    effective_durations = scene_durations or INSTAGRAM_SCENE_DURATIONS
    effective_target = target_duration if target_duration is not None else INSTAGRAM_TARGET_DURATION
    char_names = [c.name for c in show_config.characters]

    print(f"\n{SEP}")
    print(f"  {show_config.title.upper()} — EPISODE GENERATOR")
    print(f"  Idea:     {idea}")
    print(f"  Platform: {cfg['label']} ({cfg['aspect_ratio']}, {cfg['resolution']})")
    print(f"  Output:   {episode_dir}")
    print(f"{SEP}\n")

    # ── 1. Story ──────────────────────────────────────────────────────────────
    if existing_episode is not None:
        episode = copy.deepcopy(existing_episode)
        if effective_durations:
            for i, scene in enumerate(episode.scenes):
                if i < len(effective_durations):
                    scene.duration = effective_durations[i]
            episode.scenes = episode.scenes[:len(effective_durations)]
        print("Step 1 — Reusing existing episode story.")
    elif story_file:
        print("Step 1 — Loading story from file…")
        episode = load_episode_from_file(story_file, idea, char_names)
    elif dry_run:
        print("Step 1 — [DRY RUN] Using placeholder story…")
        episode = _placeholder_episode(idea, show_config, effective_durations)
    else:
        auto_story = episode_dir / "story.json"
        if auto_story.exists():
            print("Step 1 — Resuming: story.json found, skipping story generation.")
            episode = load_episode_from_file(str(auto_story), idea, char_names)
        else:
            print("Step 1 — Generating storyline with Gemini…")
            episode = generate_story(client, idea, show_config, scene_durations=effective_durations)

    print(f"\n  Title:   {episode.title}")
    print(f"  Logline: {episode.logline}")
    print(f"  Moral:   {episode.moral}")
    print(f"  Scenes:  {len(episode.scenes)}\n")

    # ── 2. Veo3 prompts ───────────────────────────────────────────────────────
    print("Step 2 — Building Veo3 prompts…")
    total_scenes = len(episode.scenes)
    for scene in episode.scenes:
        scene.veo_prompt = build_veo_prompt(
            scene,
            show_config,
            is_first=(scene.number == 1),
            is_last=(scene.number == total_scenes),
        )
        print(f"  Scene {scene.number}: {scene.title!r} ({scene.duration}s, {scene.mood})")

    save_progress(episode_dir, episode)
    print(f"\n  Story + prompts saved to {episode_dir}/\n")

    if dry_run:
        print("[DRY RUN] Skipping video generation.")
        print(f"[DRY RUN] Would produce {len(episode.scenes)} scenes → {effective_target}s {cfg['label']} video.")
        return None

    if skip_video:
        print("[--skip-video] Stopping after prompt generation.")
        return None

    # ── 3a. Frames only ───────────────────────────────────────────────────────
    if frames_only:
        print("Step 3 — Generating base frames only (Imagen)…\n")
        for scene in episode.scenes:
            clip_path = episode_dir / f"scene{platform_suffix}_{scene.number:02d}.mp4"
            print(f"  Scene {scene.number}/{total_scenes}: {scene.title!r}")
            generate_scene_frame(
                client=client,
                scene=scene,
                output_path=clip_path,
                show_config=show_config,
                aspect_ratio=cfg["aspect_ratio"],
                is_first=(scene.number == 1),
                is_last=(scene.number == total_scenes),
                platform_suffix=platform_suffix,
            )
        print(f"\n[--frames-only] Frames saved to {episode_dir}/frame{platform_suffix}_*.png")
        return None

    # ── 3b. Frames + video clips ───────────────────────────────────────────────
    print("Step 3 — Generating scene frames (Imagen) then clips (Veo3)…")
    print(f"  Pipeline: text → Imagen frame → Veo3 animation")
    print(f"  Models: {GEMINI_IMAGE_MODEL} → {VEO_MODEL_PRIMARY} → {VEO_MODEL_FALLBACK} → {VEO_MODEL_FAST} → {VEO_MODEL_LITE}\n")

    scene_paths: list[Path] = []

    for scene in episode.scenes:
        clip_path = episode_dir / f"scene{platform_suffix}_{scene.number:02d}.mp4"
        is_first = scene.number == 1
        is_last = scene.number == total_scenes

        if clip_path.exists():
            print(f"  Scene {scene.number} — clip already exists, reusing.")
            scene_paths.append(clip_path)
            continue

        print(f"\n  Scene {scene.number}/{total_scenes}: {scene.title!r}")

        base_image = generate_scene_frame(
            client=client,
            scene=scene,
            output_path=clip_path,
            show_config=show_config,
            aspect_ratio=cfg["aspect_ratio"],
            is_first=is_first,
            is_last=is_last,
            platform_suffix=platform_suffix,
        )

        ok = generate_scene_video(
            client=client,
            scene=scene,
            output_path=clip_path,
            aspect_ratio=cfg["aspect_ratio"],
            resolution=cfg["resolution"],
            base_image=base_image,
        )

        if ok:
            scene_paths.append(clip_path)
        else:
            print(f"  WARNING: Scene {scene.number} failed — skipping from final cut.")

    if not scene_paths:
        sys.exit("ERROR: No scenes were generated successfully.")

    # ── 4. Assemble ───────────────────────────────────────────────────────────
    safe_title = "".join(c if c.isalnum() or c == "_" else "_" for c in episode.title)[:40]
    final_path = episode_dir / f"{safe_title}{platform_suffix}_{platform}.mp4"
    intro_flag = episode_dir / f"_intro_done{platform_suffix}.flag"
    needs_intro = platform == "instagram" and episode_number is not None

    all_cached = all(p.exists() for p in scene_paths)
    already_assembled = final_path.exists() and all_cached
    already_with_intro = intro_flag.exists()

    if already_assembled and (already_with_intro or not needs_intro):
        print(f"\nStep 4 — Final video already complete, skipping.")
        print(f"  {final_path}")
        return final_path

    if not already_assembled:
        source_total = sum(s.duration for s in episode.scenes[:len(scene_paths)])
        print(f"\nStep 4 — Assembling episode ({source_total}s source → target {effective_target}s)…")
        ok = assemble_video(scene_paths, final_path, effective_target, source_total=source_total)
        if not ok:
            print("ERROR: Video assembly failed.")
            return None
    else:
        print(f"\nStep 4 — Clips cached; skipping re-assembly.")

    # ── 5. Brand intro ────────────────────────────────────────────────────────
    if needs_intro and not already_with_intro:
        intro_path = episode_dir / f"_intro{platform_suffix or '_ig'}.mp4"
        print(f"\nStep 5 — Generating brand intro (Episode {episode_number})…")
        intro = generate_brand_intro(episode_number, episode.title, intro_path, show_config, platform)
        if intro:
            raw_path = final_path.with_name(final_path.stem + "_raw.mp4")
            final_path.rename(raw_path)
            if prepend_intro(intro, raw_path, final_path):
                raw_path.unlink(missing_ok=True)
                intro_flag.touch()
                print(f"  Brand intro prepended → {final_path.name}")
            else:
                raw_path.rename(final_path)

    print(f"\n{SEP}")
    print(f"  SUCCESS — Episode ready!")
    print(f"  {episode.title}")
    print(f"  {final_path}")
    print(f"{SEP}\n")
    return final_path


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def run_series(
    storyline: str,
    locations: list[str],
    show_config: ShowConfig,
    dry_run: bool = False,
    skip_video: bool = False,
    frames_only: bool = False,
    output_dir: Optional[Path] = None,
) -> None:
    """Run the full series pipeline.

    Phase A: all Instagram episodes (ready to publish).
    Phase B: all YouTube clips (same stories, shorter durations).
    Final:   YouTube compilation + captions.md.
    """
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    needs_api = not (dry_run or skip_video)
    if not api_key and needs_api:
        sys.exit("ERROR: Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.")

    client = genai.Client(api_key=api_key or "dry-run-placeholder")

    base_output = output_dir or Path("output")
    slug = "".join(c if c.isalnum() else "_" for c in storyline.lower())[:40].strip("_")
    series_dir = base_output / f"series_{slug}"
    series_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{SEP}")
    print(f"  {show_config.title.upper()} — SERIES GENERATOR")
    print(f"  Storyline: {storyline}")
    print(f"  Locations: {', '.join(locations)}")
    print(f"  Output:    {series_dir}")
    print(f"{SEP}\n")

    # ── 1. Series plan ────────────────────────────────────────────────────────
    series_json_path = series_dir / "series.json"

    if series_json_path.exists():
        print("Loading existing series plan from series.json…")
        raw = json.loads(series_json_path.read_text())
    elif dry_run:
        print("[DRY RUN] Using placeholder series plan (no API call)…")
        raw = {
            "title": f"{show_config.title}: {storyline}",
            "tagline": "An adventure in every episode.",
            "episodes": [
                {
                    "number": i + 1,
                    "location": loc,
                    "idea": (
                        f"{show_config.characters[0].name if show_config.characters else 'Our heroes'} "
                        f"visits {loc}"
                    ),
                    "hook": f"The most amazing {loc} adventure awaits!",
                }
                for i, loc in enumerate(locations)
            ],
        }
    else:
        print("Generating series plan with Gemini…")
        raw = generate_series_plan(client, storyline, locations, show_config)
        series_json_path.write_text(json.dumps({
            "storyline": storyline,
            "title": raw["title"],
            "tagline": raw["tagline"],
            "episodes": raw["episodes"],
        }, indent=2))

    series_episodes = [
        SeriesEpisode(
            number=ep["number"],
            location=ep["location"],
            idea=ep["idea"],
            hook=ep["hook"],
        )
        for ep in raw["episodes"]
    ]
    series_title = raw["title"]
    series_tagline = raw["tagline"]

    print(f"\n  Series Title: {series_title}")
    print(f"  Tagline:      {series_tagline}")
    print(f"  Episodes:     {len(series_episodes)}\n")
    for ep in series_episodes:
        print(f"    Ep {ep.number}: [{ep.location}] {ep.idea}")
    print()

    # ── Phase A: Instagram ────────────────────────────────────────────────────
    print(f"{SEP}")
    print(f"  PHASE A — Instagram Reels ({len(series_episodes)} episodes)")
    print(f"{SEP}\n")

    episode_objects: dict[int, Optional[Episode]] = {}
    char_names = [c.name for c in show_config.characters]

    for series_ep in series_episodes:
        n = series_ep.number
        loc_slug = "".join(c if c.isalnum() else "_" for c in series_ep.location.lower())[:20]
        ep_dir = series_dir / f"ep{n:02d}_{loc_slug}"
        ep_dir.mkdir(parents=True, exist_ok=True)

        print(f"--- Instagram Ep {n}/{len(series_episodes)}: {series_ep.location} ---")

        episode_obj: Optional[Episode] = None
        try:
            ig_path = run_episode(
                idea=series_ep.idea,
                show_config=show_config,
                platform="instagram",
                dry_run=dry_run,
                skip_video=skip_video,
                frames_only=frames_only,
                scene_durations=INSTAGRAM_SCENE_DURATIONS,
                episode_dir=ep_dir,
                platform_suffix="",
                target_duration=INSTAGRAM_TARGET_DURATION,
                episode_number=n,
                output_dir=base_output,
            )
            series_ep.instagram_path = ig_path

            story_path = ep_dir / "story.json"
            if story_path.exists():
                episode_obj = load_episode_from_file(str(story_path), series_ep.idea, char_names)

        except Exception as e:
            print(f"  ERROR generating Instagram episode {n}: {e}")

        episode_objects[n] = episode_obj

        try:
            if episode_obj is not None and not dry_run:
                print(f"\n  Generating Instagram caption for episode {n}…")
                series_ep.instagram_caption = generate_instagram_caption(
                    client, show_config, series_ep.location, series_ep.hook, episode_obj
                )
                print(f"  Caption generated ({len(series_ep.instagram_caption)} chars).")
        except Exception as e:
            print(f"  ERROR generating caption for episode {n}: {e}")

    # ── Phase B: YouTube ──────────────────────────────────────────────────────
    youtube_clip_paths: list[Path] = []
    youtube_total_duration = len(series_episodes) * YOUTUBE_TARGET_DURATION

    if not frames_only:
        print(f"\n{SEP}")
        print(f"  PHASE B — YouTube clips ({len(series_episodes)} episodes)")
        print(f"{SEP}\n")

        for series_ep in series_episodes:
            n = series_ep.number
            loc_slug = "".join(c if c.isalnum() else "_" for c in series_ep.location.lower())[:20]
            ep_dir = series_dir / f"ep{n:02d}_{loc_slug}"
            episode_obj = episode_objects.get(n)

            print(f"--- YouTube Ep {n}/{len(series_episodes)}: {series_ep.location} "
                  f"({YOUTUBE_TARGET_DURATION}s target) ---")
            try:
                yt_path = run_episode(
                    idea=series_ep.idea,
                    show_config=show_config,
                    platform="youtube",
                    dry_run=dry_run,
                    skip_video=skip_video,
                    frames_only=frames_only,
                    scene_durations=YOUTUBE_SCENE_DURATIONS,
                    episode_dir=ep_dir,
                    platform_suffix="_yt",
                    existing_episode=episode_obj,
                    target_duration=YOUTUBE_TARGET_DURATION,
                    output_dir=base_output,
                )
                series_ep.youtube_clip_path = yt_path
                if yt_path is not None:
                    youtube_clip_paths.append(yt_path)
            except Exception as e:
                print(f"  ERROR generating YouTube clip for episode {n}: {e}")

    # ── YouTube compilation ───────────────────────────────────────────────────
    if not dry_run and not skip_video and not frames_only and youtube_clip_paths:
        print(f"\n{SEP}")
        print(f"  ASSEMBLING {youtube_total_duration}s YouTube compilation…")
        print(f"{SEP}")

        safe_title = "".join(c if c.isalnum() or c == "_" else "_" for c in series_title)[:40]
        youtube_final = series_dir / f"{safe_title}_youtube.mp4"
        ok = assemble_video(youtube_clip_paths, youtube_final, youtube_total_duration)
        if ok:
            print(f"\n  YouTube compilation ready: {youtube_final}")

    # ── Captions ──────────────────────────────────────────────────────────────
    youtube_caption = ""
    if not dry_run:
        try:
            print(f"\n  Generating YouTube series caption…")
            ep_dicts = [
                {"number": ep.number, "location": ep.location, "idea": ep.idea}
                for ep in series_episodes
            ]
            youtube_caption = generate_youtube_caption(
                client, show_config, series_title, series_tagline, storyline,
                ep_dicts, YOUTUBE_TARGET_DURATION,
            )
            print(f"  YouTube caption generated ({len(youtube_caption)} chars).")
        except Exception as e:
            print(f"  ERROR generating YouTube caption: {e}")

    captions_path = series_dir / "captions.md"
    lines = [f"# {series_title} — Captions\n\n_{series_tagline}_\n"]
    for ep in series_episodes:
        lines.append(f"\n---\n\n## Episode {ep.number}: {ep.location}\n\n**Idea:** {ep.idea}\n\n")
        if ep.instagram_caption:
            lines.append("### Instagram Caption\n\n" + ep.instagram_caption + "\n")
        else:
            lines.append("_Instagram caption not generated._\n")
    lines.append("\n---\n\n## YouTube Compilation Caption\n\n")
    lines.append(youtube_caption if youtube_caption else "_YouTube caption not generated._\n")
    captions_path.write_text("".join(lines))
    print(f"\n  Captions saved to: {captions_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  SERIES COMPLETE — {series_title}")
    print(f"  {series_tagline}")
    print(f"  Output directory: {series_dir}")
    print()
    for ep in series_episodes:
        print(f"  Ep {ep.number} [{ep.location}]")
        print(f"    Instagram: {ep.instagram_path or '(not generated)'}")
        print(f"    YouTube:   {ep.youtube_clip_path or '(not generated)'}")
    print(f"{SEP}\n")
