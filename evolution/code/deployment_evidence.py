"""Compact deployment summary; persisted descriptions never confer authority."""
from __future__ import annotations

from typing import Any


def verify_deployment(env: Any, *, tool_relpath: str, verification: object = None) -> dict[str, str]:
    """Return refusal unless the final gate owns a live protected assessment.

    The optional context configures verification; it is not accepting evidence.
    Gates retain the assessment and snapshot lease outside the decision mapping.
    """
    return {'schema_version': '1', 'status': 'unverifiable',
            'reason': 'independent_test_verification_unavailable'}
