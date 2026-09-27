"""Stable application errors exposed through the API error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def change_not_found(change_id: str) -> AppError:
    return AppError(
        "CHANGE_NOT_FOUND",
        "The requested Change does not exist.",
        status_code=404,
        details={"change_id": change_id},
    )


def adapter_unavailable(capability: str) -> AppError:
    return AppError(
        "CAPABILITY_UNAVAILABLE",
        f"The {capability} capability has not been connected yet.",
        status_code=503,
        details={"capability": capability},
    )


def revision_conflict(*, expected: int, actual: int) -> AppError:
    return AppError(
        "REVISION_CONFLICT",
        "The Change was updated by another operation.",
        status_code=409,
        details={"expected_revision": expected, "actual_revision": actual},
    )


def idempotency_conflict(scope: str) -> AppError:
    return AppError(
        "IDEMPOTENCY_KEY_REUSED",
        "The idempotency key was already used for a different request.",
        status_code=409,
        details={"scope": scope},
    )


def invalid_transition(current: str, target: str) -> AppError:
    return AppError(
        "INVALID_CHANGE_TRANSITION",
        "The requested lifecycle transition is not allowed.",
        status_code=409,
        details={"current_state": current, "target_state": target},
    )


def transition_guard_failed(target: str, missing: list[str]) -> AppError:
    return AppError(
        "TRANSITION_GUARD_FAILED",
        "Authoritative evidence does not permit the requested transition.",
        status_code=409,
        details={"target_state": target, "missing_requirements": missing},
    )


def policy_denied(reason_code: str, explanation: str) -> AppError:
    return AppError(
        "POLICY_DENIED",
        explanation,
        status_code=403,
        details={"reason_code": reason_code},
    )


def provider_repository_unresolved(repository_path: str) -> AppError:
    return AppError(
        "PROVIDER_REPOSITORY_UNRESOLVED",
        "The Change's repository has no resolvable GitHub remote.",
        status_code=409,
        details={"repository_path": repository_path},
    )


def no_pull_request_to_compensate(change_id: str) -> AppError:
    return AppError(
        "NO_PULL_REQUEST_TO_COMPENSATE",
        "This Change has no succeeded pull-request-creation operation to compensate.",
        status_code=409,
        details={"change_id": change_id},
    )


def grant_binding_invalid(grant_id: str) -> AppError:
    return AppError(
        "CREDENTIAL_GRANT_BINDING_INVALID",
        "The credential grant is not bound to the requesting actor and Change.",
        status_code=403,
        details={"grant_id": grant_id},
    )


def recovery_plan_not_found(plan_id: str) -> AppError:
    return AppError(
        "RECOVERY_PLAN_NOT_FOUND",
        "The requested recovery plan does not exist.",
        status_code=404,
        details={"plan_id": plan_id},
    )


def passport_not_found(change_id: str) -> AppError:
    return AppError(
        "PASSPORT_NOT_FOUND",
        "No Change Passport has been generated for this Change yet.",
        status_code=404,
        details={"change_id": change_id},
    )


def tool_not_found(tool_id: str) -> AppError:
    return AppError(
        "TOOL_NOT_FOUND",
        "The requested tool is not registered.",
        status_code=404,
        details={"tool_id": tool_id},
    )


def tool_executable_unreadable(executable_path: str) -> AppError:
    return AppError(
        "TOOL_EXECUTABLE_UNREADABLE",
        "The tool's executable could not be read to compute its identity.",
        status_code=400,
        details={"executable_path": executable_path},
    )


def tool_trust_denied(tool_id: str) -> AppError:
    return AppError(
        "TOOL_TRUST_DENIED",
        "This tool is explicitly denied and may not be launched.",
        status_code=403,
        details={"tool_id": tool_id},
    )


def evidence_store_inside_repository(
    database_path: str, repository_root: str, *, user_directory: bool = False
) -> AppError:
    if user_directory:
        # A repository at the user profile (or above LOCALAPPDATA) also encloses
        # the default store and migrate-store's default target.
        message = (
            "The evidence store is inside a Git working tree that encloses your "
            "user profile or LOCALAPPDATA, so the default store location cannot be "
            "used. Set CHANGE_ASSURANCE_DB_PATH to a location outside every "
            "repository (and pass the same path to `sentinel migrate-store --to` "
            "if you are moving an existing store)."
        )
    else:
        message = (
            "The evidence store is inside a Git working tree that an agent could "
            "reach. Move it with `sentinel migrate-store` (or `python -m "
            "backend.app.cli migrate-store`), or set CHANGE_ASSURANCE_DB_PATH to a "
            "location outside every repository."
        )
    return AppError(
        "EVIDENCE_STORE_INSIDE_REPOSITORY",
        message,
        status_code=409,
        details={"database_path": database_path, "repository_root": repository_root},
    )


def evidence_store_migration_required(legacy_path: str, database_path: str) -> AppError:
    return AppError(
        "EVIDENCE_STORE_MIGRATION_REQUIRED",
        "A legacy evidence store exists in this directory and the default store has "
        "not been created yet. Sentinel refuses to start with a new, empty store. "
        "Run `sentinel migrate-store` (or `python -m backend.app.cli migrate-store`) "
        "from this directory to move it first, or set CHANGE_ASSURANCE_DB_PATH to "
        "choose a store explicitly.",
        status_code=409,
        details={"legacy_path": legacy_path, "database_path": database_path},
    )


def evidence_store_unsafe_location(path: str) -> AppError:
    return AppError(
        "EVIDENCE_STORE_UNSAFE_LOCATION",
        "The evidence store location is a junction or symbolic link. Sentinel "
        "keeps its store only in a real directory it created.",
        status_code=409,
        details={"path": path},
    )


def evidence_store_migration_source_missing(path: str) -> AppError:
    return AppError(
        "EVIDENCE_STORE_MIGRATION_SOURCE_MISSING",
        "There is no evidence store database at the migration source.",
        status_code=404,
        details={"path": path},
    )


def evidence_store_migration_target_exists(path: str) -> AppError:
    return AppError(
        "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS",
        "The migration target already exists. migrate-store never overwrites an "
        "existing store or token; choose another --to or remove it yourself.",
        status_code=409,
        details={"path": path},
    )


def evidence_store_migration_integrity_failed(reason: str) -> AppError:
    return AppError(
        "EVIDENCE_STORE_MIGRATION_INTEGRITY_FAILED",
        "The migrated copy failed its integrity check and was removed. The "
        "source store was not changed.",
        status_code=500,
        details={"reason": reason},
    )
