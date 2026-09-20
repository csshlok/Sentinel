import { useQueries, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { actorLabel, knownActors, mergeActors, type KnownActor } from "@/lib/known";
import { actorListQuery, actorQuery, delegationsQuery } from "@/services/actions";

/**
 * Actors a form can offer. Uses the backend's actor list when it has one. Against an older backend without `GET /actors`, it falls back
 * to actors named by this Change's delegations (resolved by id) plus those created on this install. `version` bumps after an actor is
 * created so the picker updates without a reload.
 */
export function useActors(changeId?: string) {
  const [version, setVersion] = useState(0);
  const list = useQuery(actorListQuery());
  const fallback = list.isError;
  const delegations = useQuery({ ...delegationsQuery(changeId ?? ""), enabled: fallback && Boolean(changeId) });
  const ids = fallback ? [...new Set((delegations.data?.items ?? []).flatMap((d) => [d.grantor_id, d.grantee_id]))] : [];
  const fetched = useQueries({ queries: ids.map((id) => actorQuery(id)) });
  const resolved: KnownActor[] = fetched.flatMap((q) => (q.data ? [{ id: q.data.id, display_name: q.data.display_name, kind: q.data.kind }] : []));
  const listed: KnownActor[] = (list.data?.items ?? []).map((a) => ({ id: a.id, display_name: a.display_name, kind: a.kind }));
  void version;
  const actors = mergeActors(listed, resolved, knownActors());
  return {
    actors,
    /** Real number of actors on the backend when it reports one; a page holds at most 100. */
    total: list.data?.total ?? null,
    /** True when the backend has an actor list, so the "known actors" caveat doesn't apply. */
    complete: list.isSuccess,
    refresh: () => { setVersion((v) => v + 1); void list.refetch(); },
    nameOf: (id: string) => { const a = actors.find((x) => x.id === id); return a ? actorLabel(a) : id; },
  };
}
