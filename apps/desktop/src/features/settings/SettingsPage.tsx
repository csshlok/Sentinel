import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CAPABILITY_LINKS } from "@/lib/nav";
import { CAPABILITY_INFO } from "@/lib/capabilityInfo";
import { TerminalCard } from "./TerminalCard";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Facts, PageHeader, Section, Skeleton, StatusLabel } from "@/components/product";
import { GithubConnection } from "@/features/delivery/GithubConnection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { transport } from "@/lib/api";
import { THEME_CHOICES, readThemePreference, setThemePreference, type ThemePreference } from "@/lib/theme";
import { buildDiagnostics } from "@/lib/diagnostics";
import { devToken } from "@/lib/api/browser-transport";
import type { CapabilityState } from "@/lib/api/types";
import type { StatusInfo } from "@/lib/status";
import { capabilitiesQuery, healthQuery, identityQuery, runtimeQuery } from "@/services/system";
import { formatTime } from "@/lib/status";

const CAPABILITY: Record<CapabilityState, StatusInfo> = {
  AVAILABLE: { label: "Available", tone: "ok" },
  UNCONFIGURED: { label: "Not configured", tone: "warn" },
  UNSUPPORTED: { label: "Unsupported", tone: "neutral" },
};

function TokenForm() {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(Boolean(devToken.get()));
  return (
    <form
      className="grid max-w-md gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        devToken.set(value);
        setValue("");
        setSaved(true);
        void queryClient.invalidateQueries();
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor="dev-token">Development API token</Label>
        <Input id="dev-token" type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" aria-describedby="dev-token-hint" />
        <p id="dev-token-hint" className="text-xs text-muted-foreground">
          Browser development only. It's kept in this tab's session storage and cleared when the tab closes. The desktop app never
          puts a token in the page.
        </p>
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!value.trim()}>
          Use token
        </Button>
        {saved ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              devToken.clear();
              setSaved(false);
              void queryClient.invalidateQueries();
            }}
          >
            Clear token
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function Appearance() {
  const [pref, setPref] = useState<ThemePreference>(readThemePreference);
  return (
    <fieldset className="grid gap-2">
      <legend className="sr-only">Theme</legend>
      {THEME_CHOICES.map((c) => (
        <label key={c.value} className="flex items-center gap-2 text-sm">
          <input type="radio" name="theme" checked={pref === c.value} onChange={() => { setPref(c.value); setThemePreference(c.value); }} />
          {c.label}
        </label>
      ))}
    </fieldset>
  );
}

function Diagnostics({ text }: { text: string }) {
  const [note, setNote] = useState<string | null>(null);
  const bridge = window.changeAssuranceDesktop;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">A summary of versions and states you can paste into a bug report. It contains no tokens, no repository paths and no Change data.</p>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              setNote("Copied.");
            } catch {
              setNote("Copying isn't available here. Select the text below and copy it.");
            }
          }}
        >
          Copy diagnostic summary
        </Button>
        {bridge?.diagnostics ? (
          <Button size="sm" variant="outline" onClick={async () => { const r = await bridge.diagnostics.openLogs(); setNote(r.ok ? null : r.error.message); }}>Open logs folder</Button>
        ) : null}
      </div>
      {note ? <p className="text-sm" role="status">{note}</p> : null}
      <pre className="mono max-h-48 overflow-auto whitespace-pre-wrap rounded-md border bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label="Diagnostic summary">{text}</pre>
    </div>
  );
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const health = useQuery(healthQuery());
  const caps = useQuery(capabilitiesQuery());
  const runtime = useQuery(runtimeQuery());
  const identity = useQuery(identityQuery());
  const [restarting, setRestarting] = useState(false);
  const inBrowser = transport.kind === "browser";
  const backend = runtime.data?.backend;

  return (
    <>
      <PageHeader title="Settings" description="Connection to the local service, how you're signed in, and what it reports it can do." />

      <Section
        title="Local service"
        action={
          backend ? (
            <Button
              size="sm"
              variant="outline"
              disabled={restarting}
              onClick={async () => {
                setRestarting(true);
                await window.changeAssuranceDesktop?.runtime.restartBackend();
                await queryClient.invalidateQueries();
                setRestarting(false);
              }}
            >
              {restarting ? "Restarting…" : backend.mode === "managed" ? "Restart" : "Check again"}
            </Button>
          ) : undefined
        }
      >
        <Facts
          items={[
            { label: "Interface", value: inBrowser ? "Browser (development)" : "Desktop app" },
            {
              label: "Status",
              value: health.isPending ? (
                "Checking…"
              ) : health.isError ? (
                <StatusLabel status={{ label: "Not reachable", tone: "danger" }} />
              ) : (
                <StatusLabel status={{ label: `Reachable · API v${health.data.api_version}`, tone: "ok" }} />
              ),
            },
            ...(identity.data
              ? [
                  { label: "Service", value: identity.data.service_name },
                  { label: "Instance", value: <code title="Changes every time the service starts">{identity.data.instance_id.slice(0, 8)}</code> },
                  { label: "Running since", value: formatTime(identity.data.started_at) },
                ]
              : []),
            ...(backend
              ? [
                  { label: "Mode", value: backend.mode === "managed" ? "Managed by this app" : "External (started separately)" },
                  { label: "Address", value: <code>{backend.url || "—"}</code> },
                  ...(backend.detail ? [{ label: "Detail", value: backend.detail }] : []),
                  { label: "Build", value: runtime.data?.packaged ? "Packaged" : "Development" },
                  {
                    label: "Git",
                    value: runtime.data?.git.available ? (
                      <StatusLabel status={{ label: `Found · ${runtime.data.git.version}`, tone: "ok" }} />
                    ) : (
                      <span className="inline-flex flex-wrap items-center gap-2">
                        <StatusLabel status={{ label: "Not found", tone: "warn" }} />
                        <span className="text-muted-foreground">Install Git and make sure it's on your PATH to create Changes.</span>
                      </span>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Section>

      <Section title="Authentication">
        {inBrowser ? (
          <TokenForm />
        ) : (
          <p className="text-sm text-muted-foreground">
            {runtime.data?.hasToken
              ? "The app signs requests to the local service for you. The token never reaches the page."
              : "The app has no token for the local service, so protected screens will be rejected."}
          </p>
        )}
      </Section>

      <Section title="GitHub" description="Needed to create pull requests and read CI outcomes.">
        <GithubConnection />
      </Section>

      <Section title="Appearance"><Appearance /></Section>

      <Section title="Diagnostics">
        <Diagnostics text={buildDiagnostics({ interfaceKind: inBrowser ? "browser" : "desktop", api: health.data?.api_version ?? null, reachable: health.isSuccess, runtime: runtime.data ?? null, capabilities: caps.data?.items ?? [] })} />
      </Section>

      <TerminalCard />

      <Section title="Capabilities" description="What the local service reports. Unavailable is shown separately from failed." flush>
        {caps.isPending ? (
          <Skeleton lines={4} label="Loading capabilities" />
        ) : caps.isError ? (
          <div className="p-4">
            <ErrorState error={caps.error} onRetry={() => caps.refetch()} />
          </div>
        ) : (
          <ul aria-label="Capabilities" className="divide-y">
            {caps.data.items.map((cap) => (
              <li key={cap.id} className="flex items-start justify-between gap-4 px-5 py-3.5">
                <div className="min-w-0">
                  <p className="font-medium text-[var(--text-primary)]">{cap.name}</p>
                  {CAPABILITY_INFO[cap.id] ? (
                    <>
                      <p className="mt-1 text-[13px] leading-5 text-[var(--text-body)]">{CAPABILITY_INFO[cap.id]!.purpose}</p>
                      <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">Works with: {CAPABILITY_INFO[cap.id]!.worksWith}</p>
                    </>
                  ) : null}
                  {cap.state === "AVAILABLE" && CAPABILITY_LINKS[cap.id] ? <p className="mt-0.5 text-[13px] text-muted-foreground">Used in: {CAPABILITY_LINKS[cap.id]!.where}</p> : null}
                  {cap.reason ? <p className="mt-0.5 text-[13px] text-muted-foreground">{cap.reason}</p> : null}
                  {(cap.limitations ?? []).map((limit) => (
                    <p key={limit} className="mt-0.5 text-[13px] text-muted-foreground">
                      {limit}
                    </p>
                  ))}
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <StatusLabel status={CAPABILITY[cap.state]} />
                  {cap.state === "AVAILABLE" && CAPABILITY_LINKS[cap.id] ? (
                    <Link to={CAPABILITY_LINKS[cap.id]!.to} className="text-[13px] underline underline-offset-2 hover:text-foreground">{CAPABILITY_LINKS[cap.id]!.label}</Link>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
