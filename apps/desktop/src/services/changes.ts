import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { http, newIdempotencyKey } from "../lib/api";
import type {
  ChangeCreateRequest,
  ChangeListResponse,
  ChangeView,
  EvidenceOverview,
  JournalEventListResponse,
  RepositoryInfo,
} from "../lib/api/types";

export const changeKeys = {
  all: ["changes"] as const,
  list: () => [...changeKeys.all, "list"] as const,
  pages: () => [...changeKeys.all, "pages"] as const,
  detail: (id: string) => [...changeKeys.all, "detail", id] as const,
  evidence: (id: string) => [...changeKeys.all, "evidence", id] as const,
  events: (id: string) => [...changeKeys.all, "events", id] as const,
};

export const PAGE_SIZE = 50;

export const changeListQuery = () =>
  queryOptions({
    queryKey: changeKeys.list(),
    queryFn: ({ signal }) =>
      http.get<ChangeListResponse>("/api/v1/changes", { query: { limit: PAGE_SIZE, offset: 0 }, signal }),
  });

/** Every page of Changes, newest first. A full page means there may be more; a short page is the end. */
export const changePagesQuery = () =>
  infiniteQueryOptions({
    queryKey: changeKeys.pages(),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      http.get<ChangeListResponse>("/api/v1/changes", { query: { limit: PAGE_SIZE, offset: pageParam }, signal }),
    // `total` is the real number of Changes. Fall back to "a full page means maybe more" only for a backend that doesn't report it.
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((n, p) => n + p.items.length, 0);
      if (typeof last.total === "number") return loaded < last.total ? loaded : undefined;
      return last.items.length >= PAGE_SIZE ? loaded : undefined;
    },
  });

export const changeDetailQuery = (id: string) =>
  queryOptions({
    queryKey: changeKeys.detail(id),
    queryFn: ({ signal }) => http.get<ChangeView>(`/api/v1/changes/${encodeURIComponent(id)}`, { signal }),
  });

export const evidenceQuery = (id: string) =>
  queryOptions({
    queryKey: changeKeys.evidence(id),
    queryFn: ({ signal }) =>
      http.get<EvidenceOverview>(`/api/v1/changes/${encodeURIComponent(id)}/evidence`, { signal }),
  });

export const EVENT_PAGE_SIZE = 100;

/** Events are ordered by `seq`. The backend's `since_seq` is inclusive and starts at 1, so the next cursor is last `seq` + 1. */
export const eventPagesQuery = (id: string) =>
  infiniteQueryOptions({
    queryKey: [...changeKeys.events(id), "pages"] as const,
    initialPageParam: 1,
    queryFn: ({ pageParam, signal }) =>
      http.get<JournalEventListResponse>(`/api/v1/changes/${encodeURIComponent(id)}/events`, {
        query: { limit: EVENT_PAGE_SIZE, since_seq: pageParam },
        signal,
      }),
    getNextPageParam: (last) => {
      const items = last.items ?? [];
      return items.length >= EVENT_PAGE_SIZE ? items[items.length - 1]!.seq + 1 : undefined;
    },
  });

export const eventsQuery = (id: string) =>
  queryOptions({
    queryKey: changeKeys.events(id),
    queryFn: ({ signal }) =>
      http.get<JournalEventListResponse>(`/api/v1/changes/${encodeURIComponent(id)}/events`, {
        query: { limit: 100 },
        signal,
      }),
  });

export function validateRepository(path: string): Promise<RepositoryInfo> {
  return http.post<RepositoryInfo>("/api/v1/repositories/validate", { path });
}

/** `idempotencyKey` is owned by the caller so a retry of the same submission reuses it. */
export function createChange(request: ChangeCreateRequest, idempotencyKey = newIdempotencyKey()) {
  return http.post<ChangeView>("/api/v1/changes", request, { idempotencyKey });
}
