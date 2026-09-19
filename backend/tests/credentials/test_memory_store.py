from backend.app.credentials.memory_store import InMemoryCredentialStore


def test_set_get_delete_round_trip() -> None:
    store = InMemoryCredentialStore()
    assert store.get_secret("github") is None

    store.set_secret("github", "ghp_canary_token")
    assert store.get_secret("github") == "ghp_canary_token"

    store.set_secret("github", "ghp_replaced_token")
    assert store.get_secret("github") == "ghp_replaced_token"

    store.delete_secret("github")
    assert store.get_secret("github") is None


def test_delete_missing_secret_is_a_no_op() -> None:
    store = InMemoryCredentialStore()
    store.delete_secret("does-not-exist")
    assert store.get_secret("does-not-exist") is None
