"""Multimodal prompt/image preparation (upstream ai-model/shared/multimodal-prompt.ts)."""

from typing import Any, Dict, List, Optional
import asyncio
import base64
from pathlib import Path
from loguru import logger

def user_prompt_to_string(prompt: Any) -> str:
    """TUserPrompt: str or {'prompt': str}."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict) and "prompt" in prompt:
        return str(prompt.get("prompt", ""))
    return str(prompt)


def ensure_data_url(image_base64: str) -> str:
    if image_base64.startswith("data:"):
        return image_base64
    return f"data:image/jpeg;base64,{image_base64}"


_REFERENCE_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def resolve_reference_image(image: Any, convert_http: bool) -> Optional[str]:
    """Resolve one markdown reference image to a model-ingestable URL."""
    url = image.get("url") if isinstance(image, dict) else None
    if not url or not isinstance(url, str):
        return None
    if url.startswith("data:"):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        if not convert_http:
            return url
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=15) as resp:
                raw = resp.read()
            mime = getattr(resp.headers, "get_content_type", lambda: "image/png")()
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception as e:
            logger.warning(f"Failed to inline reference image {url}: {e}")
            return url
    path = Path(url)
    if path.exists():
        suffix = path.suffix.lstrip(".").lower() or "png"
        mime = _REFERENCE_IMAGE_MIME.get(suffix, "image/png")
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    return None


def resolve_reference_images(images: Any, convert_http: bool) -> List[str]:
    """Resolve a list of markdown reference images to model-ingestable URLs."""
    resolved = []
    for item in images or []:
        url = resolve_reference_image(item, convert_http)
        if url:
            resolved.append(url)
    return resolved


async def prepare_reference_images(images: Any, convert_http: bool) -> List[str]:
    """Resolve reference images once per unique URL, at most five in flight
    (upstream prepareReferenceImages)."""
    urls: List[str] = []
    for item in images or []:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url:
            urls.append(url)
    unique_urls = list(dict.fromkeys(urls))
    semaphore = asyncio.Semaphore(5)
    prepared: Dict[str, Optional[str]] = {}

    async def prepare_one(url: str) -> None:
        async with semaphore:
            prepared[url] = await asyncio.to_thread(
                resolve_reference_image, {"url": url}, convert_http
            )

    await asyncio.gather(*(prepare_one(url) for url in unique_urls))
    return [prepared[url] for url in urls if prepared.get(url)]


def get_screenshot_base64(context: Any) -> str:
    """Read the screenshot from a UIContext (base64 or data URL)."""
    screenshot = getattr(context, "screenshot_base64", None)
    if screenshot is None and isinstance(context, dict):
        screenshot = context.get("screenshot_base64")
    if screenshot is None and isinstance(context, dict):
        nested = context.get("screenshot") or {}
        screenshot = nested.get("base64")
    if not screenshot:
        raise ValueError("UIContext has no screenshot for the AI workflow")
    return screenshot


def get_shot_size(context: Any) -> Dict[str, int]:
    """Read the screenshot size {width, height} from a UIContext."""
    size = getattr(context, "size", None)
    if size is None and isinstance(context, dict):
        size = context.get("size")
    if size is not None:
        return {"width": int(size.width), "height": int(size.height)} if hasattr(size, "width") else {
            "width": int(size["width"]),
            "height": int(size["height"]),
        }
    if isinstance(context, dict):
        shot_size = context.get("shotSize")
        if shot_size:
            return dict(shot_size)
    raise ValueError("UIContext has no size for the AI workflow")
