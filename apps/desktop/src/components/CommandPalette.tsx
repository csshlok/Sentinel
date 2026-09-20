import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Bot, GitBranch, GitPullRequestArrow, House, Plus, Settings, Users, Wrench } from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { repoName } from "@/lib/status";
import { changeListQuery } from "@/services/changes";

/** Ctrl/⌘+K: jump to a page, start a Change, or open any existing Change by title or repository. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  // Only fetch while the palette is open; results come from the same cache the Changes page uses.
  const changes = useQuery({ ...changeListQuery(), enabled: open });

  const run = (action: () => unknown) => () => {
    onOpenChange(false);
    void action();
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Search"
      description="Jump to a page or a Change"
      showCloseButton={false}
      className="top-[20%] translate-y-0 sm:max-w-lg"
    >
      <CommandInput placeholder="Search Changes, or jump to a page…" />
      <CommandList>
        <CommandEmpty>Nothing matches that.</CommandEmpty>
        <CommandGroup heading="Actions">
          <CommandItem value="new change create" onSelect={run(() => navigate({ to: "/changes", search: { new: true } }))}>
            <Plus /> New Change
          </CommandItem>
        </CommandGroup>
        <CommandGroup heading="Go to">
          <CommandItem value="home overview" onSelect={run(() => navigate({ to: "/home" }))}>
            <House /> Home
          </CommandItem>
          <CommandItem value="changes" onSelect={run(() => navigate({ to: "/changes" }))}>
            <GitPullRequestArrow /> Changes
          </CommandItem>
          <CommandItem value="agents runs launch" onSelect={run(() => navigate({ to: "/agents" }))}>
            <Bot /> Agents
          </CommandItem>
          <CommandItem value="actors people authority" onSelect={run(() => navigate({ to: "/actors" }))}>
            <Users /> Actors
          </CommandItem>
          <CommandItem value="github pull requests connection" onSelect={run(() => navigate({ to: "/github" }))}>
            <GitBranch /> GitHub
          </CommandItem>
          <CommandItem value="tools" onSelect={run(() => navigate({ to: "/tools" }))}>
            <Wrench /> Tools
          </CommandItem>
          <CommandItem value="settings runtime authentication capabilities" onSelect={run(() => navigate({ to: "/settings" }))}>
            <Settings /> Settings
          </CommandItem>
        </CommandGroup>
        {changes.data && changes.data.items.length > 0 ? (
          <CommandGroup heading="Changes">
            {changes.data.items.map((change) => (
              <CommandItem
                key={change.id}
                value={`${change.title} ${repoName(change.repository_path)} ${change.id}`}
                onSelect={run(() => navigate({ to: "/changes/$changeId", params: { changeId: change.id } }))}
              >
                <span className="truncate">{change.title}</span>
                <span className="ml-auto truncate pl-3 text-xs text-muted-foreground">{repoName(change.repository_path)}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
      </CommandList>
    </CommandDialog>
  );
}
