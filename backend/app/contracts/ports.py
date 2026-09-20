"""Frozen protocol boundaries for independently owned backend modules."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from backend.app.contracts.models import (
    AgentAttachRequest,
    AgentLaunchRequest,
    AgentRun,
    AssurancePlan,
    AssuranceRun,
    ChainVerificationResult,
    ChangePassport,
    ChangeView,
    CredentialGrant,
    DependencyReport,
    DriftReport,
    EnvironmentDrift,
    EnvironmentPassport,
    GitCheckpoint,
    GitCheckpointComparison,
    GitSummary,
    LifecycleFacts,
    Outcome,
    PolicyDecision,
    ProviderOperation,
    ProviderOperationRequest,
    RecoveryPlan,
    ReplayTimeline,
    RepositoryInfo,
    ToolManifest,
    ToolObservation,
    ToolTrustDecision,
    VerificationRequest,
    VerificationResult,
)


@runtime_checkable
class GitInspectionPort(Protocol):
    """Compatibility port implemented by the existing Git adapter."""

    def validate_repository(self, path: str) -> RepositoryInfo:
        """Validate a path and return its canonical committed Git repository."""

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        """Read the current Git working tree without mutating it."""


@runtime_checkable
class VerificationPort(Protocol):
    """Compatibility port implemented by the existing verification runner."""

    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
    ) -> VerificationResult:
        """Run one bounded verification command in the repository root."""


@runtime_checkable
class GitStatePort(Protocol):
    def capture(
        self,
        change_id: UUID,
        name: str,
        repository_path: str,
        evidence_revision: int,
        patch_limit_bytes: int,
    ) -> GitCheckpoint:
        """Capture a read-only Git checkpoint."""

    def compare(
        self, baseline: GitCheckpoint, current: GitCheckpoint
    ) -> GitCheckpointComparison:
        """Compare two checkpoints without mutating the repository."""


@runtime_checkable
class AgentLauncherPort(Protocol):
    def launch(
        self,
        change_id: UUID,
        repository_path: str,
        request: AgentLaunchRequest,
        output_limit_bytes: int,
    ) -> AgentRun:
        """Launch an invocation; Windows implementations supervise its process tree."""

    def attach(self, change_id: UUID, request: AgentAttachRequest) -> AgentRun:
        """Record declared metadata for an externally launched invocation."""

    def stop(self, run_id: UUID) -> AgentRun:
        """Request cancellation, including the supervised tree when available."""

    def pause(self, run_id: UUID) -> AgentRun:
        """Suspend the top-level process only (Windows-first, no descendants)."""

    def resume(self, run_id: UUID) -> AgentRun:
        """Resume a previously paused top-level process."""


@runtime_checkable
class EnvironmentPort(Protocol):
    def capture(self, change_id: UUID, repository_path: str) -> EnvironmentPassport:
        """Capture a redacted, bounded environment passport."""

    def compare(
        self, baseline: EnvironmentPassport, current: EnvironmentPassport
    ) -> EnvironmentDrift:
        """Compare passports without claiming causal attribution."""


@runtime_checkable
class DependencyPort(Protocol):
    def scan(
        self,
        change_id: UUID,
        checkpoint: GitCheckpoint,
        repository_path: str,
        *,
        baseline: GitCheckpoint | None = None,
    ) -> DependencyReport:
        """Compare supported manifests and lockfiles.

        Old-side content is read from ``baseline.head_sha`` when a baseline
        is given, else from ``checkpoint.head_sha`` (the prior, narrower
        default). New-side content is always the working tree. Passing the
        Change's actual baseline checkpoint is what lets this catch
        dependency edits the agent already committed by the time
        ``checkpoint`` was captured -- comparing only checkpoint.head_sha
        against the working tree misses anything already folded into that
        same commit.
        """


@runtime_checkable
class AssurancePort(Protocol):
    def discover(
        self,
        change: ChangeView,
        checkpoint: GitCheckpoint,
        environment: EnvironmentPassport | None,
        dependencies: DependencyReport | None,
    ) -> AssurancePlan:
        """Build an evidence-selected assurance plan."""

    def run(
        self,
        change: ChangeView,
        plan: AssurancePlan,
        repository_path: str,
        output_limit_bytes: int,
    ) -> list[AssuranceRun]:
        """Execute bounded checks and return structured results."""


@runtime_checkable
class LifecycleFactsPort(Protocol):
    def get_facts(self, change: ChangeView, target_state: str) -> LifecycleFacts:
        """Compose authoritative server-side facts for a transition."""


@runtime_checkable
class CredentialStorePort(Protocol):
    def put(self, key: str, secret: str) -> None:
        """Store a durable secret outside application persistence."""

    def get(self, key: str) -> str | None:
        """Return a secret only to the broker boundary."""

    def delete(self, key: str) -> bool:
        """Remove a broker-owned secret."""


@runtime_checkable
class CredentialBrokerPort(Protocol):
    def issue_grant(
        self, actor_id: UUID, change_id: UUID, scopes: list[str], ttl_seconds: int
    ) -> CredentialGrant:
        """Issue a short-lived internal capability grant."""

    def revoke(self, grant_id: UUID) -> CredentialGrant:
        """Revoke an internal grant."""


@runtime_checkable
class PolicyPort(Protocol):
    def evaluate(
        self,
        actor_id: UUID,
        change: ChangeView,
        operation: str,
        parameters: dict[str, object],
    ) -> PolicyDecision:
        """Return an explainable, default-deny policy decision."""


@runtime_checkable
class ProviderPort(Protocol):
    def execute(
        self, request: ProviderOperationRequest, grant: CredentialGrant
    ) -> ProviderOperation:
        """Execute one brokered provider operation."""


@runtime_checkable
class OutcomePort(Protocol):
    def refresh(self, change: ChangeView) -> list[Outcome]:
        """Refresh provider outcomes tied to exact commit identities."""


@runtime_checkable
class RecoveryPort(Protocol):
    def plan(self, change: ChangeView) -> RecoveryPlan:
        """Preview supported compensations and all known limitations."""

    def execute(
        self, change: ChangeView, plan: RecoveryPlan, approval_token: str
    ) -> RecoveryPlan:
        """Execute an approved recovery plan without rewriting history."""


@runtime_checkable
class PassportPort(Protocol):
    def build(self, change: ChangeView) -> ChangePassport:
        """Build a deterministic Passport from retained evidence."""


@runtime_checkable
class ReplayPort(Protocol):
    def reconstruct(self, change_id: UUID) -> ReplayTimeline:
        """Reconstruct and hash-verify a Change's causal timeline. No re-execution."""

    def verify_chain(self, change_id: UUID) -> ChainVerificationResult:
        """Recompute and verify the per-Change hash chain, without the full timeline."""


@runtime_checkable
class ToolRegistryPort(Protocol):
    def resolve_or_register(self, executable_path: str, *, source: str) -> ToolManifest:
        """Resolve a top-level executable's identity, registering it if unseen."""

    def get(self, tool_id: UUID) -> ToolManifest:
        """Return one tool manifest."""

    def list(self) -> list[ToolManifest]:
        """List the full tool registry."""

    def record_observation(
        self,
        tool_id: UUID,
        change_id: UUID,
        agent_run_id: UUID | None,
        capabilities_observed: list[str],
        context: str,
    ) -> ToolObservation:
        """Record one observation of a tool being used by a Change."""

    def declare_manifest(self, change_id: UUID, manifest_path: str) -> ToolManifest:
        """Register (or resolve) a declared tool/MCP manifest for a Change.

        Reading the declared config file is a bounded filesystem read of a
        static artifact -- not interception of a running process -- so it
        stays inside the read-only-collector boundary (B.1). Records a
        "declared_manifest" observation against the Change, same as a
        launcher executable gets a "launch" observation.
        """

    def decide_trust(
        self,
        tool_id: UUID,
        actor_id: UUID,
        decision: str,
        scope: str,
        reason: str | None,
        change_id: UUID | None,
    ) -> ToolTrustDecision:
        """Record an explicit human/actor trust decision for a tool."""

    def check_drift(self, tool_id: UUID) -> DriftReport:
        """Compare current identity/capabilities against the last APPROVED snapshot."""
