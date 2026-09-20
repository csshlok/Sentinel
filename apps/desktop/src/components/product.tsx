import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { StatusInfo, Tone } from "@/lib/status";

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-[var(--status-muted)]",
};

/** A quiet dot + text label. The text always carries the meaning; colour only reinforces it. */
export function StatusLabel({ status, className }: { status: StatusInfo; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center gap-1.5 whitespace-nowrap rounded-full bg-[var(--status-muted-bg)] px-2 text-xs text-foreground",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", DOT[status.tone])} aria-hidden="true" />
      {status.label}
    </span>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="break-words text-2xl font-semibold leading-tight tracking-[-0.01em] text-[var(--text-primary)]">
          {title}
        </h1>
        {description ? <div className="mt-1 max-w-[70ch] text-sm leading-5 text-muted-foreground">{description}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** A flat, bordered panel with an optional header row. */
export function Section({
  title,
  description,
  action,
  children,
  flush = false,
  className,
}: {
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  /** Remove body padding, for tables and lists that run edge to edge. */
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0 overflow-hidden rounded-lg border bg-card", className)}>
      {title ? (
        <header className="flex min-h-[3.25rem] items-center justify-between gap-4 border-b px-5 py-2.5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold leading-snug text-[var(--text-primary)]">{title}</h2>
            {description ? <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">{description}</p> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </header>
      ) : null}
      <div className={flush ? "" : "px-5 py-4"}>{children}</div>
    </section>
  );
}

const NOTICE: Record<"info" | "warn" | "danger", string> = {
  info: "bg-[var(--status-info-bg)] text-[var(--text-body)]",
  warn: "bg-[var(--status-warn-bg)] text-[var(--status-warn-ink)]",
  danger: "bg-[var(--status-error-bg)] text-[var(--text-body)]",
};

export function Notice({
  tone = "info",
  title,
  children,
  role,
  action,
}: {
  tone?: "info" | "warn" | "danger";
  title: string;
  children?: ReactNode;
  role?: "alert" | "status";
  action?: ReactNode;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 rounded-lg px-4 py-3 text-sm", NOTICE[tone])} role={role}>
      <div className="min-w-0">
        <p className="font-medium text-[var(--text-primary)]">{title}</p>
        {children ? <div className="mt-0.5 leading-5">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-5 py-12 text-center">
      {icon ? <div className="mb-3 text-muted-foreground">{icon}</div> : null}
      <h2 className="text-base font-semibold text-[var(--text-primary)]">{title}</h2>
      {children ? <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{children}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div className="space-y-3 p-5" role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="h-3 animate-pulse rounded bg-secondary"
          style={{ width: `${Math.max(42, 100 - i * 13)}%` }}
        />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

/** Definition list used for facts. Values wrap; long paths and hashes never overflow. */
export function Facts({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(96px,max-content)_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
      {items.map(({ label, value }) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="break-words text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PathText({ path, className }: { path: string; className?: string }) {
  return <code className={cn("break-all text-[13px] text-muted-foreground", className)}>{path}</code>;
}

export function Chips({ items, empty }: { items: string[] | undefined; empty: string }) {
  if (!items || items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item} className="mono break-all rounded border bg-secondary px-2 py-0.5 text-xs">
          {item}
        </li>
      ))}
    </ul>
  );
}

/** Table shell: horizontal scroll on narrow widths, hairline rows, quiet header. */
export function DataTable({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm" aria-label={label}>
        {children}
      </table>
    </div>
  );
}
export const th = "whitespace-nowrap px-4 py-2.5 text-xs font-medium text-muted-foreground first:pl-5 last:pr-5";
export const td = "border-t px-4 py-2.5 align-top first:pl-5 last:pr-5";
