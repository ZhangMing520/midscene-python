"""Shared helpers (upstream shared/utils.ts).

Only the app-name helpers are ported so far.
"""

import re
from typing import Dict, Mapping, Optional


def normalize_for_comparison(value: str) -> str:
    """Normalize an app name for case-insensitive matching (upstream
    normalizeForComparison): lowercase and strip spaces, dashes, underscores."""
    return re.sub(r"[\s\-_]+", "", value.lower())


def merge_and_normalize_app_name_mapping(
    default_mapping: Mapping[str, str],
    user_mapping: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Merge app name mappings with normalized keys; user entries win.

    Matches upstream mergeAndNormalizeAppNameMapping.
    """
    result = {normalize_for_comparison(key): value for key, value in default_mapping.items()}
    if user_mapping:
        result.update(
            {normalize_for_comparison(key): value for key, value in user_mapping.items()}
        )
    return result
