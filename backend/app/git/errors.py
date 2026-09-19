"""Git-specific exception types."""


class GitRepositoryError(ValueError):
    """Raised when a repository cannot be validated or inspected."""


class GitCommandError(GitRepositoryError):
    """Raised when a Git subprocess fails unexpectedly."""


class RepositoryValidationError(GitRepositoryError):
    """Raised when the repository path is invalid or not a Git work tree."""
