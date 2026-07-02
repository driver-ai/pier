// Evidence landing route (Plan 03, Task 7) — the entry for pier's evidence
// mode. `home.tsx` redirects `mode === "evidence"` here (Plan 02).
//
// Composes the two lead elements — the `ConditionComparison` bars and the
// `CostLens` scatter — over the precomputed `condition_aggregates.json`
// (fetched via `fetchConditionAggregates`) and Plan 02's condition config
// (`useConditions`). No run-records here (that is Plan 04's task drill); this
// landing reads only what the comparison + cost lens need.
//
// Consumer mode (exam mode) is lifted into this route as ONE shared dimension
// (DEC-012): the same selection drives both the comparison and the cost lens,
// rather than each owning an independent selector. The comparison renders the
// selector (it also owns the view toggle); the route holds the state and passes
// the resolved active mode to the cost lens.
//
// Presents evidence only — no stated conclusions (DEC-010). When the aggregates
// sidecar is absent the fetcher yields `[]` (404 → []); the route renders
// pier's `Empty` state, never a white screen (dry-run 03 Gap 9).

import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";

import { ConditionComparison } from "~/components/condition-comparison";
import { CostLens } from "~/components/cost-lens";
import { DataNotesSurface } from "~/components/data-quality";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
} from "~/components/ui/breadcrumb";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { fetchConditionAggregates } from "~/lib/api";
import { examModes } from "~/lib/comparison";
import { useConditions } from "~/lib/conditions";

export default function Evidence() {
  // Precomputed aggregates (pier does not re-aggregate). 404 → [] via the
  // fetcher, so an absent sidecar is an empty list, not an error.
  const {
    data: aggregates,
    isLoading: aggLoading,
    isFetching: aggFetching,
  } = useQuery({
    queryKey: ["conditionAggregates"],
    queryFn: fetchConditionAggregates,
    staleTime: Infinity,
  });

  // Plan 02 condition config for labels + rails ordering.
  const {
    data: conditions,
    isLoading: condLoading,
    isFetching: condFetching,
  } = useConditions();

  // Consumer (exam) mode lifted here as one shared dimension (DEC-012).
  const [examMode, setExamMode] = useState<string | null>(null);

  const modes = useMemo(() => examModes(aggregates ?? []), [aggregates]);

  // Resolve the active mode the same way ConditionComparison does, so the cost
  // lens is scoped to exactly the mode the (controlled) selector shows.
  const activeMode =
    examMode && modes.includes(examMode) ? examMode : (modes[0] ?? null);

  const isLoading = aggLoading || condLoading;
  const isFetching = aggFetching || condFetching;

  const hasAggregates = !!aggregates && aggregates.length > 0;

  return (
    <div className="px-4 py-10">
      <div className="mb-8">
        <Breadcrumb className="mb-4">
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbPage>Evidence</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
        <h1 className="text-4xl font-normal tracking-tighter font-mono">
          Evidence
        </h1>
        <p className="mt-4 text-sm text-muted-foreground">
          How each context condition changes performance per model, and what it
          costs.
        </p>
      </div>

      {!isLoading && !hasAggregates ? (
        <div className="flex flex-col gap-8">
          {/* Active data-quality notes surface even when there are no aggregates. */}
          <DataNotesSurface />
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BarChart3 />
              </EmptyMedia>
              <EmptyTitle>No evidence for this run</EmptyTitle>
              <EmptyDescription>
                This run has no condition aggregates to compare. The evidence
                sidecar (<code>condition_aggregates.json</code>) may be absent.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {/* Active data-quality notes (Plan 07) — config-driven; hidden when none. */}
          <DataNotesSurface />
          <ConditionComparison
            aggregates={aggregates}
            conditions={conditions}
            examMode={examMode}
            onExamModeChange={setExamMode}
            isLoading={isLoading}
            isFetching={isFetching}
          />
          <CostLens
            aggregates={aggregates}
            conditions={conditions}
            examMode={activeMode}
            isLoading={isLoading}
            isFetching={isFetching}
          />
        </div>
      )}
    </div>
  );
}
