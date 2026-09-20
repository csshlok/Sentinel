"""Stable Git-domain errors exposed through the shared API envelope."""

from __future__ import annotations

from typing import Any

from backend.app.core.errors import AppError


class GitRepositoryError(AppError):
    """Base class for expected Git inspection failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=status_code, details=details)


class GitCommandError(GitRepositoryError):
    def __init__(
        self,
        message: str = "Git could not inspect the repository.",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            "GIT_COMMAND_FAILED", message, status_code=500, details=details
        )


class RepositoryValidationError(GitRepositoryError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code=400, details=details)


class GitExecutableNotFoundError(GitRepositoryError):
    """Git is not installed or not resolvable on PATH.

    A distinct, stable 4xx (not the generic 500 ``GitCommandError`` uses for
    unexpected inspection failures): this is a client-actionable environment
    problem -- install Git -- not a server fault, so a caller (the desktop
    UI in particular) can render a specific, explainable message rather than
    an opaque "something went wrong".
    """

    def __init__(self) -> None:
        super().__init__(
            "GIT_EXECUTABLE_NOT_FOUND",
            "Git is not installed or could not be located on PATH.",
            status_code=424,
        )
