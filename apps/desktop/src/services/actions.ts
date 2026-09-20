import { queryOptions } from "@tanstack/react-query";
import { http, newIdempotencyKey, transport } from "@/lib/api";
import type {
  Actor,
  ActorKind,
  ActorListResponse,
  AgentAdapterListResponse,
  AgentRun,
  AgentRunListResponse,
  AssuranceEvaluation,
  AssuranceFacts,
  AssurancePlan,
  AssuranceRunListResponse,
  ChainVerificationResult,
  ChangeContract,
  ChangeLifecycleState,
  ChangeListResponse,
  ChangePassport,
  ChangeView,
  CredentialGrant,
  Delegation,
  DelegationListResponse,
  DependencyReport,
  EnvironmentView,
  EvidenceSnapshot,
  GitCheckpointComparison,
  GitCheckpointListResponse,
  OutcomeListResponse,
  ProviderConnectionStatus,
  ProviderOperation,
  RecoveryPlan,
  ReplayTimeline,
  SignedPassportExport,
  ToolManifest,
  ToolManifestListResponse,
  ToolTrustDecision,
  ToolTrustScope,
} from "@/lib/api/types";
import { changeKeys } from "./changes";

const base = (id: string) => `/api/v1/changes/${encodeURIComponent(id)}`;
const seg = encodeURIComponent;
const idem = (key?: string) => ({ idempotencyKey: key ?? newIdempotencyKey() });

// --- mutations on a Change (each returns the updated ChangeView) -----------------------------------------------------
export const refreshChange = (id: string) => http.post<ChangeView>(`${base(id)}/refresh`, undefined, idem());

export const transitionChange = (id: string, body: { expected_revision: number; target_state: ChangeLifecycleState; reason: string | null }, key?: string) =>
  http.post<ChangeView>(`${base(id)}/transition`, body, idem(key));

export const cancelChange = (id: string, body: { expected_revision: number; reason: string | null }) =>
  http.post<ChangeView>(`${base(id)}/cancel`, body, idem());

export const verifyChange = (id: string, body: { executable: string; args: string[]; timeout_seconds?: number }) =>
  http.post<ChangeView>(`${base(id)}/verify`, body, idem());

export const updateContract = (id: string, body: { contract: ChangeContract; expected_revision: number }) =>
  http.put<ChangeView>(`${base(id)}/contract`, body);

export const captureEvidence = (id: string, kind: "baseline" | "current") =>
  http.post<EvidenceSnapshot>(`${base(id)}/evidence/${kind}`, undefined, idem());

export const buildPassport = (id: string) => http.post<ChangePassport>(`${base(id)}/passport`, undefined, idem());
export const exportSignedPassport = (id: string) => http.post<SignedPassportExport>(`${base(id)}/passport/export`, undefined, idem());

export const forkChange = (id: string, body: { actor_id: string; fork: { checkpoint_id: string; title: string; intent: string } }, key?: string) =>
  http.post<ChangeView>(`${base(id)}/fork`, body, idem(key));

// --- authority --------------------------------------------------------------------------------------------------------
export const createActor = (body: { display_name: string; kind: ActorKind; provenance?: Record<string, unknown> }, key?: string) =>
  http.post<Actor>("/api/v1/actors", body, idem(key));
export const ACTOR_PAGE = 100;
/** Every actor the backend knows, first page (the API caps a page at 100). `total` says whether more exist. */
export const actorListQuery = () =>
  queryOptions({
    queryKey: ["actors", "list"] as const,
    queryFn: ({ signal }) => http.get<ActorListResponse>("/api/v1/actors", { query: { limit: ACTOR_PAGE, offset: 0 }, signal }),
    retry: false,
    staleTime: 10_000,
  });
export const actorQuery = (id: string) =>
  queryOptions({ queryKey: ["actors", id] as const, queryFn: ({ signal }) => http.get<Actor>(`/api/v1/actors/${seg(id)}`, { signal }), staleTime: 60_000 });
export const createDelegation = (body: { change_id: string; grantor_id: string; grantee_id: string; scopes: string[]; ttl_seconds: number; use_limit?: number | null }, key?: string) =>
  http.post<Delegation>("/api/v1/delegations", body, idem(key));
export const revokeDelegation = (id: string) => http.post<Delegation>(`/api/v1/delegations/${seg(id)}/revoke`, undefined, idem());

// --- agents -----------------------------------------------------------------------------------------------------------
export interface LaunchBody { actor_id: string; launch: { adapter: string; executable: string; args: string[]; timeout_seconds?: number }; output_limit_bytes?: number }
export const launchAgent = (id: string, body: LaunchBody, key?: string) => http.post<AgentRun>(`${base(id)}/agents/launch`, body, idem(key));
export interface AttachBody { actor_id: string; attach: { adapter: string; external_run_id: string; declared_started_at?: string | null } }
export const attachAgent = (id: string, body: AttachBody, key?: string) => http.post<AgentRun>(`${base(id)}/agents/attach`, body, idem(key));
export const pauseAgent = (id: string, runId: string, actorId: string) => http.post<AgentRun>(`${base(id)}/agents/${seg(runId)}/pause`, { actor_id: actorId }, idem());
export const resumeAgent = (id: string, runId: string, actorId: string) => http.post<AgentRun>(`${base(id)}/agents/${seg(runId)}/resume`, { actor_id: actorId }, idem());
export const stopAgent = (id: string, runId: string, actorId: string) => http.post<AgentRun>(`${base(id)}/agents/${seg(runId)}/stop`, { actor_id: actorId }, idem());

// --- assurance --------------------------------------------------------------------------------------------------------
export const createAssurancePlan = (id: string) => http.post<AssurancePlan>(`${base(id)}/assurance/plan`, undefined, idem());
export const runAssurancePlan = (id: string, planId: string, body: { actor_id: string; output_limit_bytes?: number }, key?: string) =>
  http.post<AssuranceRunListResponse>(`${base(id)}/assurance/${seg(planId)}/run`, body, idem(key));

// --- delivery ---------------------------------------------------------------------------------------------------------
export const connectGithub = (token: string) => http.post<ProviderConnectionStatus>("/api/v1/providers/github/connect", { token }, idem());
export const disconnectGithub = () => http.post<ProviderConnectionStatus>("/api/v1/providers/github/disconnect", undefined, idem());
export const createGrant = (id: string, body: { actor_id: string; scopes: string[]; ttl_seconds?: number }, key?: string) =>
  http.post<CredentialGrant>(`${base(id)}/providers/github/grants`, body, idem(key));
export const revokeGrant = (id: string, grantId: string) => http.post<CredentialGrant>(`${base(id)}/providers/github/grants/${seg(grantId)}/revoke`, undefined, idem());
export const refreshOutcomes = (id: string, body: { actor_id: string; grant_id: string; required_check_names?: string[] }) =>
  http.post<OutcomeListResponse>(`${base(id)}/outcomes/refresh`, body, idem());
export interface PullBody { actor_id: string; grant_id: string; base_branch: string; head_branch: string; title: string; idempotency_key: string }
export const createPull = (id: string, body: PullBody) => http.post<ProviderOperation>(`${base(id)}/providers/github/pulls`, body, idem(body.idempotency_key));
export const closePull = (id: string, body: { actor_id: string; grant_id: string; idempotency_key: string }) =>
  http.post<ProviderOperation>(`${base(id)}/providers/github/pulls/close`, body, idem(body.idempotency_key));

// --- recovery ---------------------------------------------------------------------------------------------------------
export const previewRecovery = (id: string) => http.post<RecoveryPlan>(`${base(id)}/recovery/preview`, undefined, idem());
export const executeRecovery = (id: string, planId: string, body: { actor_id: string; approval_token: string }, key?: string) =>
  http.post<RecoveryPlan>(`${base(id)}/recovery/${seg(planId)}/execute`, body, idem(key));

// --- tools ------------------------------------------------------------------------------------------------------------
export const trustTool = (toolId: string, body: { actor_id: string; decision: "APPROVE" | "DENY"; scope: ToolTrustScope; reason?: string | null; change_id?: string | null }, key?: string) =>
  http.post<ToolTrustDecision>(`/api/v1/tools/${seg(toolId)}/trust`, body, idem(key));
export const declareTool = (id: string, manifestPath: string) => http.post<ToolManifest>(`${base(id)}/tools/declare`, { manifest_path: manifestPath }, idem());

export const deleteChange = (id: string) => transport.request<void>({ method: "DELETE", path: base(id) });

// --- read surfaces ----------------------------------------------------------------------------------------------------
const read = <T>(id: string, name: string, path: string, opts: { refetchInterval?: number | false | ((q: { state: { data: T | undefined } }) => number | false) } = {}) =>
  queryOptions({
    queryKey: [...changeKeys.all, name, id] as const,
    queryFn: ({ signal }) => http.get<T>(`${base(id)}${path}`, { signal }),
    ...(opts.refetchInterval !== undefined ? { refetchInterval: opts.refetchInterval as never } : {}),
  });

export const passportQuery = (id: string) => read<ChangePassport>(id, "passport", "/passport");
/** Runs that are still nonterminal are re-read every few seconds, and only then. */
const ACTIVE_RUN = new Set(["RUNNING", "PAUSED", "ATTACHED"]);
export const agentsQuery = (id: string) =>
  read<AgentRunListResponse>(id, "agents", "/agents", {
    refetchInterval: (q) => ((q.state.data?.items ?? []).some((r) => r.status === "RUNNING") ? 3_000 : false),
  });
export const isActiveRun = (r: Pick<AgentRun, "status">) => ACTIVE_RUN.has(r.status);
export const outcomesQuery = (id: string) => read<OutcomeListResponse>(id, "outcomes", "/outcomes");
export const delegationsQuery = (id: string) => read<DelegationListResponse>(id, "delegations", "/delegations");
export const recoveryQuery = (id: string) => read<RecoveryPlan>(id, "recovery", "/recovery");
export const assuranceFactsQuery = (id: string) => read<AssuranceFacts>(id, "assurance-facts", "/assurance/facts");
export const assurancePlanQuery = (id: string) => read<AssurancePlan>(id, "assurance-plan", "/assurance/plan");
export const assuranceEvaluationQuery = (id: string, planId: string) =>
  queryOptions({
    queryKey: [...changeKeys.all, "assurance-evaluation", id, planId] as const,
    queryFn: ({ signal }) => http.get<AssuranceEvaluation>(`${base(id)}/assurance/${seg(planId)}/evaluation`, { signal }),
    enabled: Boolean(planId),
  });
export const replayVerifyQuery = (id: string) => read<ChainVerificationResult>(id, "replay-verify", "/replay/verify");
export const replayQuery = (id: string) => read<ReplayTimeline>(id, "replay", "/replay");
export const environmentQuery = (id: string) => read<EnvironmentView>(id, "environment", "/environment");
export const dependenciesQuery = (id: string) => read<DependencyReport>(id, "dependencies", "/dependencies");
export const checkpointsQuery = (id: string) => read<GitCheckpointListResponse>(id, "checkpoints", "/git/checkpoints");
export const changeToolsQuery = (id: string) => read<ToolManifestListResponse>(id, "change-tools", "/tools");
export const forksQuery = (id: string) => read<ChangeListResponse>(id, "forks", "/forks");
export const comparisonQuery = (id: string, baselineId: string, currentId: string) =>
  queryOptions({
    queryKey: [...changeKeys.all, "compare", id, baselineId, currentId] as const,
    queryFn: ({ signal }) => http.get<GitCheckpointComparison>(`${base(id)}/git/compare`, { query: { baseline_id: baselineId, current_id: currentId }, signal }),
    enabled: Boolean(baselineId && currentId),
  });
export const adaptersQuery = () =>
  queryOptions({ queryKey: ["agents", "adapters"] as const, queryFn: ({ signal }) => http.get<AgentAdapterListResponse>("/api/v1/agents/adapters", { signal }), staleTime: 60_000 });
export const githubStatusQuery = () =>
  queryOptions({ queryKey: ["providers", "github", "status"] as const, queryFn: ({ signal }) => http.get<ProviderConnectionStatus>("/api/v1/providers/github/status", { signal }) });
