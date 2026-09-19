from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.contracts.models import ChangeContract, ChangeView, ReviewState
from backend.app.contracts.ports import PolicyPort
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.identity.models import Delegation
from backend.app.identity.repository import DelegationRepository
from backend.app.policy.service import DelegationPolicyEngine

REPO_PATH = "C:\\work\\repo"


def _engine(tmp_path, now: datetime) -> tuple[DelegationPolicyEngine, DelegationRepository, Database]:
    database = Database(tmp_path / "policy.sqlite3")
    database.initialize()
    repository = DelegationRepository(database)
    engine = DelegationPolicyEngine(repository, clock=lambda: now)
    return engine, repository, database


def _change(database: Database, **contract_overrides: object) -> ChangeView:
    now = datetime.now(UTC)
    view = ChangeView(
        id=uuid4(),
        title="Test change",
        intent="Exercise policy",
        repository_path=REPO_PATH,
        created_at=now,
        updated_at=now,
        review_state=ReviewState.NO_CHANGES,
        contract=ChangeContract(**contract_overrides),
    )
    ChangeRepository(database).create(
        StoredChange(
            id=view.id,
            title=view.title,
            intent=view.intent,
            repository_path=view.repository_path,
            created_at=now,
            updated_at=now,
            last_refreshed_at=None,
            git_summary=None,
            verification=None,
            contract=view.contract,
        )
    )
    return view


def _delegate(
    repository: DelegationRepository,
    *,
    actor_id,
    change_id,
    now: datetime,
    scopes: list[str],
    use_limit: int | None = None,
) -> Delegation:
    delegation = Delegation(
        id=uuid4(),
        grantor_id=uuid4(),
        grantee_id=actor_id,
        change_id=change_id,
        repository_path=REPO_PATH,
        scopes=scopes,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        use_limit=use_limit,
    )
    repository.create(delegation)
    return delegation


def test_policy_engine_satisfies_the_frozen_port(tmp_path) -> None:
    engine, _, _ = _engine(tmp_path, datetime.now(UTC))
    assert isinstance(engine, PolicyPort)


def test_denies_without_any_delegation(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, _, database = _engine(tmp_path, now)
    change = _change(database)

    decision = engine.evaluate(uuid4(), change, "github.pr.create", {})

    assert decision.allowed is False
    assert decision.reason_code == "AUTHORITY_NOT_FOUND"


def test_allows_when_delegated_and_within_contract(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database)
    _delegate(
        repository,
        actor_id=actor_id,
        change_id=change.id,
        now=now,
        scopes=["github.pr.create"],
    )

    decision = engine.evaluate(actor_id, change, "github.pr.create", {})

    assert decision.allowed is True
    assert decision.reason_code == "ALLOWED"


def test_denies_default_denied_operation_even_with_delegation(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database)
    _delegate(
        repository,
        actor_id=actor_id,
        change_id=change.id,
        now=now,
        scopes=["github.force_push"],
    )

    decision = engine.evaluate(actor_id, change, "github.force_push", {})

    assert decision.allowed is False
    assert decision.reason_code == "OPERATION_NOT_PERMITTED"
    assert decision.risk_level.value == "HIGH"


def test_denies_forbidden_path(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database, forbidden_paths=["secrets"])
    _delegate(
        repository,
        actor_id=actor_id,
        change_id=change.id,
        now=now,
        scopes=["git.recovery.commit"],
    )

    decision = engine.evaluate(
        actor_id,
        change,
        "git.recovery.commit",
        {"target_path": "secrets/prod.env"},
    )

    assert decision.allowed is False
    assert decision.reason_code == "PATH_FORBIDDEN"


def test_denies_operation_outside_authority_ceiling(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database, authority_ceiling=["github.repo.read"])
    _delegate(
        repository,
        actor_id=actor_id,
        change_id=change.id,
        now=now,
        scopes=["github.pr.create"],
    )

    decision = engine.evaluate(actor_id, change, "github.pr.create", {})

    assert decision.allowed is False
    assert decision.reason_code == "OPERATION_NOT_PERMITTED"


def test_denies_risk_above_contract_ceiling_and_requires_approval(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database, max_risk="LOW")
    _delegate(
        repository,
        actor_id=actor_id,
        change_id=change.id,
        now=now,
        scopes=["assurance.run"],
    )

    decision = engine.evaluate(
        actor_id, change, "assurance.run", {"risk_level": "HIGH"}
    )

    assert decision.allowed is False
    assert decision.reason_code == "RISK_TOO_HIGH"
    assert decision.required_approval is True


def test_known_operations_get_a_real_default_risk_without_a_caller_hint(tmp_path) -> None:
    """Threat model finding #7: no call site ever populated

    parameters["risk_level"], so the risk gate was dead code -- LOW always
    won by default and RISK_TOO_HIGH could never fire regardless of an
    operation's true risk. github.pr.create and recovery.execute now get a
    real default classification (MEDIUM, matching ChangeContract's own
    default max_risk so ordinary flows are unaffected) even when the
    caller passes no risk_level parameter at all.
    """

    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database, max_risk="LOW")
    _delegate(
        repository, actor_id=actor_id, change_id=change.id, now=now,
        scopes=["github.pr.create", "recovery.execute", "agent.launch"],
    )

    pr_decision = engine.evaluate(actor_id, change, "github.pr.create", {})
    assert pr_decision.allowed is False
    assert pr_decision.reason_code == "RISK_TOO_HIGH"

    recovery_decision = engine.evaluate(actor_id, change, "recovery.execute", {})
    assert recovery_decision.allowed is False
    assert recovery_decision.reason_code == "RISK_TOO_HIGH"

    # An operation with no known default stays LOW, so a LOW-ceiling
    # contract still allows it -- the fix adds real defaults, it doesn't
    # make every operation risky by fiat.
    unclassified = engine.evaluate(actor_id, change, "agent.launch", {})
    assert unclassified.allowed is True


def test_use_limit_is_actually_enforced_across_calls(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database)
    delegation = _delegate(
        repository, actor_id=actor_id, change_id=change.id, now=now,
        scopes=["agent.launch"], use_limit=1,
    )

    first = engine.evaluate(actor_id, change, "agent.launch", {})
    assert first.allowed is True
    assert repository.get(delegation.id).uses == 1

    second = engine.evaluate(actor_id, change, "agent.launch", {})
    assert second.allowed is False
    assert second.reason_code == "AUTHORITY_EXHAUSTED"
    # The second, denied attempt must not have consumed a further use.
    assert repository.get(delegation.id).uses == 1


def test_a_denied_operation_does_not_consume_a_delegation_use(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _engine(tmp_path, now)
    actor_id = uuid4()
    change = _change(database, forbidden_paths=["secrets"])
    delegation = _delegate(
        repository, actor_id=actor_id, change_id=change.id, now=now,
        scopes=["git.recovery.commit"], use_limit=1,
    )

    decision = engine.evaluate(
        actor_id, change, "git.recovery.commit", {"target_path": "secrets/prod.env"}
    )

    assert decision.allowed is False
    assert repository.get(delegation.id).uses == 0
