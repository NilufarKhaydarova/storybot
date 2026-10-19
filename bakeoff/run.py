"""Run the bake-off: one photo, one style page and four story pages through every model.

    python -m bakeoff.run --photo child.jpg --style style.jpg --name Timur
    python -m bakeoff.run --photo child.jpg --style style.jpg --name Timur --models gpt-image-2,flux-2-pro
    python -m bakeoff.run --photo child.jpg --style style.jpg --name Timur --dry-run

Each model first turns the photo into a character sheet in the style of the style page,
then draws every scene from that sheet. Models whose API key isn't set are skipped.
Results land in out/<date-time>/: the images, results.json and report.html.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from . import compose, prompts, providers, report

HERE = Path(__file__).parent
INPUT_MAX_EDGE = 1536


def load_image(path: Path) -> bytes:
    """As JPEG, upright and at most INPUT_MAX_EDGE on the long side: smaller uploads, same result."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((INPUT_MAX_EDGE, INPUT_MAX_EDGE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def save_png(data: bytes, path: Path) -> None:
    Image.open(io.BytesIO(data)).save(path)


async def _attempt(cfg: dict, prompt: str, refs: list[bytes], kind: str, client: httpx.AsyncClient,
                   path: Path) -> tuple[dict, bytes | None]:
    started = time.monotonic()
    try:
        data = await providers.generate(cfg, prompt, refs, kind, client)
        save_png(data, path)
    except providers.Failed as exc:
        status = "refused" if isinstance(exc, providers.Refused) else "failed"
        return {"status": status, "error": str(exc), "seconds": time.monotonic() - started}, None
    except OSError as exc:  # the reply wasn't an image Pillow can read
        return {"status": "failed", "error": f"unreadable image: {exc}", "seconds": time.monotonic() - started}, None
    return {"status": "ok", "file": path.name, "seconds": time.monotonic() - started}, data


async def run_model(cfg: dict, photo: bytes, style: bytes, story: dict, name: str, out: Path,
                    client: httpx.AsyncClient, photo_on_pages: bool, font: str | None) -> dict:
    model_dir = out / cfg["name"]
    model_dir.mkdir(parents=True, exist_ok=True)
    single = cfg["provider"] in providers.SINGLE_IMAGE
    outfit = story["outfit"]
    started = time.monotonic()

    sheet_refs = [photo] if single else [photo, style]
    sheet, sheet_data = await _attempt(cfg, prompts.sheet(name, outfit, single), sheet_refs, "sheet", client,
                                       model_dir / "sheet.png")

    async def draw_page(scene: dict) -> dict:
        if sheet_data is None:
            return {"id": scene["id"], "status": "skipped", "error": "no character sheet"}
        with_photo = photo_on_pages and not single
        refs = [sheet_data] if single else [sheet_data, style] + ([photo] if with_photo else [])
        text_side = scene.get("text_side", "right")
        prompt = prompts.page(name, outfit, scene["scene"], text_side, single, with_photo)
        entry, _ = await _attempt(cfg, prompt, refs, "page", client, model_dir / f"page-{scene['id']}.png")
        if entry["status"] == "ok":
            spread_path = model_dir / f"spread-{scene['id']}.jpg"
            await asyncio.to_thread(compose.spread, model_dir / entry["file"], scene["text"], text_side,
                                    spread_path, font)
            entry["spread"] = spread_path.name
        return {"id": scene["id"], **entry}

    pages = await asyncio.gather(*(draw_page(s) for s in story["scenes"]))

    rel = f"{cfg['name']}/"
    for entry in [sheet, *pages]:
        for key in ("file", "spread"):
            if entry.get(key):
                entry[key] = rel + entry[key]
    attempts = [e for e in [sheet, *pages] if e["status"] != "skipped"]
    ok = sum(e["status"] == "ok" for e in attempts)
    return {
        "name": cfg["name"], "note": cfg.get("note", ""), "sheet": sheet, "pages": list(pages),
        "ok": ok, "total": 1 + len(pages), "refused": sum(e["status"] == "refused" for e in attempts),
        "usd": ok * float(cfg.get("usd_per_image", 0)), "seconds": time.monotonic() - started,
    }


def fill_name(story: dict, name: str) -> dict:
    return json.loads(json.dumps(story).replace("{name}", name))


def pick_models(models: list[dict], wanted: str, dry_run: bool) -> list[dict]:
    names = {n.strip() for n in wanted.split(",") if n.strip()}
    chosen = []
    for cfg in models:
        if names and cfg["name"] not in names:
            continue
        if not names and not cfg.get("enabled", True):
            print(f"  skip {cfg['name']}: disabled in models.json")
            continue
        if dry_run:
            chosen.append({**cfg, "provider": "fake", "usd_per_image": 0})
        elif not providers.key_for(cfg):
            print(f"  skip {cfg['name']}: {providers.KEY_ENV[cfg['provider']]} is not set")
        else:
            chosen.append(cfg)
    return chosen


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--photo", type=Path, required=True, help="photo of the child (with the parent's consent)")
    parser.add_argument("--style", type=Path, required=True, help="a picture-book page in the target style")
    parser.add_argument("--name", required=True, help="the child's name, used in the story")
    parser.add_argument("--models", default="", help="comma-separated names from models.json (default: all enabled)")
    parser.add_argument("--models-file", type=Path, default=HERE / "models.json")
    parser.add_argument("--story", type=Path, default=HERE / "scenes.json")
    parser.add_argument("--scenes", type=int, default=0, help="only the first N scenes (default: all)")
    parser.add_argument("--no-photo-on-pages", action="store_true",
                        help="draw pages from the character sheet alone, without the photo")
    parser.add_argument("--font", help="a .ttf font for the text overlay")
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--dry-run", action="store_true", help="placeholder images: no keys, no cost")
    parser.add_argument("--yes", action="store_true", help="don't ask before spending")
    args = parser.parse_args()

    story = fill_name(json.loads(args.story.read_text(encoding="utf-8")), args.name)
    if args.scenes:
        story["scenes"] = story["scenes"][: args.scenes]
    models = pick_models(json.loads(args.models_file.read_text(encoding="utf-8")), args.models, args.dry_run)
    if not models:
        raise SystemExit("No models to run: set an API key (see .env.example) or use --dry-run.")

    images = 1 + len(story["scenes"])
    estimate = sum(images * float(m.get("usd_per_image", 0)) for m in models)
    print(f"{len(models)} model(s) × {images} images: {', '.join(m['name'] for m in models)}")
    if not args.dry_run:
        print(f"Estimated cost: about ${estimate:.2f}")
        if not args.yes and input("Go ahead? [y/N] ").strip().lower() != "y":
            return

    out = args.out / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    photo, style = load_image(args.photo), load_image(args.style)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        results = await asyncio.gather(*(
            run_model(cfg, photo, style, story, args.name, out, client, not args.no_photo_on_pages, args.font)
            for cfg in models
        ))

    (out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    path = report.write(out, story["title"], list(results), story["scenes"], args.dry_run)
    print()
    for r in results:
        problems = [f"{e.get('id', 'sheet')}: {e['status']}" for e in [r["sheet"], *r["pages"]] if e["status"] != "ok"]
        print(f"  {r['name']:<24} {r['ok']}/{r['total']} ok  ~${r['usd']:.2f}  {r['seconds']:.0f}s  "
              + ("; ".join(problems) if problems else ""))
    print(f"\nReport: {path}")


if __name__ == "__main__":
    asyncio.run(main())
