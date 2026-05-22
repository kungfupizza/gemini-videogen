# Brand Assets for Chef Pip's World

Add the following files to this directory to enable the branded intro sequence.

## Required files

| File | Dimensions | Description |
|------|-----------|-------------|
| `intro_waving_ig.png` | 720 x 1280 px | Instagram (9:16) brand card — Pip waving with the Sizzle Wagon |
| `intro_card_yt.png`   | 1280 x 720 px | YouTube (16:9) brand card — show logo and title card |
| `chime.wav`           | any sample rate | Short friendly intro chime (1-3 seconds) |

## What the brand intro looks like

When these assets are present, each episode opens with:
1. The brand card image displayed full-screen
2. The chime plays
3. Kokoro TTS narrator says: "Hello everyone... Episode N... [Episode Title]."
4. The text `Episode N  |  Episode Title` appears as an overlay at the bottom

The brand intro is prepended to the assembled episode video.

## Optional: character reference images

Adding character reference PNGs helps the Imagen model maintain visual consistency
across scenes. Place them in the `characters/` directory and update the
`## Reference Image` path in each character's `.md` file.

```
characters/
    pip.png       (Pip reference — 512x512 or larger, transparent background ideal)
    bot_e.png     (Bot-E reference)
```

Then update the character files:
```markdown
## Reference Image
characters/pip.png
```

## Tips for brand images

- Use the exact dimensions above — the pipeline letterboxes to fit but exact sizing looks best.
- PNG format preferred (supports transparency for compositing).
- Keep the centre of the image clear for the text overlay bar at the bottom.
- Use your show's colour palette and font for a cohesive look.
