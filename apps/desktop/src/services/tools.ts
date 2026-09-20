import { queryOptions } from "@tanstack/react-query";
import { http } from "../lib/api";
import type { ToolManifest, ToolManifestListResponse } from "../lib/api/types";

export const toolKeys = { list: ["tools", "list"] as const, detail: (id: string) => ["tools", "detail", id] as const };

export const toolListQuery = () =>
  queryOptions({
    queryKey: toolKeys.list,
    queryFn: ({ signal }) => http.get<ToolManifestListResponse>("/api/v1/tools", { signal }),
  });

export const toolDetailQuery = (id: string) =>
  queryOptions({
    queryKey: toolKeys.detail(id),
    queryFn: ({ signal }) => http.get<ToolManifest>(`/api/v1/tools/${encodeURIComponent(id)}`, { signal }),
  });
