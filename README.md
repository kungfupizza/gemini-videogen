# gemini-videogen

**Idea to Video CLI powered by Google Veo3.**

Turn any show concept into AI-animated video episodes. Provide a "show config" (lore + characters)
and run one command to generate complete episodes — Instagram Reels, YouTube clips, or both.

Extracted from a production cartoon pipeline. Show-agnostic: works for any genre, any characters.

---

## Features

- **`init`** — Generate a complete show config from a one-line idea using Gemini
- **`run`** — Generate a single episode (story → Veo3 video → assembled MP4)
- **`series`** — Generate a multi-episode series with Instagram + YouTube variants and captions
- **Model cascade** — Tries `veo-3.1` → `veo-3.0` → `veo-3.0-fast` → `veo-3.0-lite` automatically
- **Resume** — Interrupted runs pick up where they left off (story.json + cached clips)
- **Brand intro** — Optional branded intro card with Kokoro TTS narration prepended to each episode
- **Dual platform** — Instagram 9:16 (45s) and YouTube 16:9 (34s) from the same story

---

## Install

```bash
# install from source
git clone https://github.com/your-username/gemini-videogen
cd gemini-videogen
uv sync

# With Kokoro TTS support for brand intros (optional)
uv sync --extra tts
```

> **uv** is the recommended installer — fast, lockfile-based, reproducible.
> Install it with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`

Once published to PyPI:

```bash
uv pip install gemini-videogen
```

**System dependency:** `ffmpeg` is required for video assembly.

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
apt install ffmpeg
```

---

## Setup

### 1. Get a Google API key

Get your key from [Google AI Studio](https://aistudio.google.com/).
You need access to **Gemini** (for story generation) and **Veo3** (for video generation).

### 2. Set the environment variable

```bash
export GOOGLE_API_KEY=your_key_here
```

Or create a `.env` file in your working directory:

```
GOOGLE_API_KEY=your_key_here
```

---

## Quick start

### Step 1: Generate a show config

```bash
gemini-videogen init "A cooking adventure show for kids hosted by a young chef and her robot"
```

This calls Gemini to generate:
- `lore.md` — world description, universe rules, art style
- `characters/pip.md`, `characters/bot_e.md` — character configs
- `brand/README.md` — instructions for brand assets

Review and edit these files to your taste.

### Step 2: Add brand assets (optional)

See `brand/README.md` in your show directory. Brand assets enable the branded intro sequence.

Without brand assets, episodes are generated without an intro — still fully functional.

### Step 3: Generate an episode

```bash
gemini-videogen run "Chef Pip discovers edible flowers in Japan" --show ./my_show
```

Output goes to `./output/<slug>/`:
- `story.json` — episode story and scene plans
- `prompts.json` — Veo3 prompts for each scene
- `frame_01.png` ... `frame_06.png` — Imagen base frames
- `scene_01.mp4` ... `scene_06.mp4` — individual scene clips
- `EpisodeTitle_instagram.mp4` — final assembled episode

### Step 4: Generate a series

```bash
gemini-videogen series "Kitchen Adventures: Italy, Japan, Mexico, India, France, Peru" --show ./my_show
```

Or let the pipeline pick locations:

```bash
gemini-videogen series "Chef Pip travels the world" --show ./my_show
```

Output includes:
- Per-episode Instagram Reels (Phase A)
- Per-episode YouTube clips (Phase B)
- YouTube compilation video
- `captions.md` — ready-to-post captions for all platforms

---

## Show config format

A show config is a directory with this structure:

```
my_show/
├── lore.md
├── characters/
│   ├── protagonist.md
│   └── companion.md
└── brand/
    ├── intro_waving_ig.png   (720x1280, Instagram brand card)
    ├── intro_card_yt.png     (1280x720, YouTube brand card)
    └── chime.wav             (short intro chime)
```

### lore.md

```markdown
# Show Title

## World
One or more paragraphs describing the world/setting — injected into story generation.

## Universe Rules
- How episodes open (e.g. "Every episode begins with the vehicle arriving")
- How episodes close
- Any recurring rules (tone, content limits, recurring elements)

## Art Style
One sentence describing the visual style — injected into every Veo3 prompt.
e.g. "3D cartoon animation style, vibrant kid-friendly colours, bold clean outlines,
Pixar-quality rendering, expressive faces, smooth motion, cinematic lighting"

## Ship / Vehicle (optional)
Description of the recurring vehicle if any. Injected into episode open/close scenes.
```

### characters/protagonist.md

```markdown
# Character Name

## Visual Description
Full visual description injected verbatim into Veo3 prompts. Be specific about
appearance, clothing, distinguishing features. 3+ sentences.

## Voice
One sentence: voice gender, accent, tone, quirks.
e.g. "Warm upbeat American girl's voice, age 10, curious and expressive"

## Personality
2-3 sentences for story generation context.

## Reference Image
Optional: path to a reference PNG relative to show config dir (e.g. characters/name.png)
```

See `example_show/` for a complete working example.

---

## CLI reference

```
gemini-videogen init IDEA [--output DIR]
gemini-videogen run  IDEA --show DIR [--platform instagram|youtube] [--dry-run] [--skip-video] [--frames-only] [--story-file PATH]
gemini-videogen series STORYLINE --show DIR [--dry-run] [--skip-video]
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Generate story + prompts only; no video API calls |
| `--skip-video` | Stop after prompt generation |
| `--frames-only` | Generate Imagen base frames; skip Veo3 |
| `--story-file PATH` | Resume from an existing `story.json` |
| `--platform` | `instagram` (9:16, 45s) or `youtube` (16:9, 34s) |
| `--output DIR` | Base output directory (default: `./output`) |

---

## Claude MCP server

`gemini-videogen` ships an [MCP](https://modelcontextprotocol.io) server so Claude can orchestrate
Veo3 video generation directly from a conversation — no CLI needed.

### Install

```bash
uv sync --extra mcp
```

### Register with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gemini-videogen": {
      "command": "gemini-videogen-mcp",
      "env": {
        "GOOGLE_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Available tools

| Tool | Description |
|------|-------------|
| `init_show` | Generate a show config (lore + characters) from a one-line idea |
| `run_episode` | Generate a single episode video |
| `generate_series` | Generate a full multi-episode series |
| `list_outputs` | List generated videos and file sizes |
| `show_episode_story` | Read the story plan for a generated episode |

### Example conversation

> **You:** Create a new show about a young marine biologist and her submarine robot exploring the ocean. Then make a pilot episode.
>
> **Claude:** *(calls `init_show`, then `run_episode` with `dry_run=True` to preview, then generates the video)*

---

## Kokoro TTS (brand intros)

Brand intros use [Kokoro](https://github.com/hexgrad/kokoro) for narration. It's optional:

```bash
pip install kokoro numpy
```

Without Kokoro, brand intros use only the chime (no spoken narration). Without any brand assets,
episodes are generated without a brand intro — the core video pipeline is unaffected.

---

## Platform specs

| Platform | Aspect ratio | Resolution | Target duration | Scene durations |
|----------|-------------|------------|-----------------|-----------------|
| Instagram Reels | 9:16 | 720p | 45s | [8,8,8,8,8,6] |
| YouTube | 16:9 | 720p | 34s | [6,6,6,6,6,4] |

---

## Resume behaviour

The pipeline saves `story.json` before any video generation. If a run is interrupted:
- Story is reloaded from `story.json` automatically
- Existing scene clips (`scene_01.mp4` etc.) are reused without re-generation
- The intro flag (`_intro_done.flag`) prevents double-prepending the brand intro

Just re-run the same command to resume.

---

## License

MIT
