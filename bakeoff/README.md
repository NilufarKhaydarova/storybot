# Image model bake-off

Which model should draw the books? This runs the same test through every candidate and
puts the results side by side in one HTML page.

For each model:
1. **Character sheet**: the child's photo plus a style page from a picture book are turned
   into the child as a book character (front, three-quarter, side, face close-up).
2. **Four story pages**, each drawn from that sheet plus the style page (and the photo, for
   likeness). The scenes test one thing each: a close-up, full body in motion, a second
   character, and night lighting.
3. Each page is cropped to a 2:1 spread (a square book opened flat) and the story text is laid
   over the side the prompt kept calm, with a faint line at the fold.

The image models never write the text. Our code does, so Uzbek and Russian text comes out right.

## Run it

```bash
pip install -r bakeoff/requirements.txt
cp bakeoff/.env.example .env      # fill in the keys you have
set -a; source .env; set +a

python -m bakeoff.run --photo child.jpg --style style.jpg --name Timur
open out/<date-time>/report.html
```

- `--dry-run` runs everything with placeholder images: no keys, no cost.
- `--models gpt-image-2,flux-2-pro` runs only those.
- `--scenes 2` runs only the first two scenes: a cheaper first pass.
- `--no-photo-on-pages` draws pages from the sheet alone. Run it both ways: sending the photo
  every time may help likeness, and may also trigger more safety refusals.
- It prints an estimated cost and asks before spending (`--yes` skips the question).
  All seven default models together cost about $3 per run.

Models without a key are skipped, so you can start with just the keys you already have
(checker-bot's `OPENAI_API_KEY` and `GEMINI_API_KEY`). One `FAL_KEY` adds FLUX.2, Qwen and Seedream.

## The models (`models.json`)

| Name | Provider | Key | Why it's here |
|---|---|---|---|
| gpt-image-2 | OpenAI | `OPENAI_API_KEY` | Strong at keeping a character, up to 16 reference images |
| nano-banana-pro | Google | `GEMINI_API_KEY` | Often ranked best for consistency; known to be strict about photos of children |
| nano-banana-2 | Google | `GEMINI_API_KEY` | The cheaper Google model |
| flux-2-pro | fal | `FAL_KEY` | Black Forest Labs' best editing model, up to 9 reference images |
| qwen-edit-2511 | fal | `FAL_KEY` | Open weights (Apache 2.0): the one we could later run on our own DigitalOcean GPU |
| seedream-5-lite | fal | `FAL_KEY` | The cheapest |
| kontext-pro-fireworks | Fireworks | `FIREWORKS_API_KEY` | Fireworks only has FLUX.1 Kontext, which takes **one** reference image, so the style is described in words |
| muse-image | OpenRouter | `OPENROUTER_API_KEY` | Meta's image model. Off by default: confirm its model ID on openrouter.ai, then set `"enabled": true` |

Prices in `models.json` are rough estimates from published comparisons, used only for the
cost line. Two endpoint names couldn't be confirmed: Seedream on fal, and Muse Image on
OpenRouter. If one fails with a 404, look up its current ID and edit `models.json`.

## Judging

`report.html` lists what to look at: likeness, consistency between pages, style match, mistakes
(hands, stray letters), layout, and refusals. Refusals are counted separately. A model that
turns down children's photos even some of the time can't be used for this product, however
good its pictures are.

Run it with 2–3 different children's photos, with their parents' permission. One photo can flatter
a model by chance. The `out/` folder holds those photos' results. It's git-ignored: keep it that way.

## About the style page

A page from someone else's published book is fine for this internal test. The bot itself
needs style pages we have the rights to: commissioned from an illustrator, or generated and
then chosen by us.

## Checks

```bash
python -m bakeoff.test_providers   # every adapter against canned API replies, offline
```
