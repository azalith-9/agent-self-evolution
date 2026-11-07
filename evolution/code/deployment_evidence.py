"""Internal deployment boundary, independent of cooperative test diagnostics.

No currently installed adapter supplies semantic verification across a protected
trust boundary. In particular, pytest records, supervisor process receipts and
persisted accepted summaries cannot authorize exporting candidate code. Refusal
here preserves diagnostic runs without claiming a supported certification flow.
"""

from __future__ import annotations

from typing import Any


def verify_deployment(env: Any, *, tool_relpath: str) -> dict[str, str]:
    """Refuse certification when no protected semantic verifier is available.

    Do not inspect attributes supplied by an execution adapter: a constructed
    certificate or a previous JSON decision is not independently verified proof.
    This boundary must remain closed until an actual independent oracle exists.
    """
    return {
        "schema_version": "1", "status": "unverifiable",
        "reason": "independent_test_verification_unavailable",
    }
