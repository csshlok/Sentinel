"""Offline recipient trust commands; no Sentinel API or database is needed."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from backend.app.passport.trust import TrustRegistry, load_public_key

trust_app = typer.Typer(no_args_is_help=True)


def _output(value: object, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))
    else:
        typer.echo(json.dumps(value, sort_keys=True, indent=2))


def _fail(error: Exception) -> None:
    typer.echo(f"Trust registry error: {error}", err=True)
    raise typer.Exit(1)


@trust_app.command("add")
def trust_add(
    fingerprint_value: str = typer.Argument("", metavar="FINGERPRINT"),
    label: str = typer.Option(..., "--label"),
    key: Path | None = typer.Option(None, "--key", help="Public SPKI as PEM or DER."),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Explicitly trust a grouped fingerprint or a public SPKI file."""
    try:
        spki = load_public_key(key) if key is not None else None
        value = TrustRegistry().add(fingerprint_value=fingerprint_value or None,
                                    spki=spki, label=label)
    except (OSError, ValueError) as exc:
        _fail(exc)
    _output({"fingerprint": value, "label": label}, as_json=json_)


@trust_app.command("list")
def trust_list(json_: bool = typer.Option(False, "--json")) -> None:
    """List locally trusted installation fingerprints."""
    try:
        items = TrustRegistry().list()
    except (OSError, ValueError) as exc:
        _fail(exc)
    _output({"items": items, "count": len(items)}, as_json=json_)


@trust_app.command("remove")
def trust_remove(fingerprint_value: str, json_: bool = typer.Option(False, "--json")) -> None:
    """Remove explicit trust for one fingerprint."""
    try:
        removed = TrustRegistry().remove(fingerprint_value)
    except (OSError, ValueError) as exc:
        _fail(exc)
    _output({"fingerprint": fingerprint_value, "removed": removed}, as_json=json_)


@trust_app.command("revoke")
def trust_revoke(
    fingerprint_value: str,
    reason: str = typer.Option("Local revocation", "--reason"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Mark a fingerprint locally revoked, including if trust was removed."""
    try:
        TrustRegistry().revoke(fingerprint_value, reason=reason)
    except (OSError, ValueError) as exc:
        _fail(exc)
    _output({"fingerprint": fingerprint_value, "revoked": True}, as_json=json_)


@trust_app.command("rotate")
def trust_rotate(statement: Path, json_: bool = typer.Option(False, "--json")) -> None:
    """Accept a new key only with a valid statement from the trusted old key."""
    try:
        if not statement.is_file() or statement.stat().st_size > 16_384:
            raise ValueError("Rotation statement missing or oversized")
        body = json.loads(statement.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise ValueError("Rotation statement must be an object")
        value = TrustRegistry().apply_rotation(body)
    except (OSError, ValueError, RecursionError) as exc:
        _fail(exc)
    _output({"fingerprint": value, "rotated": True}, as_json=json_)
