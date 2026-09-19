from backend.app.contracts.ports import CredentialStorePort
from backend.app.credentials.memory_store import InMemoryCredentialStore


def test_satisfies_the_frozen_credential_store_port() -> None:
    assert isinstance(InMemoryCredentialStore(), CredentialStorePort)


def test_put_get_delete_round_trip() -> None:
    store = InMemoryCredentialStore()
    assert store.get("github") is None

    store.put("github", "ghp_canary_token")
    assert store.get("github") == "ghp_canary_token"

    store.put("github", "ghp_replaced_token")
    assert store.get("github") == "ghp_replaced_token"

    assert store.delete("github") is True
    assert store.get("github") is None


def test_delete_missing_secret_returns_false() -> None:
    store = InMemoryCredentialStore()
    assert store.delete("does-not-exist") is False
