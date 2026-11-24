"""Pointer geometry helpers (upstream pointer.ts)."""


def clamp_pointer_point_to_size(
    point: dict[str, float], size: dict[str, float]
) -> tuple[int, int]:
    """Keep a screen-space point inside the half-open pixel bounds."""
    maximum_x = max(0, int(size["width"]) - 1)
    maximum_y = max(0, int(size["height"]) - 1)
    return (
        max(0, min(int(point["x"]), maximum_x)),
        max(0, min(int(point["y"]), maximum_y)),
    )


__all__ = ["clamp_pointer_point_to_size"]
