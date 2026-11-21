"""XML tag extraction helpers.

Synced from upstream packages/core/src/ai-model/shared/xml.ts.
"""

import re
from typing import Optional, Sequence


def extract_xml_tag(xml_string: str, tag_name: str) -> Optional[str]:
    """Extract content of a tag, searching from the end.

    Handles models that prepend thinking content before the response tags, and
    half-open tags without a matching close.
    """
    lower_xml = xml_string.lower()
    lower_tag = tag_name.lower()
    close_tag = f"</{lower_tag}>"
    open_tag = f"<{lower_tag}>"

    last_close_index = lower_xml.rfind(close_tag)
    if last_close_index == -1:
        last_open_index = lower_xml.rfind(open_tag)
        if last_open_index == -1:
            return None
        content_start = last_open_index + len(open_tag)
        remaining = xml_string[content_start:]
        next_tag_index = remaining.find("<")
        content = remaining if next_tag_index == -1 else remaining[:next_tag_index]
        return content.strip()

    search_area = lower_xml[:last_close_index]
    last_open_index = search_area.rfind(open_tag)
    if last_open_index == -1:
        return None

    content_start = last_open_index + len(open_tag)
    content_end = last_close_index
    return xml_string[content_start:content_end].strip()


def _escapeRegExp(value: str) -> str:
    return re.sub(r"[.*+?^${}()|[\]\\]", lambda m: "\\" + m.group(0), value)


def extract_raw_xml_fragment(
    content: str, tag_names: Sequence[str]
) -> str:
    """Extract raw XML from the first protocol tag through the last protocol tag."""
    start_tag_name = tag_names[0]
    end_tag_name = tag_names[-1]
    start_match = re.search(
        r"<" + _escapeRegExp(start_tag_name) + r">", content, re.IGNORECASE
    )
    if not start_match:
        return ""

    content_from_start = content[start_match.start():]
    end_matches = list(
        re.finditer(
            r"</" + _escapeRegExp(end_tag_name) + r">",
            content_from_start,
            re.IGNORECASE,
        )
    )
    if end_matches:
        last_end = end_matches[-1]
        return content_from_start[: last_end.end()]
    return content_from_start
