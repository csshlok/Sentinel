"""Versioned, strict contracts shared across Change Assurance modules."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


TrimmedTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
TrimmedIntent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
RepositoryPath = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32767)
]
PathPattern = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)
]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
LongText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
ExecutableName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
CommandArgument = Annotated[str, StringConstraints(max_length=2048)]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CapabilityScope = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]


class ContractModel(BaseModel):
    """Strict base for public contracts and port payloads."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=False,
        frozen=True,
        validate_default=True,
    )


class ChangedPathStatus(StrEnum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"
    COPIED = "COPIED"
    UNTRACKED = "UNTRACKED"
    CONFLICTED = "CONFLICTED"


class PathCategory(StrEnum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    DEPENDENCY = "DEPENDENCY"
    CONFIG = "CONFIG"
    DOCUMENTATION = "DOCUMENTATION"
    OTHER = "OTHER"


class VerificationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"


class ReviewState(StrEnum):
    NO_CHANGES = "NO_CHANGES"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class ChangeLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    LOCALLY_VERIFIED = "LOCALLY_VERIFIED"
    REVIEW_READY = "REVIEW_READY"
    PR_OPEN = "PR_OPEN"
    CI_VERIFIED = "CI_VERIFIED"
    ARTIFACT_BUILT = "ARTIFACT_BUILT"
    DEPLOYED = "DEPLOYED"
    OBSERVING = "OBSERVING"
    STABLE = "STABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RECOVERING = "RECOVERING"
    RECOVERED_VERIFIED = "RECOVERED_VERIFIED"
    RECOVERY_CONFLICT = "RECOVERY_CONFLICT"
    RECOVERY_FAILED = "RECOVERY_FAILED"


class RiskLevel(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CapabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNCONFIGURED = "UNCONFIGURED"
    UNSUPPORTED = "UNSUPPORTED"


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SERVICE = "SERVICE"


class AgentRunStatus(StrEnum):
    ATTACHED = "ATTACHED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class EvidenceStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    PARTIAL = "PARTIAL"


class AssuranceStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class ProviderOperationStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class OutcomeKind(StrEnum):
    PULL_REQUEST = "PULL_REQUEST"
    CI = "CI"
    ARTIFACT = "ARTIFACT"
    DEPLOYMENT = "DEPLOYMENT"


class OutcomeStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"


class RecoveryStatus(StrEnum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    RECOVERED = "RECOVERED"
    PARTIAL = "PARTIAL"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    CONFLICTED = "CONFLICTED"


class RepositoryPathRequest(ContractModel):
    path: RepositoryPath


class RepositoryInfo(ContractModel):
    root: RepositoryPath
    branch: str | None = Field(default=None, max_length=1024)
    head_sha: GitSha


class ChangedPath(ContractModel):
    path: Annotated[str, StringConstraints(min_length=1, max_length=32767)]
    old_path: Annotated[str, StringConstraints(min_length=1, max_length=32767)] | None = None
    status: ChangedPathStatus
    staged: bool
    unstaged: bool
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    category: PathCategory
    binary: bool = False


class GitSummary(ContractModel):
    repository_root: RepositoryPath
    branch: str | None = Field(default=None, max_length=1024)
    head_sha: GitSha
    is_clean: bool
    files: list[ChangedPath] = Field(default_factory=list, max_length=10000)
    total_additions: int = Field(ge=0)
    total_deletions: int = Field(ge=0)
    patch: str
    patch_truncated: bool = False
    untracked_patch_omitted: bool = False
    refreshed_at: AwareDatetime


class VerificationRequest(ContractModel):
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=64)
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class VerificationResult(ContractModel):
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=64)
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    output_truncated: bool = False
    started_at: AwareDatetime
    completed_at: AwareDatetime


class ChangeContract(ContractModel):
    schema_version: Literal[1] = 1
    allowed_paths: list[PathPattern] = Field(default_factory=lambda: ["**"], max_length=256)
    forbidden_paths: list[PathPattern] = Field(default_factory=list, max_length=256)
    expected_outcomes: list[ShortText] = Field(default_factory=list, max_length=128)
    required_checks: list[ShortText] = Field(default_factory=list, max_length=128)
    authority_ceiling: list[CapabilityScope] = Field(default_factory=list, max_length=128)
    allowed_provider_operations: list[CapabilityScope] = Field(default_factory=list, max_length=64)
    max_risk: RiskLevel = RiskLevel.MEDIUM
    recovery_allowed: bool = True

    @field_validator(
        "allowed_paths",
        "forbidden_paths",
        "expected_outcomes",
        "required_checks",
        "authority_ceiling",
        "allowed_provider_operations",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate values are not allowed")
        return values


class ChangeCreateRequest(ContractModel):
    title: TrimmedTitle
    intent: TrimmedIntent
    repository_path: RepositoryPath
    contract: ChangeContract = Field(default_factory=ChangeContract)


class ChangeContractUpdateRequest(ContractModel):
    contract: ChangeContract
    expected_revision: int = Field(ge=1)


class ChangeTransitionRequest(ContractModel):
    target_state: ChangeLifecycleState
    expected_revision: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None


class ChangeCancelRequest(ContractModel):
    expected_revision: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None


class LifecycleFacts(ContractModel):
    repository_valid: bool = False
    contract_present: bool = False
    authority_valid: bool = False
    required_assurance_passed: bool = False
    assurance_fresh: bool = False
    deviations_resolved: bool = False
    required_evidence_complete: bool = False
    pull_request_recorded: bool = False
    ci_passed_for_current_head: bool = False
    artifact_recorded: bool = False
    deployment_recorded: bool = False
    observation_criteria_met: bool = False
    recovery_plan_approved: bool = False
    recovery_verified: bool = False
    recovery_conflict: bool = False
    recovery_failed: bool = False
    unresolved_recovery_actions: bool = False


class ChangeView(ContractModel):
    id: UUID
    title: str
    intent: str
    repository_path: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_refreshed_at: AwareDatetime | None = None
    git_summary: GitSummary | None = None
    verification: VerificationResult | None = None
    review_state: ReviewState
    lifecycle_state: ChangeLifecycleState = ChangeLifecycleState.DRAFT
    revision: int = Field(default=1, ge=1)
    contract: ChangeContract = Field(default_factory=ChangeContract)
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    evidence_revision: int = Field(default=0, ge=0)
    verification_evidence_revision: int | None = Field(default=None, ge=0)
    last_transition_at: AwareDatetime | None = None


class ChangeListResponse(ContractModel):
    items: list[ChangeView]
    count: int = Field(ge=0)


class Capability(ContractModel):
    id: ShortText
    name: ShortText
    state: CapabilityState
    reason: str | None = Field(default=None, max_length=1000)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class CapabilitiesResponse(ContractModel):
    items: list[Capability]


class Actor(ContractModel):
    id: UUID
    kind: ActorKind
    display_name: TrimmedTitle
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    revision: int = Field(default=1, ge=1)


class Delegation(ContractModel):
    id: UUID
    grantor_id: UUID
    grantee_id: UUID
    change_id: UUID
    repository_path: RepositoryPath
    scopes: list[CapabilityScope] = Field(min_length=1, max_length=128)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    use_limit: int | None = Field(default=None, ge=1)
    uses: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> "Delegation":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.use_limit is not None and self.uses > self.use_limit:
            raise ValueError("uses cannot exceed use_limit")
        return self


class AgentLaunchRequest(ContractModel):
    adapter: ShortText
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=128)
    environment_keys: list[ShortText] = Field(default_factory=list, max_length=128)
    timeout_seconds: int = Field(default=900, ge=1, le=86400)


class AgentAttachRequest(ContractModel):
    adapter: ShortText
    external_run_id: ShortText
    declared_started_at: AwareDatetime | None = None


class AgentRun(ContractModel):
    id: UUID
    change_id: UUID
    adapter: str
    status: AgentRunStatus
    top_level_pid: int | None = Field(default=None, ge=1)
    external_run_id: str | None = Field(default=None, max_length=512)
    exit_code: int | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    descendant_control_available: Literal[False] = False
    limitations: list[str] = Field(default_factory=list, max_length=32)


class GitCheckpoint(ContractModel):
    id: UUID
    change_id: UUID
    name: ShortText
    repository_root: RepositoryPath
    branch: str | None = Field(default=None, max_length=1024)
    head_sha: GitSha
    status_digest: Digest
    summary: GitSummary
    evidence_revision: int = Field(ge=1)
    captured_at: AwareDatetime


class GitCheckpointComparison(ContractModel):
    baseline_id: UUID
    current_id: UUID
    branch_moved: bool
    head_changed: bool
    added_paths: list[str] = Field(default_factory=list, max_length=10000)
    removed_paths: list[str] = Field(default_factory=list, max_length=10000)
    changed_paths: list[str] = Field(default_factory=list, max_length=10000)


class EnvironmentFact(ContractModel):
    key: ShortText
    value: str | None = Field(default=None, max_length=4000)
    fingerprint: Digest | None = None
    sensitive: bool = False
    status: EvidenceStatus = EvidenceStatus.CURRENT

    @model_validator(mode="after")
    def protect_sensitive_value(self) -> "EnvironmentFact":
        if self.sensitive and self.value is not None:
            raise ValueError("sensitive facts may not contain raw values")
        if self.value is None and self.fingerprint is None and self.status is EvidenceStatus.CURRENT:
            raise ValueError("a current fact needs a value or fingerprint")
        return self


class EnvironmentPassport(ContractModel):
    id: UUID
    change_id: UUID
    schema_version: Literal[1] = 1
    facts: list[EnvironmentFact] = Field(default_factory=list, max_length=10000)
    captured_at: AwareDatetime
    status: EvidenceStatus = EvidenceStatus.CURRENT
    limitations: list[str] = Field(default_factory=list, max_length=64)


class EnvironmentDrift(ContractModel):
    baseline_id: UUID
    current_id: UUID
    added: list[EnvironmentFact] = Field(default_factory=list)
    removed: list[EnvironmentFact] = Field(default_factory=list)
    changed: list[EnvironmentFact] = Field(default_factory=list)
    unknown: list[EnvironmentFact] = Field(default_factory=list)
    causal_attribution_available: Literal[False] = False


class DependencyChange(ContractModel):
    ecosystem: ShortText
    package: ShortText
    old_version: str | None = Field(default=None, max_length=512)
    new_version: str | None = Field(default=None, max_length=512)
    direct: bool | None = None
    source_path: str = Field(max_length=32767)
    evidence_status: EvidenceStatus = EvidenceStatus.CURRENT
    risk_notes: list[str] = Field(default_factory=list, max_length=32)
    causal_attribution_available: Literal[False] = False


class DependencyReport(ContractModel):
    id: UUID
    change_id: UUID
    checkpoint_id: UUID
    changes: list[DependencyChange] = Field(default_factory=list, max_length=10000)
    unsupported_ecosystems: list[str] = Field(default_factory=list, max_length=64)
    captured_at: AwareDatetime


class AssuranceCheck(ContractModel):
    id: ShortText
    name: ShortText
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=128)
    required: bool = False
    rationale: LongText


class AssurancePlan(ContractModel):
    id: UUID
    change_id: UUID
    checkpoint_id: UUID
    checks: list[AssuranceCheck] = Field(default_factory=list, max_length=256)
    coverage_gaps: list[str] = Field(default_factory=list, max_length=256)
    created_at: AwareDatetime


class AssuranceRun(ContractModel):
    id: UUID
    change_id: UUID
    plan_id: UUID
    checkpoint_id: UUID
    check_id: str
    status: AssuranceStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    started_at: AwareDatetime
    completed_at: AwareDatetime


class PolicyDecision(ContractModel):
    allowed: bool
    reason_code: ShortText
    explanation: LongText
    risk_level: RiskLevel
    required_approval: bool = False


class CredentialGrant(ContractModel):
    id: UUID
    actor_id: UUID
    change_id: UUID
    provider: ShortText
    scopes: list[CapabilityScope] = Field(min_length=1, max_length=128)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "CredentialGrant":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class ProviderOperationRequest(ContractModel):
    provider: ShortText
    operation: CapabilityScope
    change_id: UUID
    actor_id: UUID
    idempotency_key: ShortText
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProviderOperation(ContractModel):
    id: UUID
    request: ProviderOperationRequest
    status: ProviderOperationStatus
    provider_reference: str | None = Field(default=None, max_length=2048)
    safe_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class Outcome(ContractModel):
    id: UUID
    change_id: UUID
    kind: OutcomeKind
    status: OutcomeStatus
    repository: str = Field(max_length=2048)
    head_sha: GitSha
    provider_reference: str = Field(max_length=2048)
    observed_at: AwareDatetime
    details: dict[str, Any] = Field(default_factory=dict)


class RecoveryAction(ContractModel):
    id: UUID
    kind: ShortText
    description: LongText
    supported: bool
    reversible_commit: GitSha | None = None
    provider_reference: str | None = Field(default=None, max_length=2048)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class RecoveryPlan(ContractModel):
    id: UUID
    change_id: UUID
    status: RecoveryStatus = RecoveryStatus.PLANNED
    actions: list[RecoveryAction] = Field(default_factory=list, max_length=1000)
    unsupported_effects: list[str] = Field(default_factory=list, max_length=256)
    conflicts: list[str] = Field(default_factory=list, max_length=256)
    source_checkpoint_id: UUID
    created_at: AwareDatetime
    approved_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None


class EvidenceReference(ContractModel):
    kind: ShortText
    id: UUID
    status: EvidenceStatus
    captured_at: AwareDatetime | None = None


class ChangePassport(ContractModel):
    id: UUID
    change_id: UUID
    schema_version: Literal[1] = 1
    lifecycle_state: ChangeLifecycleState
    actor_ids: list[UUID] = Field(default_factory=list, max_length=128)
    authority_summary: list[str] = Field(default_factory=list, max_length=256)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=10000)
    outcomes: list[UUID] = Field(default_factory=list, max_length=10000)
    limitations: list[str] = Field(default_factory=list, max_length=256)
    recovery_status: RecoveryStatus | None = None
    generated_at: AwareDatetime
    canonical_digest: Digest


class RestorationClass(StrEnum):
    EXACT = "exact"
    CONDITIONAL = "conditional"
    COMPENSATING = "compensating"
    STAGEABLE = "stageable"
    NONE = "none"
    UNKNOWN = "unknown"


class JournalEventType(StrEnum):
    """Closed, namespaced set of mutations this backend can honestly journal.

    Every member corresponds to a mutation of an entity this backend already
    models (see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` Part A). There is no
    `filesystem.write` or `process.spawn` member: the filesystem tracker and
    process supervisor stay cut, so those effects are never claimed here.
    """

    CHANGE_CREATED = "change.created"
    CHANGE_CONTRACT_UPDATED = "change.contract_updated"
    CHANGE_TRANSITIONED = "change.transitioned"
    CHANGE_GIT_SUMMARY_REFRESHED = "change.git_summary_refreshed"
    CHANGE_LEGACY_VERIFICATION_RUN = "change.legacy_verification_run"
    CHANGE_DELETED = "change.deleted"
    DELEGATION_ISSUED = "delegation.issued"
    DELEGATION_REVOKED = "delegation.revoked"
    CREDENTIAL_GRANT_ISSUED = "credential.grant.issued"
    CREDENTIAL_GRANT_REVOKED = "credential.grant.revoked"
    CREDENTIAL_SECRET_RESOLVED = "credential.secret.resolved"
    GIT_CHECKPOINT_CAPTURED = "git.checkpoint.captured"
    AGENT_LAUNCHED = "agent.launched"
    AGENT_ATTACHED = "agent.attached"
    AGENT_STOP_REQUESTED = "agent.stop_requested"
    AGENT_COMPLETED = "agent.completed"
    ENVIRONMENT_PASSPORT_CAPTURED = "environment.passport.captured"
    DEPENDENCY_REPORT_CAPTURED = "dependency.report.captured"
    ASSURANCE_PLAN_CREATED = "assurance.plan.created"
    ASSURANCE_CHECK_COMPLETED = "assurance.check.completed"
    PROVIDER_PULL_REQUEST_CREATED = "provider.pull_request.created"
    PROVIDER_PULL_REQUEST_REFRESHED = "provider.pull_request.refreshed"
    PROVIDER_CI_REFRESHED = "provider.ci_refreshed"
    OUTCOME_RECORDED = "outcome.recorded"
    RECOVERY_PLAN_CREATED = "recovery.plan.created"
    RECOVERY_ACTION_COMPLETED = "recovery.action.completed"
    RECOVERY_PLAN_COMPLETED = "recovery.plan.completed"
    PASSPORT_BUILT = "passport.built"
    POLICY_DECISION_DENIED = "policy.decision.denied"
    TOOL_MANIFEST_REGISTERED = "tool.manifest.registered"
    TOOL_TRUST_DECIDED = "tool.trust.decided"
    TOOL_TRUST_INVALIDATED = "tool.trust.invalidated"


class JournalEvent(ContractModel):
    """One immutable, hash-chained row in a Change's causal timeline.

    The chain is scoped per Change (`seq` is monotonic within `change_id`,
    starting at 1): see A.3/A.7 of the plan for why, and for the explicit
    limitation that this proves within-Change tamper evidence only, not
    cross-Change tamper evidence.
    """

    id: UUID
    change_id: UUID
    seq: int = Field(ge=1)
    event_type: JournalEventType
    actor_id: UUID | None = None
    subject_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    subject_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: AwareDatetime
    prev_event_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    event_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    schema_version: int = Field(default=1, ge=1)


class JournalEffect(ContractModel):
    """A structured before/produced digest transition attached to one event.

    Narrower than the PDF's generic filesystem/process effect model: only
    covers resources that already carry a comparable digest today (see A.2).
    """

    id: UUID
    event_id: UUID
    change_id: UUID
    resource_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    resource_id: UUID
    before_digest: Digest | None = None
    produced_digest: Digest | None = None
    restoration_class: RestorationClass


class JournalEventListResponse(ContractModel):
    items: list[JournalEvent] = Field(default_factory=list, max_length=100000)
    count: int = Field(ge=0)


class ReplayTimeline(ContractModel):
    """Deterministic reconstruction of a Change's causal timeline.

    Trace-only: no re-execution of any kind. See A.7 for the full list of
    explicit non-goals, echoed in `limitations` on every response.
    """

    change_id: UUID
    events: list[JournalEvent] = Field(default_factory=list, max_length=200000)
    effects: list[JournalEffect] = Field(default_factory=list, max_length=200000)
    chain_verified: bool
    first_break_seq: int | None = None
    limitations: list[str] = Field(default_factory=list, max_length=32)
    generated_at: AwareDatetime


class ChainVerificationResult(ContractModel):
    change_id: UUID
    verified: bool
    checked_events: int = Field(ge=0)
    first_break_seq: int | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ToolTrustState(StrEnum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ToolSignatureState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNSIGNED = "unsigned"
    UNKNOWN = "unknown"


class ToolTrustDecisionKind(StrEnum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ToolTrustScope(StrEnum):
    EXACT_VERSION = "exact_version"
    PUBLISHER_POLICY = "publisher_policy"


class ToolObservationContext(StrEnum):
    LAUNCH = "launch"
    ATTACH = "attach"
    DECLARED_MANIFEST = "declared_manifest"


class ToolManifest(ContractModel):
    """A top-level launched executable or explicitly declared tool/MCP
    manifest (see EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md B.1's bounded
    scope -- this governs what top-level executable may launch, never what
    a running agent's descendant process calls).
    """

    id: UUID
    name: ShortText
    version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    publisher: str | None = Field(default=None, max_length=256)
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)]
    artifact_digest: Digest
    signature_state: ToolSignatureState
    capabilities: list[CapabilityScope] = Field(default_factory=list, max_length=128)
    filesystem_scope: list[str] = Field(default_factory=list, max_length=128)
    network_scope: list[str] = Field(default_factory=list, max_length=128)
    credential_requirements: list[CapabilityScope] = Field(default_factory=list, max_length=128)
    trust_state: ToolTrustState
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime


class ToolTrustDecision(ContractModel):
    id: UUID
    tool_id: UUID
    change_id: UUID | None = None
    decided_by_actor_id: UUID
    decision: ToolTrustDecisionKind
    scope: ToolTrustScope
    reason: str | None = Field(default=None, max_length=1000)
    decided_at: AwareDatetime
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: str | None = Field(default=None, max_length=1000)


class ToolObservation(ContractModel):
    id: UUID
    tool_id: UUID
    change_id: UUID
    agent_run_id: UUID | None = None
    observed_at: AwareDatetime
    capabilities_observed: list[CapabilityScope] = Field(default_factory=list, max_length=128)
    context: ToolObservationContext


class DriftReport(ContractModel):
    tool_id: UUID
    drifted: bool
    changed_fields: list[str] = Field(default_factory=list, max_length=32)
    prior_trust_state: ToolTrustState
    new_trust_state: ToolTrustState


class ToolManifestListResponse(ContractModel):
    items: list[ToolManifest] = Field(default_factory=list, max_length=10000)
    count: int = Field(ge=0)


class ToolTrustRequest(ContractModel):
    actor_id: UUID
    decision: ToolTrustDecisionKind
    scope: ToolTrustScope
    reason: str | None = Field(default=None, max_length=1000)
    change_id: UUID | None = None


class ActorCreateRequest(ContractModel):
    kind: ActorKind
    display_name: TrimmedTitle
    provenance: dict[str, Any] = Field(default_factory=dict)


class DelegationCreateRequest(ContractModel):
    grantor_id: UUID
    grantee_id: UUID
    change_id: UUID
    scopes: list[CapabilityScope] = Field(min_length=1, max_length=128)
    ttl_seconds: int = Field(ge=1, le=31_536_000)
    use_limit: int | None = Field(default=None, ge=1)


class DelegationListResponse(ContractModel):
    items: list[Delegation]
    count: int = Field(ge=0)


class CredentialGrantRequest(ContractModel):
    actor_id: UUID
    scopes: list[CapabilityScope] = Field(min_length=1, max_length=128)
    ttl_seconds: int = Field(default=900, ge=1, le=86400)


class ProviderConnectRequest(ContractModel):
    token: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class ProviderConnectionStatus(ContractModel):
    provider: ShortText
    configured: bool


class PullRequestActionRequest(ContractModel):
    actor_id: UUID
    grant_id: UUID
    base_branch: ShortText
    head_branch: ShortText
    title: ShortText
    idempotency_key: ShortText


class OutcomeRefreshRequest(ContractModel):
    grant_id: UUID
    required_check_names: list[ShortText] = Field(default_factory=list, max_length=64)


class OutcomeListResponse(ContractModel):
    items: list[Outcome]
    count: int = Field(ge=0)


class RecoveryExecuteRequest(ContractModel):
    actor_id: UUID
    approval_token: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class AgentLaunchActionRequest(ContractModel):
    actor_id: UUID
    launch: AgentLaunchRequest
    output_limit_bytes: int = Field(default=200_000, ge=0, le=1_048_576)


class AgentAttachActionRequest(ContractModel):
    actor_id: UUID
    attach: AgentAttachRequest


class ActorActionRequest(ContractModel):
    actor_id: UUID


class AssuranceRunActionRequest(ContractModel):
    actor_id: UUID
    output_limit_bytes: int = Field(default=200_000, ge=0, le=1_048_576)


class AgentRunListResponse(ContractModel):
    items: list[AgentRun]
    count: int = Field(ge=0)


class AgentAdapterInfo(ContractModel):
    adapter: ShortText
    executables: dict[str, bool]
    credential_keys: list[str] = Field(default_factory=list)
    descendant_control_available: Literal[False] = False


class AgentAdapterListResponse(ContractModel):
    items: list[AgentAdapterInfo]
    count: int = Field(ge=0)


class GitCheckpointListResponse(ContractModel):
    items: list[GitCheckpoint]
    count: int = Field(ge=0)


class AssuranceRunListResponse(ContractModel):
    items: list[AssuranceRun]
    count: int = Field(ge=0)


class HealthResponse(ContractModel):
    status: str
    api_version: str


class ErrorDetail(ContractModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(ContractModel):
    error: ErrorDetail


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)
