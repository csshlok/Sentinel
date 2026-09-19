"""Checkpoint-fork tree ("TVA branches" view) and fork creation (Part B, AC-7).

Renders a Change's fork lineage as a branching tree -- one node per Change,
children are Changes forked from that Change -- deliberately evoking the
"branched timeline" visual the operator asked for, in the only honest form a
terminal UI can offer: a real tree of real Changes and real checkpoints, no
animation or fabricated in-between state. A forked Change is not a Git branch
(no repository mutation happened); this screen never implies otherwise.

The tree is bounded (depth and node count) so a pathological fork chain
cannot make this screen hang or render something unusable -- exceeding the
bound is shown as an explicit truncation notice, never silently dropped.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static, Tree
from textual.widgets.tree import TreeNode

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

MAX_TREE_DEPTH = 4
MAX_TREE_NODES = 60
MAX_ANCESTOR_HOPS = 10

_STATE_SYMBOLS = {
    "DRAFT": ("o", "white"),
    "ACTIVE": ("*", "cyan"),
    "BLOCKED": ("#", "red"),
    "FAILED": ("x", "red"),
    "CANCELLED": ("x", "grey50"),
    "STABLE": ("*", "green"),
    "REVIEW_READY": ("*", "yellow"),
}


def _state_label(state: str) -> str:
    symbol, color = _STATE_SYMBOLS.get(state, ("o", "white"))
    return f"[{color}]{symbol} {state}[/{color}]"


def _node_label(change: dict[str, Any], *, is_current: bool) -> str:
    marker = "[bold yellow]>> HERE >>[/bold yellow] " if is_current else ""
    title = change.get("title", "(untitled)")
    state = _state_label(change.get("lifecycle_state", "DRAFT"))
    short_id = str(change.get("id", ""))[:8]
    return f"{marker}{title}  {state}  [dim]{short_id}[/dim]"


class BranchScreen(Screen):
    """A branching tree of a Change's forks, plus checkpoint-fork creation."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str, actor_id: str | None = None) -> None:
        super().__init__()
        self.change_id = change_id
        self.actor_id = actor_id
        self.client = ApiClient(api_url)
        self._checkpoint_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading fork tree...", id="status"),
            Tree("Branches", id="branch_tree"),
            Static("[bold]Checkpoints (fork from a selected one)[/bold]"),
            DataTable(id="checkpoints"),
            Horizontal(
                Input(placeholder="New fork title", id="fork_title"),
                Input(placeholder="New fork intent", id="fork_intent"),
                Button("Fork Selected Checkpoint", id="fork"),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#checkpoints", DataTable)
        table.add_columns("Name", "Branch", "Head SHA", "Captured")
        tree = self.query_one("#branch_tree", Tree)
        tree.show_root = False
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    # -- data loading ---------------------------------------------------

    def _load(self) -> None:
        status = self.query_one("#status", Static)
        try:
            current = self.client.get_change(self.change_id)
            checkpoints = self.client.list_git_checkpoints(self.change_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return

        root_change, truncated_up = self._find_root(current)
        root_id = root_change["id"]
        nodes, edges, truncated_down = self._collect_tree(root_id, root_change)
        self.app.call_from_thread(self._render_tree, nodes, edges, root_id, truncated_up, truncated_down)

        items = checkpoints.get("items", [])
        self._checkpoint_ids = [item["id"] for item in items]
        self.app.call_from_thread(self._render_checkpoints, items)
        self.app.call_from_thread(status.update, f"{len(nodes)} Change(s) in this branch tree")

    def _find_root(self, current: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Walk forked_from_change_id upward to the ultimate ancestor."""

        change = current
        hops = 0
        while change.get("forked_from_change_id") and hops < MAX_ANCESTOR_HOPS:
            try:
                change = self.client.get_change(change["forked_from_change_id"])
            except (ApiConnectionError, ApiError):
                break
            hops += 1
        truncated = hops >= MAX_ANCESTOR_HOPS and bool(change.get("forked_from_change_id"))
        return change, truncated

    def _collect_tree(
        self, root_id: str, root_change: dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], bool]:
        """Bounded breadth/depth walk of the fork tree rooted at ``root_id``."""

        nodes: dict[str, dict[str, Any]] = {root_id: root_change}
        edges: dict[str, list[str]] = {}
        frontier = [(root_id, 0)]
        truncated = False
        while frontier:
            node_id, depth = frontier.pop(0)
            if len(nodes) >= MAX_TREE_NODES:
                truncated = True
                break
            if depth >= MAX_TREE_DEPTH:
                if self._has_forks(node_id):
                    truncated = True
                continue
            try:
                forks = self.client.list_change_forks(node_id).get("items", [])
            except (ApiConnectionError, ApiError):
                continue
            children: list[str] = []
            for fork in forks:
                if len(nodes) >= MAX_TREE_NODES:
                    truncated = True
                    break
                nodes[fork["id"]] = fork
                children.append(fork["id"])
                frontier.append((fork["id"], depth + 1))
            if children:
                edges[node_id] = children
        return nodes, edges, truncated

    def _has_forks(self, change_id: str) -> bool:
        try:
            return self.client.list_change_forks(change_id).get("count", 0) > 0
        except (ApiConnectionError, ApiError):
            return False

    # -- rendering (must run on the Textual thread) ----------------------

    def _render_tree(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: dict[str, list[str]],
        root_id: str,
        truncated_up: bool,
        truncated_down: bool,
    ) -> None:
        tree = self.query_one("#branch_tree", Tree)
        tree.clear()
        if not nodes:
            tree.root.add_leaf("[red]Could not load this Change's fork tree.[/red]")
            return
        if truncated_up:
            tree.root.add_leaf(
                "[yellow]! Ancestor chain exceeds this view's depth; showing from a nearer "
                "ancestor, not the true root.[/yellow]"
            )
        label = _node_label(nodes[root_id], is_current=(root_id == self.change_id))
        root_node = tree.root.add(label, expand=True)
        self._add_children(root_node, root_id, nodes, edges)
        if truncated_down:
            tree.root.add_leaf(
                "[yellow]! Some deeper or wider forks are not shown (tree view is bounded).[/yellow]"
            )
        if len(nodes) == 1:
            root_node.add_leaf("[dim]No forks yet. Select a checkpoint below to create one.[/dim]")

    def _add_children(
        self,
        parent_node: TreeNode,
        node_id: str,
        nodes: dict[str, dict[str, Any]],
        edges: dict[str, list[str]],
    ) -> None:
        for child_id in edges.get(node_id, []):
            label = _node_label(nodes[child_id], is_current=(child_id == self.change_id))
            child_node = parent_node.add(label, expand=True)
            self._add_children(child_node, child_id, nodes, edges)

    def _render_checkpoints(self, items: list[dict[str, Any]]) -> None:
        table = self.query_one("#checkpoints", DataTable)
        table.clear()
        for item in items:
            table.add_row(
                item.get("name", ""), item.get("branch") or "-",
                (item.get("head_sha") or "")[:12], item.get("captured_at", ""),
            )

    # -- forking ----------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fork":
            self._fork_selected()

    def _fork_selected(self) -> None:
        status = self.query_one("#status", Static)
        if not self.actor_id:
            status.update("[yellow]No actor id configured; launch with --actor-id to fork.[/yellow]")
            return
        table = self.query_one("#checkpoints", DataTable)
        if not self._checkpoint_ids or table.cursor_row is None:
            status.update("[yellow]Select a checkpoint first.[/yellow]")
            return
        try:
            checkpoint_id = self._checkpoint_ids[table.cursor_row]
        except IndexError:
            return
        title = self.query_one("#fork_title", Input).value.strip()
        intent = self.query_one("#fork_intent", Input).value.strip()
        if not title or not intent:
            status.update("[yellow]A fork title and intent are both required.[/yellow]")
            return
        self.run_worker(
            lambda: self._submit_fork(checkpoint_id, title, intent), thread=True, exclusive=True
        )

    def _submit_fork(self, checkpoint_id: str, title: str, intent: str) -> None:
        status = self.query_one("#status", Static)
        try:
            self.client.fork_change(
                self.change_id, actor_id=self.actor_id, checkpoint_id=checkpoint_id,
                title=title, intent=intent,
            )
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self._load()
