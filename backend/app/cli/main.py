"""Typer CLI: create/list/show changes, identity, provider, outcome,
recovery, and passport commands, all through `ApiClient` only.

Stable exit codes: 0 success, 1 API error, 2 connection error (Typer's
own usage errors keep Click's default exit code 2 as well, since they
never reach `_run`). `--json` prints exactly one machine-readable
object and no decoration. `NO_COLOR`/`--no-color`/non-TTY output are
all honored the same way, from the first command, not retrofitted.
"""

from __future__ import annotations

import json
import os
import sys
from uuid import UUID

import typer
from rich.console import Console

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

app = typer.Typer(add_completion=False, no_args_is_help=True)
change_app = typer.Typer(no_args_is_help=True)
actor_app = typer.Typer(no_args_is_help=True)
delegation_app = typer.Typer(no_args_is_help=True)
github_app = typer.Typer(no_args_is_help=True)
outcome_app = typer.Typer(no_args_is_help=True)
recovery_app = typer.Typer(no_args_is_help=True)
passport_app = typer.Typer(no_args_is_help=True)
app.add_typer(change_app, name="change")
app.add_typer(actor_app, name="actor")
app.add_typer(delegation_app, name="delegation")
app.add_typer(github_app, name="github")
app.add_typer(outcome_app, name="outcome")
app.add_typer(recovery_app, name="recovery")
app.add_typer(passport_app, name="passport")

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_CONNECTION_ERROR = 2

ApiUrlOption = typer.Option("http://127.0.0.1:8000", "--api-url", envvar="CHANGE_ASSURANCE_API_URL")
JsonOption = typer.Option(False, "--json", help="Emit one machine-readable JSON object and no decoration.")
NoColorOption = typer.Option(False, "--no-color")


def _plain_output(no_color: bool) -> bool:
    return no_color or bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


def _console(no_color: bool) -> Console:
    plain = _plain_output(no_color)
    return Console(no_color=plain, highlight=not plain)


def _run(callback, *, as_json: bool, no_color: bool) -> None:
    console = _console(no_color)
    try:
        result = callback()
    except ApiError as error:
        payload = {
            "error": {"code": error.code, "message": error.message, "details": error.details}
        }
        if as_json:
            typer.echo(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            console.print(f"[red]{error.code}[/red]: {error.message}")
        raise typer.Exit(EXIT_API_ERROR)
    except ApiConnectionError as error:
        message = f"Could not reach the Change Assurance API: {error}"
        payload = {"error": {"code": "CONNECTION_ERROR", "message": message}}
        if as_json:
            typer.echo(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            console.print(f"[red]CONNECTION_ERROR[/red]: {message}")
        raise typer.Exit(EXIT_CONNECTION_ERROR)

    if as_json:
        typer.echo(json.dumps(result, separators=(",", ":"), sort_keys=True))
    else:
        console.print(result)
    raise typer.Exit(EXIT_OK)


@app.command()
def capabilities(api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    """Show which capabilities are configured, unconfigured, or unsupported."""
    _run(lambda: ApiClient(api_url).capabilities(), as_json=json_, no_color=no_color)


@app.command()
def validate(path: str, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    """Validate a local repository path."""
    _run(lambda: ApiClient(api_url).validate_repository(path), as_json=json_, no_color=no_color)


@change_app.command("create")
def change_create(
    title: str,
    intent: str,
    repository_path: str,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).create_change(title, intent, repository_path),
        as_json=json_,
        no_color=no_color,
    )


@change_app.command("list")
def change_list(
    limit: int = 100,
    offset: int = 0,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).list_changes(limit=limit, offset=offset),
        as_json=json_,
        no_color=no_color,
    )


@change_app.command("show")
def change_show(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).get_change(change_id), as_json=json_, no_color=no_color)


@actor_app.command("create")
def actor_create(
    kind: str, display_name: str, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption
) -> None:
    _run(lambda: ApiClient(api_url).create_actor(kind, display_name), as_json=json_, no_color=no_color)


@actor_app.command("show")
def actor_show(actor_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).get_actor(actor_id), as_json=json_, no_color=no_color)


@delegation_app.command("create")
def delegation_create(
    grantor_id: UUID,
    grantee_id: UUID,
    change_id: UUID,
    scope: list[str] = typer.Option(..., "--scope"),
    ttl_seconds: int = 3600,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).create_delegation(
            grantor_id=grantor_id,
            grantee_id=grantee_id,
            change_id=change_id,
            scopes=scope,
            ttl_seconds=ttl_seconds,
        ),
        as_json=json_,
        no_color=no_color,
    )


@delegation_app.command("revoke")
def delegation_revoke(delegation_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).revoke_delegation(delegation_id), as_json=json_, no_color=no_color)


@delegation_app.command("list")
def delegation_list(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).list_delegations(change_id), as_json=json_, no_color=no_color)


@github_app.command("connect")
def github_connect(token: str, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).github_connect(token), as_json=json_, no_color=no_color)


@github_app.command("disconnect")
def github_disconnect(api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).github_disconnect(), as_json=json_, no_color=no_color)


@github_app.command("status")
def github_status(api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).github_status(), as_json=json_, no_color=no_color)


@github_app.command("grant")
def github_grant(
    change_id: UUID,
    actor_id: UUID,
    scope: list[str] = typer.Option(..., "--scope"),
    ttl_seconds: int = 900,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).issue_github_grant(
            change_id, actor_id=actor_id, scopes=scope, ttl_seconds=ttl_seconds
        ),
        as_json=json_,
        no_color=no_color,
    )


@github_app.command("pr")
def github_pr(
    change_id: UUID,
    actor_id: UUID,
    grant_id: UUID,
    base_branch: str,
    head_branch: str,
    title: str,
    idempotency_key: str,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).create_pull_request(
            change_id,
            actor_id=actor_id,
            grant_id=grant_id,
            base_branch=base_branch,
            head_branch=head_branch,
            title=title,
            idempotency_key=idempotency_key,
        ),
        as_json=json_,
        no_color=no_color,
    )


@outcome_app.command("refresh")
def outcome_refresh(
    change_id: UUID,
    grant_id: UUID,
    check: list[str] = typer.Option([], "--check"),
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).refresh_outcomes(change_id, grant_id=grant_id, required_check_names=check),
        as_json=json_,
        no_color=no_color,
    )


@outcome_app.command("list")
def outcome_list(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).list_outcomes(change_id), as_json=json_, no_color=no_color)


@recovery_app.command("preview")
def recovery_preview(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).preview_recovery(change_id), as_json=json_, no_color=no_color)


@recovery_app.command("execute")
def recovery_execute(
    change_id: UUID,
    plan_id: UUID,
    actor_id: UUID,
    approval_token: str,
    api_url: str = ApiUrlOption,
    json_: bool = JsonOption,
    no_color: bool = NoColorOption,
) -> None:
    _run(
        lambda: ApiClient(api_url).execute_recovery(
            change_id, plan_id, actor_id=actor_id, approval_token=approval_token
        ),
        as_json=json_,
        no_color=no_color,
    )


@recovery_app.command("show")
def recovery_show(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).get_latest_recovery(change_id), as_json=json_, no_color=no_color)


@passport_app.command("build")
def passport_build(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).build_passport(change_id), as_json=json_, no_color=no_color)


@passport_app.command("show")
def passport_show(change_id: UUID, api_url: str = ApiUrlOption, json_: bool = JsonOption, no_color: bool = NoColorOption) -> None:
    _run(lambda: ApiClient(api_url).get_latest_passport(change_id), as_json=json_, no_color=no_color)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
