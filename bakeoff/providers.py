"""One image per call: a prompt and reference images in, image bytes out.

Every provider raises Refused when its safety filter turns the request down (worth
counting on its own, since a child's photo is what those filters are most wary of)
and Failed for anything else. Settings come from the model's entry in models.json.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import time

import httpx
from PIL import Image, ImageDraw

KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "fal": "FAL_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
SINGLE_IMAGE = {"fireworks"}  # providers that take one reference image per request
POLL_SECONDS = 2.0
POLL_DEADLINE = 600.0
_REFUSAL_WORDS = ("moderat", "safety", "content_policy", "content policy", "prohibited", "blocked", "nsfw")


class Failed(Exception):
    pass


class Refused(Failed):
    pass


def key_for(cfg: dict) -> str:
    return os.getenv(KEY_ENV.get(cfg["provider"], ""), "").strip()


def _data_uri(image: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image).decode()


def _fail(where: str, response: httpx.Response) -> Failed:
    text = response.text[:400]
    kind = Refused if any(w in text.lower() for w in _REFUSAL_WORDS) else Failed
    return kind(f"{where}: HTTP {response.status_code}: {text}")


async def _download(url: str, client: httpx.AsyncClient) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    response = await client.get(url)
    if response.status_code != 200:
        raise _fail("download", response)
    return response.content


async def _openai(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    response = await client.post(
        "https://api.openai.com/v1/images/edits",
        headers={"Authorization": f"Bearer {key_for(cfg)}"},
        data={"model": cfg["model"], "prompt": prompt, "n": "1",
              "size": cfg.get(f"{kind}_size", "1536x1024"), "quality": cfg.get("quality", "high")},
        files=[("image[]", (f"ref{i}.jpg", image, "image/jpeg")) for i, image in enumerate(images, 1)],
    )
    if response.status_code != 200:
        raise _fail("openai", response)
    return base64.b64decode(response.json()["data"][0]["b64_json"])


_GEMINI_REFUSALS = {"SAFETY", "PROHIBITED_CONTENT", "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}


async def _gemini(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(i).decode()}} for i in images]
    image_config = {"aspectRatio": cfg.get(f"{kind}_aspect_ratio", cfg.get("aspect_ratio", "16:9"))}
    if cfg.get("image_size"):
        image_config["imageSize"] = cfg["image_size"]
    response = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent",
        headers={"x-goog-api-key": key_for(cfg)},
        json={"contents": [{"role": "user", "parts": [*parts, {"text": prompt}]}],
              "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": image_config}},
    )
    if response.status_code != 200:
        raise _fail("gemini", response)
    body = response.json()
    blocked = (body.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise Refused(f"gemini: prompt blocked ({blocked})")
    candidate = (body.get("candidates") or [{}])[0]
    said = []
    for part in (candidate.get("content") or {}).get("parts") or []:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
        if part.get("text"):
            said.append(part["text"])
    reason = candidate.get("finishReason", "")
    kind_ = Refused if reason in _GEMINI_REFUSALS or reason.startswith("IMAGE_") else Failed
    raise kind_(f"gemini: no image (finishReason {reason or '?'}) {' '.join(said)[:300]}")


async def _fal(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    headers = {"Authorization": f"Key {key_for(cfg)}"}
    response = await client.post(
        f"https://queue.fal.run/{cfg['endpoint']}", headers=headers,
        json={"prompt": prompt, "image_urls": [_data_uri(i) for i in images], **cfg.get("params", {})},
    )
    if response.status_code not in (200, 201, 202):
        raise _fail("fal submit", response)
    job = response.json()
    deadline = time.monotonic() + POLL_DEADLINE
    while True:
        status = await client.get(job["status_url"], headers=headers)
        if status.status_code not in (200, 202):
            raise _fail("fal status", status)
        if status.json().get("status") == "COMPLETED":
            break
        if time.monotonic() > deadline:
            raise Failed("fal: timed out")
        await asyncio.sleep(POLL_SECONDS)
    result = await client.get(job["response_url"], headers=headers)
    if result.status_code != 200:
        raise _fail("fal result", result)
    body = result.json()
    if any(body.get("has_nsfw_concepts") or []):
        raise Refused("fal: output flagged by the safety checker")
    if not body.get("images"):
        raise Failed(f"fal: no image in {str(body)[:300]}")
    return await _download(body["images"][0]["url"], client)


async def _fireworks(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    base = f"https://api.fireworks.ai/inference/v1/workflows/accounts/fireworks/models/{cfg['model']}"
    headers = {"Authorization": f"Bearer {key_for(cfg)}"}
    response = await client.post(base, headers=headers,
                                 json={"prompt": prompt, "input_image": _data_uri(images[0]), **cfg.get("params", {})})
    if response.status_code != 200:
        raise _fail("fireworks submit", response)
    request_id = response.json()["request_id"]
    deadline = time.monotonic() + POLL_DEADLINE
    while True:
        poll = await client.post(f"{base}/get_result", headers=headers, json={"id": request_id})
        if poll.status_code != 200:
            raise _fail("fireworks result", poll)
        body = poll.json()
        status = str(body.get("status", ""))
        if status == "Ready":
            sample = (body.get("result") or {}).get("sample", "")
            return await _download(sample, client) if sample.startswith(("http", "data:")) else base64.b64decode(sample)
        if "Moderated" in status:
            raise Refused(f"fireworks: {status}")
        if status in ("Error", "Failed"):
            raise Failed(f"fireworks: {str(body)[:300]}")
        if time.monotonic() > deadline:
            raise Failed("fireworks: timed out")
        await asyncio.sleep(POLL_SECONDS)


async def _openrouter(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": _data_uri(i)}} for i in images]
    response = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key_for(cfg)}"},
        json={"model": cfg["model"], "modalities": ["image", "text"],
              "messages": [{"role": "user", "content": content}]},
    )
    if response.status_code != 200:
        raise _fail("openrouter", response)
    message = (response.json().get("choices") or [{}])[0].get("message") or {}
    for image in message.get("images") or []:
        return await _download(image["image_url"]["url"], client)
    raise Failed(f"openrouter: no image. {str(message.get('content'))[:300]}")


async def _fake(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    """--dry-run: a placeholder built from the inputs, to try the whole run without keys or spending."""
    await asyncio.sleep(0.05)
    size = (1536, 1024) if kind == "sheet" else (2048, 1024)
    canvas = Image.new("RGB", size, (232, 226, 214) if kind == "sheet" else (60, 130, 140))
    for i, data in enumerate(images):
        thumb = Image.open(io.BytesIO(data)).convert("RGB")
        thumb.thumbnail((400, 400))
        canvas.paste(thumb, (40 + i * 440, size[1] - thumb.height - 40))
    draw = ImageDraw.Draw(canvas)
    draw.text((40, 40), f"{cfg['name']} · {kind}\n{prompt[:160]}", fill=(20, 20, 20))
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


PROVIDERS = {"openai": _openai, "gemini": _gemini, "fal": _fal, "fireworks": _fireworks,
             "openrouter": _openrouter, "fake": _fake}


async def generate(cfg: dict, prompt: str, images: list[bytes], kind: str, client: httpx.AsyncClient) -> bytes:
    try:
        return await PROVIDERS[cfg["provider"]](cfg, prompt, images, kind, client)
    except Failed:
        raise
    except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
        raise Failed(f"{cfg['provider']}: {type(exc).__name__}: {exc}") from exc
