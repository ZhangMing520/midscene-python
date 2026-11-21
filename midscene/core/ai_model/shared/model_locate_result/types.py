"""Locate result type aliases (upstream shared/model-locate-result/types.ts)."""

from typing import Any, Dict, List, Tuple

Bbox = List[float]  # [xmin, ymin, xmax, ymax] after order normalization
LocateResultBbox = Bbox
PixelBbox = Bbox
LocateResultPoint = Tuple[float, float]

CoordinateRounding = str  # 'round' | 'trunc' | 'none'
BboxBoundsType = str  # closed | left-closed-right-open (inclusive/edges aliases)
NormalizationBasis = str  # image-size | last-pixel

RawLocateValue = Any
LocateResultValue = Dict[str, Any]
