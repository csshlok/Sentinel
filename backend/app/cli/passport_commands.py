"""Offline recipient trust commands; no Sentinel API or database is needed."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

import typer
from click.exceptions import UsageError as ClickUsageError
from typer._click.exceptions import UsageError
from typer.core import TyperCommand

from backend.app.passport.trust import TrustRegistry, load_public_key
from backend.app.passport.cng import CngKey
from backend.app.passport.identity import active_key_name, activate_key_name
from backend.app.passport.trust import normalize_fingerprint
from backend.app.passport.verify import verify_bundle
from backend.app.passport.format import MAX_BUNDLE_BYTES
from backend.app.cli.client import ApiClient
from backend.app.providers.http_transport import TransportTimeout

trust_app = typer.Typer(no_args_is_help=True)


class VerifyUsageCommand(TyperCommand):
    """Give verifier syntax errors the documented standalone exit code 3."""

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        as_json = "--json" in args  # Typer consumes this mutable list before raising.
        try:
            return super().parse_args(ctx, args)
        except (UsageError, ClickUsageError) as exc:
            if as_json:
                typer.echo(json.dumps({"verdict": "USAGE_ERROR",
                                       "reason": exc.format_message()},
                                      sort_keys=True, separators=(",", ":")))
                raise typer.Exit(3) from exc
            exc.exit_code = 3
            raise


def _output(value: object, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))
    else:
        typer.echo(json.dumps(value, sort_keys=True, indent=2))


def _fail(error: Exception) -> None:
    typer.echo(f"Trust registry error: {error}", err=True)
    raise typer.Exit(1)


def rotate_identity_command(*, output: Path, as_json: bool) -> None:
    """Activate a successor, then publish its old-key-signed statement."""
    new_name = f"Sentinel Passport v2 ES256 {uuid4()}"
    created = False
    activated = False
    output_created = False
    old_name: str | None = None
    try:
        if output.exists():
            raise FileExistsError("Rotation statement path already exists")
        old_name = active_key_name()
        with CngKey.open_existing(name=old_name) as old:
            created = True  # A failed open may already have finalized the new key.
            with CngKey.open(name=new_name) as successor:
                statement = TrustRegistry().sign_rotation(
                    old_key=old, new_spki=successor.public_spki())
                body = json.dumps(statement, sort_keys=True, separators=(",", ":"))
                activate_key_name(new_name)
                activated = True
                with output.open("x", encoding="utf-8") as stream:
                    output_created = True
                    stream.write(body + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
        _output({"rotation_statement": str(output),
                 "old_fingerprint": statement["old_fingerprint"],
                 "new_fingerprint": statement["new_fingerprint"]}, as_json=as_json)
    except Exception as exc:
        if output_created:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
        if activated and old_name is not None:
            try:
                activate_key_name(old_name)
                activated = False
            except Exception:
                pass  # Keep the successor key if rollback could not restore the selector.
        if created and not activated:
            try:
                CngKey.delete_unactivated_successor(name=new_name)
            except Exception:
                pass
        _fail(exc)


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


def verify_command(
    bundle: Path | None = typer.Argument(None, metavar="BUNDLE"),
    key: str | None = typer.Option(None, "--key", help="Explicit expected signer fingerprint."),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Verify a saved .sentinel bundle offline with recipient trust."""
    if bundle is None or not bundle.is_file():
        _output({"verdict": "USAGE_ERROR", "reason": "Provide an existing bundle path."},
                as_json=json_)
        raise typer.Exit(3)
    if key is not None:
        try:
            key = normalize_fingerprint(key)
        except ValueError as exc:
            _output({"verdict": "USAGE_ERROR", "reason": str(exc)}, as_json=json_)
            raise typer.Exit(3) from exc
    result = verify_bundle(bundle, expected_fingerprint=key)
    _output(asdict(result), as_json=json_)
    raise typer.Exit({"VALID": 0, "INVALID": 1, "INDETERMINATE": 2}[result.verdict])


def export_passport_command(
    change_id: UUID, *, api_url: str, output: Path | None, as_json: bool,
) -> None:
    """Ask the authenticated local API for a Change-ID-built ZIP and save it."""
    client = ApiClient(api_url)
    headers = {"Accept": "application/vnd.sentinel.passport+zip"}
    if client.token:
        headers["Authorization"] = f"Bearer {client.token}"
    try:
        response = client.transport.request(
            "POST", f"{client.base_url}/api/v1/changes/{change_id}/passport/v2/bundle",
            headers=headers, body=None, timeout_seconds=client.timeout_seconds,
        )
    except TransportTimeout as exc:
        _output({"error": "CONNECTION_ERROR", "message": str(exc)}, as_json=as_json)
        raise typer.Exit(2) from exc
    if response.status_code != 200:
        try:
            error = json.loads(response.body).get("error", {})
        except (ValueError, TypeError):
            error = {}
        _output({"error": error.get("code", "EXPORT_FAILED"),
                 "message": error.get("message", "Passport export failed")}, as_json=as_json)
        raise typer.Exit(1)
    if len(response.body) > MAX_BUNDLE_BYTES or not response.body.startswith(b"PK\x03\x04"):
        _output({"error": "INVALID_EXPORT", "message": "API returned an invalid bundle."},
                as_json=as_json)
        raise typer.Exit(1)
    destination = output or Path.cwd() / f"change-{change_id}.sentinel"
    try:
        with destination.open("xb") as stream:
            stream.write(response.body)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        _output({"error": "WRITE_FAILED", "message": str(exc)}, as_json=as_json)
        raise typer.Exit(1) from exc
    digest = next((value for name, value in response.headers.items()
                   if name.lower() == "x-sentinel-payload-sha256"), None)
    _output({"path": str(destination), "payload_sha256": digest,
             "size": len(response.body)}, as_json=as_json)
