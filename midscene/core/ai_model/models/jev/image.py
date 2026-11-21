"""Jev image helpers (upstream models/jev/image.ts)."""

from typing import Any, Dict, List, Optional
import asyncio
import base64
import io
from midscene.core.ai_model.service_caller.system_one import SystemOneError
from midscene.core.ai_model.shared.multimodal_prompt import resolve_reference_image

def prepare_jev_image(image_url: str) -> str:
    """Normalize an image to a JPEG/PNG data URL under 16 MiB."""
    raw = image_url
    if raw.startswith("data:"):
        header, body = raw.split(",", 1)
        if len(body.encode()) > 16 * 1024 * 1024 // 4 * 3:
            raise SystemOneError("Jev image exceeds 16 MiB")
        if header.startswith("data:image/png") or header.startswith("data:image/jpeg"):
            return raw
        # convert to jpeg
        from PIL import Image

        image = Image.open(io.BytesIO(base64.b64decode(body))).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    # raw base64 -> jpeg data url
    if len(raw.encode()) > 16 * 1024 * 1024 // 4 * 3:
        raise SystemOneError("Jev image exceeds 16 MiB")
    return "data:image/jpeg;base64," + raw


async def _prepare_jev_references(prompt: Any) -> Dict[str, Any]:
    """Reference images from a multimodal prompt (jev/image.ts prepareReferences)."""
    images = prompt.get("images") if isinstance(prompt, dict) else None
    convert_http = (
        bool(prompt.get("convertHttpImage2Base64", False))
        if isinstance(prompt, dict)
        else False
    )
    entries: List[Dict[str, Any]] = []
    for index, item in enumerate(images or []):
        url = item.get("url") if isinstance(item, dict) else item
        if not isinstance(url, str) or not url:
            continue
        entries.append(
            {
                "key": f"reference_{index}",
                "name": item.get("name") if isinstance(item, dict) else None,
                "url": url,
            }
        )

    semaphore = asyncio.Semaphore(5)
    resolved: Dict[str, Optional[str]] = {}

    async def resolve(url: str) -> None:
        if url.startswith("data:"):
            resolved[url] = url
            return
        # Local file paths (and opted-in HTTP URLs) need inlining first.
        async with semaphore:
            resolved[url] = await asyncio.to_thread(
                resolve_reference_image, {"url": url}, convert_http
            )

    await asyncio.gather(*(resolve(url) for url in dict.fromkeys(
        entry["url"] for entry in entries
    )))

    references: List[Dict[str, Any]] = []
    image_map: Dict[str, str] = {}
    for entry in entries:
        url = resolved.get(entry["url"]) or entry["url"]
        reference: Dict[str, Any] = {"image": f"`{entry['key']}`"}
        if entry["name"]:
            reference["name"] = entry["name"]
        references.append(reference)
        image_map[entry["key"]] = prepare_jev_image(url)
    return {"references": references, "images": image_map}
