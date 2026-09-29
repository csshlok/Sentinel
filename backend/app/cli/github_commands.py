"""GitHub App registration and exact-head Check commands through the local API."""

from __future__ import annotations

import json
from uuid import UUID

import typer

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError
from backend.app.providers.github_app import app_provider_name


github_app_admin = typer.Typer(no_args_is_help=True)


def _emit(call, *, as_json: bool) -> None:
    try:
        value = call()
    except ApiError as exc:
        value = {"error": {"code": exc.code, "message": exc.message,
                           "details": exc.details}}
        code = 1
    except ApiConnectionError:
        value = {"error": {"code": "CONNECTION_ERROR",
                           "message": "Could not reach the local Sentinel API."}}
        code = 2
    else:
        code = 0
    typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":"))
               if as_json else json.dumps(value, sort_keys=True, indent=2))
    raise typer.Exit(code)


def github_check(
    change_id: UUID,
    decline_app: bool = typer.Option(False, "--decline-app",
                                    help="Use a lesser commit status via the configured GitHub token."),
    api_url: str = typer.Option("http://127.0.0.1:8000", "--api-url",
                                envvar="CHANGE_ASSURANCE_API_URL"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Publish the Change's signed Passport claims on its recorded PR head."""
    _emit(lambda: ApiClient(api_url)._request(
        "POST", f"/api/v1/changes/{change_id}/providers/github/checks"
        + ("?decline_app=true" if decline_app else "")),
        as_json=json_)


@github_app_admin.command("create")
def github_app_create(
    owner: str,
    account_kind: str = typer.Option("user", "--account-kind"),
    api_url: str = typer.Option("http://127.0.0.1:8000", "--api-url",
                                envvar="CHANGE_ASSURANCE_API_URL"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Start a local one-time GitHub App registration callback."""
    if account_kind not in {"user", "organization"}:
        raise typer.BadParameter("Choose user or organization", param_hint="--account-kind")
    try:
        app_provider_name(owner)
    except ValueError as exc:
        raise typer.BadParameter("Invalid GitHub account name", param_hint="owner") from exc
    _emit(lambda: ApiClient(api_url)._request(
        "POST", "/api/v1/providers/github/app/flows",
        json_body={"owner": owner, "account_kind": account_kind}), as_json=json_)


@github_app_admin.command("status")
def github_app_status(
    owner: str,
    api_url: str = typer.Option("http://127.0.0.1:8000", "--api-url",
                                envvar="CHANGE_ASSURANCE_API_URL"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Report whether an owner has a brokered GitHub App configuration."""
    try:
        app_provider_name(owner)
    except ValueError as exc:
        raise typer.BadParameter("Invalid GitHub account name", param_hint="owner") from exc
    _emit(lambda: ApiClient(api_url)._request(
        "GET", f"/api/v1/providers/github/app/status/{owner}"), as_json=json_)
