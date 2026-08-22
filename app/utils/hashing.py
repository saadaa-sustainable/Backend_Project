"""Deterministic hashing of raw Meta API payloads.

Used to populate ``BronzeMixin.payload_hash`` so downstream (Silver-layer)
consumers can cheaply detect whether an object actually changed between two
syncs without diffing full JSON blobs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def hash_payload(payload: dict[str, Any]) -> str:
    """Return the sha256 hex digest of ``payload`` under a canonical
    (sorted-key, no-whitespace) JSON serialization, so semantically
    identical payloads always hash identically regardless of key order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
