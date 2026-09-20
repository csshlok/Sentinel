import { useState } from "react";
import { Field, Select } from "@/components/FormDialog";
import { Input } from "@/components/ui/input";
import { actorLabel, type KnownActor } from "@/lib/known";
import { formatRelative, shortSha } from "@/lib/status";
import type { GitCheckpoint } from "@/lib/api/types";

/**
 * Picks an actor. When none are known yet, falls back to a plain id field so the form is never blocked; the backend validates the id.
 */
export function ActorPicker({ id, label = "Acting actor", actors, value, onChange, error, hint }: { id: string; label?: string; actors: KnownActor[]; value: string; onChange: (v: string) => void; error?: string | null; hint?: string }) {
  if (actors.length === 0) {
    return (
      <Field id={id} label={label} error={error} hint={hint ?? "No actors known yet. Create one under Authority, or paste an actor id."}>
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" aria-describedby={`${id}-h`} className="mono text-[13px]" />
      </Field>
    );
  }
  return <ActorSelect id={id} label={label} actors={actors} value={value} onChange={onChange} error={error} hint={hint} />;
}

export function CheckpointPicker({ id, label, checkpoints, value, onChange, error }: { id: string; label: string; checkpoints: GitCheckpoint[]; value: string; onChange: (v: string) => void; error?: string | null }) {
  return (
    <Field id={id} label={label} error={error} hint={checkpoints.length === 0 ? "No checkpoints yet. Capture evidence first." : undefined}>
      <Select id={id} value={value} onChange={onChange} disabled={checkpoints.length === 0} aria-describedby={`${id}-h`}>
        <option value="">Select a checkpoint…</option>
        {checkpoints.map((c) => (
          <option key={c.id} value={c.id}>{`${c.name} · ${shortSha(c.head_sha)} · ${formatRelative(c.captured_at)}`}</option>
        ))}
      </Select>
    </Field>
  );
}

const FILTER_AT = 8;

/** A native select, with a filter box above it once there are enough actors that scrolling for one is slow. The chosen actor always stays listed. */
function ActorSelect({ id, label, actors, value, onChange, error, hint }: { id: string; label: string; actors: KnownActor[]; value: string; onChange: (v: string) => void; error?: string | null; hint?: string }) {
  const [needle, setNeedle] = useState("");
  const q = needle.trim().toLowerCase();
  const shown = q ? actors.filter((a) => a.id === value || `${a.display_name} ${a.kind} ${a.id}`.toLowerCase().includes(q)) : actors;
  return (
    <Field id={id} label={label} error={error} hint={hint ?? (q ? `${shown.length} of ${actors.length} match` : undefined)}>
      {actors.length > FILTER_AT ? (
        <Input aria-label={`Filter ${label.toLowerCase()}`} placeholder="Filter by name" value={needle} onChange={(e) => setNeedle(e.target.value)} autoComplete="off" className="mb-1.5" />
      ) : null}
      <Select id={id} value={value} onChange={onChange} aria-describedby={`${id}-h`}>
        <option value="">Select an actor…</option>
        {shown.map((a) => (
          <option key={a.id} value={a.id}>{actorLabel(a)}</option>
        ))}
      </Select>
    </Field>
  );
}
