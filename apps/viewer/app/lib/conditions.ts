// Config-driven condition metadata (DEC-009).
//
// All condition labels/descriptions come from the run's `conditions.json`
// (served at `/api/conditions`) — never hardcoded ids or labels. `useConditions`
// is the TanStack Query data source; `conditionLabel` is a pure lookup over the
// loaded list that callers can use without touching the query layer.

import { useQuery } from "@tanstack/react-query";

import { fetchConditions } from "./api";
import type { ConditionMeta } from "./types";

/**
 * Load the run's condition metadata. Returns `null` (via the fetcher) when the
 * run has no `conditions.json` — evidence config is optional, mirroring the
 * pricing endpoint. Cached indefinitely: config is static for a run.
 */
export function useConditions() {
  return useQuery({
    queryKey: ["conditions"],
    queryFn: fetchConditions,
    staleTime: Infinity,
  });
}

/**
 * Pure lookup of a condition by id over an already-loaded list. Returns the
 * matching `ConditionMeta`, or `null` when the list is unloaded/absent or the
 * id is unknown. Callers fall back to the raw id when this returns `null`.
 */
export function conditionLabel(
  conditions: ConditionMeta[] | null | undefined,
  id: string
): ConditionMeta | null {
  if (!conditions) return null;
  return conditions.find((c) => c.id === id) ?? null;
}
