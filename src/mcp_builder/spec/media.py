"""Media-type predicates shared across spec parsing and codegen stages."""

from __future__ import annotations

import re

# Matches application/json, text/json, and any RFC 6839 structured-suffix
# JSON type (application/vnd.api+json, application/ld+json, etc.).
_JSON_MEDIA_RE = re.compile(
    r"^(?:application|text)/(?:[\w.+-]+\+)?json$", re.IGNORECASE
)


def is_json_media_type(media_type: str) -> bool:
    """Return True if the media type is JSON-decodable.

    Accepts ``application/json``, ``text/json`` (legacy), and any
    ``application/foo+json`` / ``text/foo+json`` structured-suffix
    variant per RFC 6839. Media-type parameters like
    ``"; charset=utf-8"`` are stripped before matching.
    """
    bare = media_type.split(";", 1)[0].strip()
    return bool(_JSON_MEDIA_RE.match(bare))
