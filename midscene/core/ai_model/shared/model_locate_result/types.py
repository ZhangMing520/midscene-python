"""Locate result type aliases (upstream shared/model-locate-result/types.ts)."""

from typing import Any

Bbox = list[float]  # [xmin, ymin, xmax, ymax] after order normalization
LocateResultBbox = Bbox
PixelBbox = Bbox
LocateResultPoint = tuple[float, float]

CoordinateRounding = str  # 'round' | 'trunc' | 'none'
BboxBoundsType = str  # closed | left-closed-right-open (inclusive/edges aliases)
NormalizationBasis = str  # image-size | last-pixel

RawLocateValue = Any
LocateResultValue = dict[str, Any]


def is_bbox_locate_result_value(result: LocateResultValue) -> bool:
    """True when the parsed locate result describes a bbox."""
    return (result.get("coordinatesMeta") or {}).get("shape") == "bbox"


def is_point_locate_result_value(result: LocateResultValue) -> bool:
    """True when the parsed locate result describes a point."""
    return (result.get("coordinatesMeta") or {}).get("shape") == "point"
