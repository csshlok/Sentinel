"""Honest capability reporting for configured, pending, and removed systems."""

from __future__ import annotations

from backend.app.contracts.models import (
    CapabilitiesResponse,
    Capability,
    CapabilityState,
)


_REMOVED = {
    "event_journal": "Removed by approved scope; no causal event stream is recorded.",
    "process_supervisor": "Removed by approved scope; descendant processes are not controlled or attributed.",
    "filesystem_tracker": "Removed by approved scope; file writes and before-images are not observed.",
    "tool_registry": "Removed by approved scope; tool inventory and trust decisions are unavailable.",
    "replay": "Unavailable because replay requires the removed event/process/filesystem evidence.",
}

_RETAINED = {
    "change_lifecycle": "Change contracts, revisions, guarded lifecycle transitions, and migrations.",
    "git_inspection": "Read-only Git working-tree inspection.",
    "legacy_verification": "Bounded compatibility verification command execution.",
    "git_checkpoints": "Named Git checkpoint capture and comparison.",
    "agent_launcher": "Top-level launch/attach summaries without descendant supervision.",
    "environment_passports": "Redacted environment capture and drift comparison.",
    "dependency_tracking": "Supported manifest and lockfile comparison.",
    "assurance": "Evidence-selected checks and coverage reporting.",
    "identity_and_policy": "Actors, delegations, and scoped policy decisions.",
    "credential_broker": "OS-backed provider credential brokering.",
    "provider_outcomes": "GitHub pull-request and CI outcome tracking.",
    "recovery": "Approved Git commit and provider compensation only.",
    "change_passport": "Versioned retained-evidence export.",
    "cli_and_terminal_ui": "Scriptable and interactive terminal experience.",
}


def build_capabilities(configured: set[str]) -> CapabilitiesResponse:
    items: list[Capability] = []
    for capability_id, description in _RETAINED.items():
        available = capability_id in configured
        items.append(
            Capability(
                id=capability_id,
                name=capability_id.replace("_", " ").title(),
                state=(
                    CapabilityState.AVAILABLE
                    if available
                    else CapabilityState.UNCONFIGURED
                ),
                reason=None if available else "A retained implementation is not connected yet.",
                limitations=[description],
            )
        )
    for capability_id, reason in _REMOVED.items():
        items.append(
            Capability(
                id=capability_id,
                name=capability_id.replace("_", " ").title(),
                state=CapabilityState.UNSUPPORTED,
                reason=reason,
            )
        )
    return CapabilitiesResponse(items=items)
