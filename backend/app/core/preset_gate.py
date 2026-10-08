"""The required-preset gate (plan 02-05; Codex Phase 10 request, user decisions D2/D2b).

A Change whose contract selects a policy preset cannot reach ``REVIEW_READY``
unless the current preset decision is ALLOW. The decision is the one
``GET /changes/{id}/policy/preset`` reports (the Passport v2 snapshot), so
there is a single evaluator. Evidence that cannot be read is UNKNOWN and is
refused. A Change without a preset is not gated.
"""

from __future__ import annotations

from backend.app.contracts.models import ChangeView
from backend.app.core.database import Database
from backend.app.core.errors import AppError


def preset_gate_denied(gate: str, preset: str | None, reasons: list[str]) -> AppError:
    return AppError(
        "PRESET_GATE_DENIED",
        f"The required policy preset does not allow {gate}: "
        + ("; ".join(reasons[:4]) or "the decision is not ALLOW") + ".",
        status_code=409,
        details={"gate": gate, "preset": preset, "reasons": reasons[:16]},
    )


def review_ready_gate(database: Database, change: ChangeView) -> None:
    """Raise ``PRESET_GATE_DENIED`` unless the selected preset currently allows review."""

    preset = change.contract.policy_preset_name
    if preset is None:
        return
    from backend.app.passport.v2 import PassportV2Issuer

    try:
        snapshot = PassportV2Issuer(database).snapshot(change.id)
    except AppError as exc:
        raise preset_gate_denied("REVIEW_READY", preset, [
            f"preset evidence could not be evaluated ({exc.code}); UNKNOWN"]) from exc
    if snapshot.policy_decision != "ALLOW":
        raise preset_gate_denied("REVIEW_READY", preset, list(snapshot.policy_denials)
                                 or ["the preset decision is not ALLOW"])
