import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { errMessage } from "@/components/FormDialog";
import { Facts, Notice, Section, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { GitHubCheckPublicationResult } from "@/lib/api/types";
import { githubAppFlowQuery, publishGithubCheck, startGithubAppFlow } from "@/services/actions";

/** An https link that Electron opens in the user's browser (the window-open handler allows https only). */
const External = ({ href, children }: { href: string; children: string }) =>
  /^https:\/\//.test(href) ? <a className="underline" href={href} target="_blank" rel="noreferrer">{children}</a> : <code className="break-all">{href}</code>;

/**
 * Publishes the Sentinel GitHub Check on the PR head Sentinel observed. Without an installed Sentinel GitHub App the backend returns
 * GITHUB_APP_NOT_INSTALLED: the user can create their own App (manifest flow, nothing hosted), install it, or decline and publish a
 * lesser commit status instead.
 */
export function GithubCheckPanel({ changeId, disabled }: { changeId: string; disabled: boolean }) {
  const [result, setResult] = useState<GitHubCheckPublicationResult | null>(null);
  const publish = useMutation({ mutationFn: (decline: boolean) => publishGithubCheck(changeId, decline), onSuccess: setResult });
  return (
    <Section
      title="Sentinel GitHub Check"
      description="Publishes the signed claims (boundary, checks, diff exercised, freshness) as a Check on the pull request's head commit."
      action={<Button size="sm" variant="outline" disabled={disabled || publish.isPending} onClick={() => publish.mutate(false)}>{publish.isPending ? "Publishing…" : "Publish Check"}</Button>}
    >
      {disabled ? <p className="text-sm text-muted-foreground">Connect GitHub and open a pull request first.</p> : null}
      {publish.isError ? <Notice tone="danger" title="The Check wasn't published" role="alert">{errMessage(publish.error)}</Notice> : null}
      {result?.state === "PUBLISHED" ? <PublishedView result={result} /> : null}
      {result?.state === "GITHUB_APP_NOT_INSTALLED" ? (
        <NotInstalled result={result} onDecline={() => publish.mutate(true)} pending={publish.isPending} />
      ) : null}
    </Section>
  );
}

export function PublishedView({ result }: { result: GitHubCheckPublicationResult }) {
  const lesser = result.presentation === "COMMIT_STATUS_LESSER";
  return (
    <div className="space-y-3" data-testid="github-check-published">
      {lesser ? <Notice tone="warn" title="Published as a commit status">A commit status is a lesser signal than a Check: any token with status access can set one, so GitHub does not tie it to Sentinel's App.</Notice> : null}
      <Facts
        items={[
          { label: "Pull request", value: result.repository && result.pr_number ? `${result.repository}#${result.pr_number}` : "—" },
          { label: "Head", value: <code>{result.head_sha?.slice(0, 12) ?? "—"}</code> },
          { label: "Boundary", value: result.execution_boundary ?? "UNKNOWN" },
          { label: "Checks passed", value: result.checks_passed == null ? "UNKNOWN" : result.checks_passed ? "Yes" : "No" },
          { label: "Diff exercised", value: result.diff_exercised ?? "UNKNOWN" },
          { label: "Freshness", value: result.signed_freshness ?? result.freshness ?? "UNKNOWN" },
          ...(result.signer_fingerprint ? [{ label: "Signer", value: <code className="break-all">{result.signer_fingerprint}</code> }] : []),
          ...(result.check_url ? [{ label: "On GitHub", value: <External href={result.check_url}>Open the Check</External> }] : []),
        ]}
      />
    </div>
  );
}

function NotInstalled({ result, onDecline, pending }: { result: GitHubCheckPublicationResult; onDecline: () => void; pending: boolean }) {
  const owner = result.repository?.split("/")[0] ?? "";
  return (
    <div className="space-y-3" data-testid="github-app-not-installed">
      <Notice tone="warn" title="No Sentinel GitHub App is installed for this repository">
        A Check needs your own Sentinel GitHub App. You can create one (it lives in your GitHub account, its key stays on this computer), install
        it, or publish a lesser commit status instead.
      </Notice>
      {result.installation_url ? <p className="text-sm">Already created? <External href={result.installation_url}>Install the App on this repository</External>, then publish again.</p> : null}
      <CreateApp owner={owner} />
      <Button size="sm" variant="ghost" disabled={pending} onClick={onDecline}>Decline and publish a commit status</Button>
    </div>
  );
}

function CreateApp({ owner: initialOwner }: { owner: string }) {
  const [owner, setOwner] = useState(initialOwner);
  const [kind, setKind] = useState<"user" | "organization">("user");
  const start = useMutation({ mutationFn: () => startGithubAppFlow({ owner: owner.trim(), account_kind: kind }) });
  const flow = useQuery(githubAppFlowQuery(start.data?.flow_id ?? ""));
  const view = flow.data ?? start.data;
  return (
    <div className="space-y-2 rounded-md border p-3">
      <h3 className="text-sm font-medium">Create your Sentinel GitHub App</h3>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-[13px]">Owner<Input aria-label="GitHub owner" value={owner} onChange={(e) => setOwner(e.target.value)} className="w-48" /></label>
        <label className="grid gap-1 text-[13px]">Account
          <select aria-label="Account kind" className="h-9 rounded-md border bg-background px-2 text-sm" value={kind} onChange={(e) => setKind(e.target.value as "user" | "organization")}>
            <option value="user">Personal account</option>
            <option value="organization">Organization</option>
          </select>
        </label>
        <Button size="sm" disabled={!owner.trim() || start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Starting…" : "Start"}</Button>
      </div>
      {start.isError ? <Notice tone="danger" title="The App flow didn't start" role="alert">{errMessage(start.error)}</Notice> : null}
      {view ? (
        <div className="space-y-1 text-sm" data-testid="github-app-flow">
          <StatusLabel status={{ label: view.status, tone: view.status === "COMPLETE" ? "ok" : view.status === "PENDING" ? "info" : "danger" }} />
          {view.status === "PENDING" && view.registration_url ? <p><External href={view.registration_url}>Continue on GitHub</External> to create the App; this page updates when GitHub hands it back.</p> : null}
          {view.status === "COMPLETE" ? <p>Created{view.app_slug ? ` ${view.app_slug}` : ""}. Install it on the repository, then publish again.</p> : null}
          {view.reason ? <p className="text-muted-foreground">{view.reason}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
