"""Model image preprocessing (upstream model-adapter/image-preprocess.ts)."""

from typing import TypedDict

from loguru import logger

from midscene.shared.img.transform import padding_to_match_block_by_base64


class ImagePreprocessPolicy(TypedDict, total=False):
    padBlockSize: int


class PreparedModelImage(TypedDict):
    image_base64: str
    prepared_size: dict[str, int]
    content_size: dict[str, int]


def prepare_model_image(
    image_base64: str,
    width: int,
    height: int,
    policy: ImagePreprocessPolicy | None = None,
) -> PreparedModelImage:
    """Prepare the image for a model call.

    ``padBlockSize`` pads the image (right/bottom, white) so its dimensions are
    a multiple of the block size, as required by some models (e.g. qwen2.5-vl).
    """
    prepared_base64 = image_base64
    model_width = width
    model_height = height

    pad_block_size = (policy or {}).get("padBlockSize")
    if pad_block_size:
        try:
            padded = padding_to_match_block_by_base64(image_base64, int(pad_block_size))
            prepared_base64 = padded["imageBase64"]
            model_width = padded["width"]
            model_height = padded["height"]
        except Exception as e:  # pragma: no cover - fall back to no padding
            logger.warning(f"image padding failed, using original image: {e}")

    return {
        "image_base64": prepared_base64,
        "prepared_size": {"width": model_width, "height": model_height},
        "content_size": {"width": width, "height": height},
    }


__all__ = [
    "ImagePreprocessPolicy",
    "PreparedModelImage",
    "prepare_model_image",
]
