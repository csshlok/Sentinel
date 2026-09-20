import { useQuery } from "@tanstack/react-query";
import { Wrench } from "lucide-react";
import { ErrorState } from "@/components/ErrorState";
import { Link } from "@tanstack/react-router";
import { useActors } from "@/features/authority/useActors";
import { TrustDecision } from "./ToolDetailPage";
import { DataTable, EmptyState, PageHeader, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { formatRelative, formatTime, signatureInfo, trustInfo } from "@/lib/status";
import { cn } from "@/lib/utils";
import { toolListQuery } from "@/services/tools";

export function ToolsPage() {
  const { actors } = useActors();
  const tools = useQuery(toolListQuery());
  const items = tools.data?.items ?? [];
  return (
    <>
      <PageHeader title="Tools" description="Top-level executables the runtime has seen, with their signature and trust state." />
      {tools.isPending ? (
        <Section flush>
          <Skeleton lines={4} label="Loading tools" />
        </Section>
      ) : tools.isError ? (
        <ErrorState error={tools.error} onRetry={() => tools.refetch()} />
      ) : items.length === 0 ? (
        <Section>
          <EmptyState icon={<Wrench className="size-6" strokeWidth={1.5} aria-hidden="true" />} title="No tools seen yet">
            Tools appear here after an agent is launched or attached through the runtime.
          </EmptyState>
        </Section>
      ) : (
        <Section flush>
          <DataTable label="Tools">
            <thead>
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Version</th>
                <th className={th}>Publisher</th>
                <th className={th}>Signature</th>
                <th className={th}>Trust</th>
                <th className={th}>Digest</th>
                <th className={th}>Last seen</th>
                <th className={th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((tool) => (
                <tr key={tool.id}>
                  <td className={cn(td, "break-words font-medium text-[var(--text-primary)]")}><Link to="/tools/$toolId" params={{ toolId: tool.id }} className="underline-offset-2 hover:underline">{tool.name}</Link></td>
                  <td className={cn(td, "tabular-nums")}>{tool.version}</td>
                  <td className={td}>{tool.publisher ?? "—"}</td>
                  <td className={td}><StatusLabel status={signatureInfo(tool.signature_state)} /></td>
                  <td className={td}><StatusLabel status={trustInfo(tool.trust_state)} /></td>
                  <td className={cn(td, "mono")} title={tool.artifact_digest}>{tool.artifact_digest.slice(0, 12)}</td>
                  <td className={td} title={formatTime(tool.last_seen_at)}>{formatRelative(tool.last_seen_at)}</td>
                  <td className={td}><TrustDecision tool={tool} actors={actors} label="Decide" /></td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Section>
      )}
      <p className="text-xs leading-5 text-muted-foreground">
        Trust applies to the executable the runtime launches or attaches. Tool and MCP calls made inside an agent aren't intercepted.
        Open a tool to see its full manifest.
      </p>
    </>
  );
}
