import type { Actor, CredentialGrant } from "./api/types";

// The API can create and fetch an actor by id, and returns a credential grant only when it is created; there are no list endpoints for
// either. So the desktop remembers, per install, the actors and grants it created, purely so forms can offer a picker instead of asking
// for a pasted id. Nothing here is authoritative: the backend still validates every id. Grants hold no token material.
const ACTORS_KEY = "ca.known-actors.v1";
const GRANTS_KEY = "ca.known-grants.v1";
const MAX = 200;

type KnownGrant = Pick<CredentialGrant, "id" | "change_id" | "actor_id" | "scopes" | "expires_at"> & { revoked?: boolean };

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // blocked (privacy mode, sandbox): fall back to no memory rather than failing the screen
  }
}

function read<T>(key: string): T[] {
  try {
    const parsed: unknown = JSON.parse(storage()?.getItem(key) ?? "[]");
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function write(key: string, items: unknown[]) {
  try {
    storage()?.setItem(key, JSON.stringify(items.slice(0, MAX)));
  } catch {
    /* quota or blocked: the picker just has fewer suggestions */
  }
}

const isActor = (v: unknown): v is Pick<Actor, "id" | "display_name" | "kind"> =>
  typeof v === "object" && v !== null && typeof (v as Actor).id === "string" && typeof (v as Actor).display_name === "string";

export type KnownActor = Pick<Actor, "id" | "display_name" | "kind">;

export const knownActors = (): KnownActor[] => read<unknown>(ACTORS_KEY).filter(isActor).map(({ id, display_name, kind }) => ({ id, display_name, kind }));

export function rememberActor(actor: KnownActor) {
  write(ACTORS_KEY, [{ id: actor.id, display_name: actor.display_name, kind: actor.kind }, ...knownActors().filter((a) => a.id !== actor.id)]);
}

export const knownGrants = (changeId: string): KnownGrant[] =>
  read<KnownGrant>(GRANTS_KEY).filter((g) => g && typeof g.id === "string" && g.change_id === changeId);

export function rememberGrant(grant: CredentialGrant) {
  const rest = read<KnownGrant>(GRANTS_KEY).filter((g) => g.id !== grant.id);
  write(GRANTS_KEY, [{ id: grant.id, change_id: grant.change_id, actor_id: grant.actor_id, scopes: grant.scopes, expires_at: grant.expires_at, revoked: Boolean(grant.revoked_at) }, ...rest]);
}

export function markGrantRevoked(grantId: string) {
  write(GRANTS_KEY, read<KnownGrant>(GRANTS_KEY).map((g) => (g.id === grantId ? { ...g, revoked: true } : g)));
}

/** Merges actor sources by id; earlier sources win so a freshly fetched actor overrides a remembered one. */
export function mergeActors(...sources: KnownActor[][]): KnownActor[] {
  const seen = new Map<string, KnownActor>();
  for (const list of sources) for (const a of list) if (!seen.has(a.id)) seen.set(a.id, a);
  return [...seen.values()];
}

export const actorLabel = (a: Pick<KnownActor, "display_name" | "kind" | "id">) => `${a.display_name} (${a.kind.toLowerCase()}, ${a.id.slice(0, 8)})`;
