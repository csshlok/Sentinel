import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, useDialogState, useFormAction } from "@/components/FormDialog";
import { CheckpointPicker } from "@/components/pickers";
import { DataTable, Facts, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { DiffCoverageResult, PolicyPresetEvaluation } from "@/lib/api/types";
import { checkBoundaryStatus } from "@/lib/boundary";
import { formatRelative, formatTime } from "@/lib/status";
import { checkpointsQuery, checkRunsQuery, presetQuery, runDiffCoverage } from "@/services/actions";
import { changeKeys } from "@/services/changes";

const unavailable = (e: unknown) => e instanceof ApiError && (e.kind === "not_found" || e.code === "CAPABILITY_UNAVAILABLE");

/** Every check run of the Change and the boundary it was observed to run under (never inferred from configuration). */
export function CheckRunsPanel({ changeId }: { changeId: string }) {
  const q = useQuery(checkRunsQuery(changeId));
  if (q.isPending) return <Section title="Check runs" flush><Skeleton lines={2} label="Loading check runs" /></Section>;
  if (q.isError) {
    if (unavailable(q.error)) return <Section title="Check runs"><p className="text-sm text-muted-foreground">This backend does not report check runs.</p></Section>;
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  }
  const items = q.data.items ?? [];
  const unconfined = items.filter((r) => r.boundary === "UNCONFINED").length;
  return (
    <Section title="Check runs" description="Where each check actually ran. A confined run executed in its own AppContainer on a copy of the committed tree.">
      {unconfined ? <Notice tone="warn" title={`${unconfined} check run${unconfined === 1 ? "" : "s"} ran unconfined`}>An unconfined run used the explicit opt-in. It ran with your full user authority, and the Passport's confined-checks claim is FAIL for this Change.</Notice> : null}
      {items.length === 0 ? <p className="text-sm text-muted-foreground" data-testid="check-runs-empty">No check has run for this Change yet.</p> : (
        <DataTable label="Check runs">
          <thead><tr><th className={th}>Boundary</th><th className={th}>State</th><th className={th}>Network</th><th className={th}>Exit</th><th className={th}>When</th></tr></thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className={td}><StatusLabel status={checkBoundaryStatus(r)} />{r.token && !r.token.job_verified ? <span className="ml-2 text-xs text-warn">Job not verified</span> : null}</td>
                <td className={td}>{r.state}{r.timed_out ? " (timed out)" : ""}</td>
                <td className={td}>{r.network == null ? "—" : r.network ? "Allowed" : "Blocked"}</td>
                <td className={`${td} tabular-nums`}>{r.exit_code ?? "—"}</td>
                <td className={td} title={r.created_at ? formatTime(r.created_at) : undefined}>{r.created_at ? formatRelative(r.created_at) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Section>
  );
}

const DECISION = { ALLOW: { label: "Allowed", tone: "ok" }, DENY: { label: "Denied", tone: "danger" } } as const;
const FRESHNESS = { CURRENT: { label: "Current", tone: "ok" }, STALE: { label: "Stale", tone: "warn" }, UNKNOWN: { label: "Unknown", tone: "neutral" } } as const;

/** The required policy preset's decision: it gates REVIEW_READY and apply-back. */
export function PresetPanel({ changeId }: { changeId: string }) {
  const q = useQuery(presetQuery(changeId));
  if (q.isPending) return <Section title="Policy preset" flush><Skeleton lines={2} label="Loading policy preset" /></Section>;
  if (q.isError) {
    if (unavailable(q.error)) return <Section title="Policy preset"><p className="text-sm text-muted-foreground">No policy preset is evaluated for this Change.</p></Section>;
    return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  }
  return <PresetView preset={q.data} />;
}

export function PresetView({ preset }: { preset: PolicyPresetEvaluation }) {
  const decision = DECISION[preset.decision as keyof typeof DECISION] ?? { label: preset.decision, tone: "neutral" as const };
  const fresh = FRESHNESS[preset.freshness as keyof typeof FRESHNESS] ?? { label: preset.freshness, tone: "neutral" as const };
  return (
    <Section
      title="Policy preset"
      description="When a preset is required, a denial blocks Review ready and apply-back."
      action={<StatusLabel status={decision} />}
    >
      <Facts
        items={[
          { label: "Preset", value: preset.preset_name ? `${preset.preset_name}${preset.preset_version ? ` (${preset.preset_version})` : ""}` : "None selected" },
          { label: "Change type", value: preset.change_type ?? "—" },
          { label: "Freshness", value: <StatusLabel status={fresh} /> },
        ]}
      />
      {preset.denials?.length ? <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-danger" data-testid="preset-denials">{preset.denials.map((d) => <li key={d}>{d}</li>)}</ul> : null}
    </Section>
  );
}

/** Runs the diff-coverage collector (inside a confined check box) between two checkpoints and shows its result as reported. */
export function DiffCoveragePanel({ changeId }: { changeId: string }) {
  const checkpoints = useQuery(checkpointsQuery(changeId));
  const [result, setResult] = useState<DiffCoverageResult | null>(null);
  const [baseline, setBaseline] = useState("");
  const [tested, setTested] = useState("");
  const [minimum, setMinimum] = useState("0");
  const [args, setArgs] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({
    run: (_: undefined, key) => runDiffCoverage(changeId, {
      baseline_checkpoint_id: baseline,
      tested_checkpoint_id: tested,
      test_args: args.trim() ? args.trim().split(/\s+/).slice(0, 4) : [],
      rule: { minimum_percent: Number(minimum), required: Number(minimum) > 0 } as never,
    }, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: (r) => { setResult(r); dlg.close(); },
  });
  const list = checkpoints.data?.items ?? [];
  return (
    <Section
      title="Diff coverage"
      description="Did the tests actually execute the changed lines? The tests run in a confined box; the result says what was measured and what is unknown."
      action={<Button size="sm" variant="outline" disabled={list.length < 1} onClick={dlg.show}>Measure diff coverage</Button>}
    >
      {list.length < 1 ? <p className="text-sm text-muted-foreground">Capture a baseline and a current checkpoint first.</p> : null}
      {result ? <DiffCoverageView result={result} /> : null}
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Measure diff coverage"
        description="Runs the Python tests under coverage inside a confined box and maps executed lines onto the diff between the two checkpoints. Long test suites can exceed the desktop's 60-second request limit; use the CLI for those."
        submitLabel="Measure"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!baseline) e.baseline = "Choose the baseline checkpoint.";
          if (!tested) e.tested = "Choose the checkpoint that was tested.";
          const pct = Number(minimum);
          if (!/^\d+(\.\d+)?$/.test(minimum.trim()) || pct > 100) e.minimum = "Use a percentage from 0 to 100.";
          setErrs(e);
          if (!Object.keys(e).length) run.mutate(undefined);
        }}
      >
        <CheckpointPicker id="dc-baseline" label="Baseline checkpoint" checkpoints={list} value={baseline} onChange={setBaseline} error={errs.baseline} />
        <CheckpointPicker id="dc-tested" label="Tested checkpoint" checkpoints={list} value={tested} onChange={setTested} error={errs.tested} />
        <Field id="dc-min" label="Required changed-line coverage (%)" hint="0 records the measurement without making it a required gate." error={errs.minimum}>
          <Input id="dc-min" inputMode="decimal" value={minimum} onChange={(e) => setMinimum(e.target.value)} />
        </Field>
        <Field id="dc-args" label="Extra pytest arguments (optional, up to 4)">
          <Input id="dc-args" value={args} onChange={(e) => setArgs(e.target.value)} placeholder="-q tests/unit" />
        </Field>
      </FormDialog>
    </Section>
  );
}

const EXERCISED: Record<string, { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  PASS: { label: "Changed lines exercised", tone: "ok" },
  FAIL: { label: "Not enough changed lines exercised", tone: "danger" },
  NOT_APPLICABLE: { label: "No executable changed lines", tone: "neutral" },
  STALE: { label: "Stale: measured for an older state", tone: "warn" },
  UNKNOWN: { label: "Unknown", tone: "warn" },
};

export function DiffCoverageView({ result }: { result: DiffCoverageResult }) {
  const status = EXERCISED[result.diff_exercised] ?? { label: result.diff_exercised, tone: "neutral" as const };
  return (
    <div className="space-y-3" data-testid="diff-coverage-result">
      <div className="flex flex-wrap items-center gap-2"><StatusLabel status={status} /><span className="text-xs text-muted-foreground">Freshness: {result.freshness}</span></div>
      <Facts
        items={[
          { label: "Measured", value: result.measured_percent == null ? "—" : `${result.measured_percent.toFixed(1)}%${result.threshold != null ? ` (required ${result.threshold}%)` : ""}` },
          { label: "Changed lines", value: result.changed_executable_lines == null ? "—" : `${result.executed_changed_lines ?? 0} of ${result.changed_executable_lines} executed` },
          { label: "Checks passed", value: result.checks_passed == null ? "Unknown" : result.checks_passed ? "Yes" : "No" },
          { label: "Collected", value: result.boundary ?? result.collection_boundary },
          { label: "Collector", value: `${result.collector_id}${result.collector_version ? ` ${result.collector_version}` : ""} (${result.collector_status})` },
        ]}
      />
      {result.reasons?.length ? <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{result.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
      <p className="text-xs leading-5 text-muted-foreground">{result.caveat}</p>
    </div>
  );
}
