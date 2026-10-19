"""Offline checks of every provider adapter against canned API replies.

    python -m bakeoff.test_providers
"""
from __future__ import annotations

import asyncio
import base64
import io
import json

import httpx
from PIL import Image

from . import providers

PNG = io.BytesIO()
Image.new("RGB", (8, 4), (200, 100, 50)).save(PNG, "PNG")
PNG = PNG.getvalue()
B64 = base64.b64encode(PNG).decode()
REFS = [b"jpeg-1", b"jpeg-2"]


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def expect(cfg: dict, handler, outcome: type[Exception] | None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    providers.POLL_SECONDS = 0
    async with client(record) as c:
        try:
            data = await providers.generate(cfg, "draw", REFS, "page", c)
        except providers.Failed as exc:
            assert outcome is not None and isinstance(exc, outcome), f"{cfg['name']}: unexpected {exc!r}"
            assert outcome is providers.Refused or not isinstance(exc, providers.Refused), f"{cfg['name']}: {exc!r}"
        else:
            assert outcome is None, f"{cfg['name']}: expected {outcome.__name__}"
            assert data == PNG
    return seen


async def main() -> None:
    openai = {"name": "o", "provider": "openai", "model": "gpt-image-2", "page_size": "2048x1024"}
    seen = await expect(openai, lambda r: httpx.Response(200, json={"data": [{"b64_json": B64}]}), None)
    body = seen[0].content
    assert b'name="image[]"' in body and body.count(b'name="image[]"') == 2 and b"2048x1024" in body
    await expect(openai, lambda r: httpx.Response(
        400, json={"error": {"code": "moderation_blocked", "message": "Your request was rejected by the safety system."}}),
        providers.Refused)
    await expect(openai, lambda r: httpx.Response(500, text="upstream error"), providers.Failed)

    gemini = {"name": "g", "provider": "gemini", "model": "gemini-3-pro-image-preview",
              "aspect_ratio": "16:9", "image_size": "2K"}
    seen = await expect(gemini, lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [
        {"text": "Here you go"}, {"inlineData": {"mimeType": "image/png", "data": B64}}]}}]}), None)
    sent = json.loads(seen[0].content)
    assert len(sent["contents"][0]["parts"]) == 3
    assert sent["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    await expect(gemini, lambda r: httpx.Response(200, json={"candidates": [{"finishReason": "IMAGE_SAFETY"}]}),
                 providers.Refused)
    await expect(gemini, lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
                 providers.Refused)
    await expect(gemini, lambda r: httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": "I can only describe it."}]}}]}), providers.Failed)

    fal = {"name": "f", "provider": "fal", "endpoint": "fal-ai/flux-2-pro/edit",
           "params": {"image_size": {"width": 2048, "height": 1024}}}
    polls = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])

    def fal_ok(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST":
            assert json.loads(request.content)["image_size"]["width"] == 2048
            return httpx.Response(200, json={"status_url": "https://q/status", "response_url": "https://q/result"})
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": next(polls)})
        if url.endswith("/result"):
            return httpx.Response(200, json={"images": [{"url": "https://cdn/img.png"}]})
        return httpx.Response(200, content=PNG)

    seen = await expect(fal, fal_ok, None)
    assert [r.url.path for r in seen][-1] == "/img.png"
    await expect(fal, lambda r: httpx.Response(
        422, json={"detail": [{"type": "content_policy_violation", "msg": "flagged"}]}), providers.Refused)

    fireworks = {"name": "fw", "provider": "fireworks", "model": "flux-kontext-pro"}
    states = iter([{"status": "Pending"}, {"status": "Ready", "result": {"sample": "https://cdn/s.png"}}])

    def fw_ok(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/flux-kontext-pro"):
            assert json.loads(request.content)["input_image"].startswith("data:image/jpeg;base64,")
            return httpx.Response(200, json={"request_id": "r1"})
        if url.endswith("/get_result"):
            return httpx.Response(200, json=next(states))
        return httpx.Response(200, content=PNG)

    await expect(fireworks, fw_ok, None)
    await expect(fireworks, lambda r: httpx.Response(200, json=(
        {"request_id": "r2"} if str(r.url).endswith("pro") else {"status": "Request Moderated"})), providers.Refused)

    openrouter = {"name": "or", "provider": "openrouter", "model": "meta/muse-image"}
    await expect(openrouter, lambda r: httpx.Response(200, json={"choices": [{"message": {"images": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{B64}"}}]}}]}), None)
    await expect(openrouter, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]}),
                 providers.Failed)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked")

    await expect(openai, broken, providers.Failed)
    print("all provider checks passed")


if __name__ == "__main__":
    asyncio.run(main())
