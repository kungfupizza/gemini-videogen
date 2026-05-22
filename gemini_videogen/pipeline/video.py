"""
Video generation pipeline.

- generate_scene_frame()  — Imagen reference frame (character consistency anchor)
- generate_scene_video()  — Veo3 animation with model fallback cascade
- build_veo_prompt()      — assembles a rich prompt from ShowConfig
- build_image_prompt()    — static composition prompt for Imagen
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as gentypes

from gemini_videogen.config import ShowConfig
from gemini_videogen.models import Scene

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

# Cascade tried in order until one succeeds.
VEO_MODEL_PRIMARY  = "veo-3.1-generate-preview"
VEO_MODEL_FALLBACK = "veo-3.0-generate-001"
VEO_MODEL_FAST     = "veo-3.0-fast-generate-001"
VEO_MODEL_LITE     = "veo-3.0-lite-generate-preview"

GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

POLL_INTERVAL = 15   # seconds between operation status checks
MAX_WAIT      = 600  # give up after 10 minutes per scene


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_veo_prompt(
    scene: Scene,
    show_config: ShowConfig,
    is_first: bool = False,
    is_last: bool = False,
) -> str:
    """Compose a rich Veo3 prompt from ShowConfig — no hardcoded show content."""
    parts: list[str] = [show_config.art_style]

    # Episode open/close special staging from universe rules
    if is_first and show_config.ship_description:
        parts.append(
            f"Opening scene: {show_config.ship_description} lands, hatch opens, "
            "characters step out confidently."
        )
    if is_last and show_config.ship_description:
        parts.append(
            f"Closing scene: characters walk back toward the {show_config.ship_description}, "
            "wave goodbye to camera, hatch closes, vehicle departs."
        )

    # Camera & composition
    parts.append(scene.camera_style.rstrip(".") + ".")

    # Scene description & action
    parts.append(scene.description)
    parts.append(scene.action)

    # Mood
    parts.append(f"Mood: {scene.mood}.")

    # Character visual locks — always included for consistency
    parts.append(f"Characters: {show_config.characters_prompt()}")

    # Audio cues — tie each line to the speaking character
    audio_parts: list[str] = []
    speakers = [
        (c, scene.dialogue.get(c.name, ""))
        for c in show_config.characters
        if scene.dialogue.get(c.name, "").strip()
    ]

    if len(speakers) >= 2:
        c0, line0 = speakers[0]
        c1, line1 = speakers[1]
        audio_parts.append(
            f'{c0.name} turns and says in {c0.voice_description}: "{line0}" '
            f'{c1.name} replies in {c1.voice_description}: "{line1}"'
        )
    elif len(speakers) == 1:
        c, line = speakers[0]
        audio_parts.append(f'{c.name} speaks in {c.voice_description}: "{line}"')

    audio_parts.append("Cheerful orchestral background music.")
    audio_parts.append("Ambient environment sound effects.")
    parts.append(" ".join(audio_parts))

    return " ".join(p.strip() for p in parts if p.strip())


def build_image_prompt(
    scene: Scene,
    show_config: ShowConfig,
    is_first: bool,
    is_last: bool,
) -> str:
    """Static composition prompt for the image model — no motion language."""
    parts = [
        show_config.art_style,
        f"{scene.camera_style.rstrip('.')}.",
        scene.description,
        f"Characters shown: {show_config.characters_prompt()}",
        f"Mood: {scene.mood}. Single still frame, no motion blur.",
    ]
    if is_first and show_config.ship_description:
        parts.insert(1, f"{show_config.ship_description} has just arrived, characters stepping out.")
    if is_last and show_config.ship_description:
        parts.insert(1, f"Characters walking toward {show_config.ship_description}, waving goodbye.")
    return " ".join(p.strip() for p in parts if p.strip())


# ---------------------------------------------------------------------------
# Frame generator (Imagen)
# ---------------------------------------------------------------------------

def generate_scene_frame(
    client: genai.Client,
    scene: Scene,
    output_path: Path,
    show_config: ShowConfig,
    aspect_ratio: str,
    is_first: bool,
    is_last: bool,
    platform_suffix: str = "",
) -> Optional[gentypes.Image]:
    """Generate a grounded base frame using Gemini image generation + character ref images."""
    from PIL import Image as PILImage

    img_path = output_path.parent / f"frame{platform_suffix}_{scene.number:02d}.png"

    if img_path.exists():
        print(f"    Frame {scene.number} cached — reusing.")
        return gentypes.Image(image_bytes=img_path.read_bytes(), mime_type="image/png")

    print(f"    Generating base frame with {GEMINI_IMAGE_MODEL} + character refs…")

    contents: list = [build_image_prompt(scene, show_config, is_first, is_last)]

    # Attach any reference images the show config provides
    for char in show_config.characters:
        if char.reference_image and char.reference_image.exists():
            contents.append(PILImage.open(char.reference_image))

    try:
        response = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=contents,
            config=gentypes.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=gentypes.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size="1K",
                ),
            ),
        )

        for part in response.candidates[0].content.parts:
            genai_img = part.as_image()
            if genai_img is not None:
                img_path.write_bytes(genai_img.image_bytes)
                import io
                pil = PILImage.open(io.BytesIO(genai_img.image_bytes))
                print(f"    Frame saved: {img_path.name} ({pil.width}x{pil.height})")
                return genai_img

        print("    No image in response — will generate video text-only.")
        return None

    except Exception as e:
        print(f"    Frame generation failed: {str(e)[:120]}")
        print("    Continuing without base frame.")
        return None


# ---------------------------------------------------------------------------
# Video generator (Veo3)
# ---------------------------------------------------------------------------

def generate_scene_video(
    client: genai.Client,
    scene: Scene,
    output_path: Path,
    aspect_ratio: str,
    resolution: str,
    base_image: Optional[gentypes.Image],
) -> bool:
    """Generate a scene clip via Veo3 with model fallback cascade."""

    print(f"  Scene {scene.number}/{scene.title!r} — {scene.duration}s | {aspect_ratio} {resolution}")
    print(f"    Prompt snippet: {scene.veo_prompt[:120]}…")

    def _call(model: str, image: Optional[gentypes.Image]) -> gentypes.GenerateVideosOperation:
        cfg = gentypes.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration_seconds=scene.duration,
            number_of_videos=1,
        )
        return client.models.generate_videos(
            model=model,
            prompt=scene.veo_prompt,
            image=image,
            config=cfg,
        )

    def _needs_fallback(e: Exception) -> bool:
        s = str(e)
        return any(k in s for k in [
            "404", "403", "429", "NOT_FOUND", "PERMISSION_DENIED",
            "quota", "RESOURCE_EXHAUSTED", "rate", "limit",
            "use case", "not supported", "referenceImages",
        ])

    attempts = [
        (VEO_MODEL_PRIMARY,  base_image),
        (VEO_MODEL_PRIMARY,  None),
        (VEO_MODEL_FALLBACK, base_image),
        (VEO_MODEL_FALLBACK, None),
        (VEO_MODEL_FAST,     base_image),
        (VEO_MODEL_FAST,     None),
        (VEO_MODEL_LITE,     base_image),
        (VEO_MODEL_LITE,     None),
    ]
    operation = None
    for model, img in attempts:
        label = f"{model} {'+ frame' if img else '(text only)'}"
        try:
            print(f"    Trying {label}…")
            operation = _call(model, img)
            print(f"    OK {label}")
            break
        except Exception as e:
            if _needs_fallback(e):
                print(f"    {label} -> {str(e).split(chr(10))[0][:80]}")
                continue
            raise

    if operation is None:
        raise RuntimeError("All Veo model attempts failed — check your API plan and model access.")

    # Poll until operation completes
    elapsed = 0
    while not operation.done:
        if elapsed >= MAX_WAIT:
            print(f"    Timed out after {MAX_WAIT}s")
            return False
        print(f"    Waiting… ({elapsed}s elapsed)", end="\r", flush=True)
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        operation = client.operations.get(operation)

    print()  # newline after \r

    if operation.error:
        print(f"    ERROR: {operation.error}")
        return False

    video = operation.response.generated_videos[0].video

    if video.video_bytes:
        video_bytes = video.video_bytes
    else:
        import requests as req
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        r = req.get(video.uri, headers={"x-goog-api-key": api_key}, timeout=120)
        r.raise_for_status()
        video_bytes = r.content

    with open(output_path, "wb") as f:
        f.write(video_bytes)

    size_mb = output_path.stat().st_size / 1_048_576
    print(f"    Saved {output_path.name} ({size_mb:.1f} MB)")
    return True
