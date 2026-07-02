// Tasks drill route (Plan 04, Task 5) — reached by clicking a condition × model
// cell in the evidence `ConditionComparison`. The clicked cell scopes the list
// by `{model, exam_mode}` (URL params); the clicked `condition` is carried as a
// HIGHLIGHT param, not a filter — the list shows ALL conditions per item
// (DEC-014 D2, dry-run 04 MEDIUM 1).
//
// Data: reuses Plan 01/03's `/api/run-records` via `fetchRunRecords` (404 → [])
// and Plan 02's condition config via `useConditions` — no filtered endpoint, no
// aggregate re-fetch (Architecture Fit). `taskRowsFor` (Task 3) shapes the
// served records client-side into per-item rows. Rows are pre-sorted by
// disagreement DESC; `TaskList` (Task 4) renders + re-sorts.
//
// Deep-linkable (URL carries scope + highlight); browser back returns to
// `/evidence`. A row click navigates into the Plan 06 trace view by the row's
// canonical `record_id` (DEC-014 D2) at `/trace?record=<recordId>` — that route
// does not exist yet, so it 404s until Plan 06 implements it. Presents evidence
// only (DEC-010).

import { useQuery } from "@tanstack/react-query";
import { ListTree } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router";

import { TaskList } from "~/components/task-list";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "~/components/ui/breadcrumb";
import { Button } from "~/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { fetchRunRecords } from "~/lib/api";
import { conditionLabel, useConditions } from "~/lib/conditions";
import { taskRowsFor } from "~/lib/tasks";

export default function Tasks() {
  const navigate = useNavigate();

  // Scope + highlight from the clicked comparison cell (URL params, deep-link).
  const [model] = useQueryState("model", parseAsString.withDefault(""));
  const [examMode] = useQueryState("exam_mode", parseAsString.withDefault(""));
  const [condition] = useQueryState(
    "condition",
    parseAsString.withDefault("")
  );

  // Reuse the served run records (404 → []); no filtered endpoint.
  const {
    data: records,
    isLoading: recordsLoading,
    isFetching: recordsFetching,
  } = useQuery({
    queryKey: ["runRecords"],
    queryFn: fetchRunRecords,
    staleTime: Infinity,
  });

  const {
    data: conditions,
    isLoading: condLoading,
    isFetching: condFetching,
  } = useConditions();

  const isLoading = recordsLoading || condLoading;
  const isFetching = recordsFetching || condFetching;

  const rows = useMemo(() => {
    if (!records || !model || !examMode) return [];
    return taskRowsFor(
      records,
      { model, examMode },
      conditions ?? null,
      condition || undefined
    );
  }, [records, model, examMode, conditions, condition]);

  // Human-readable label for the highlighted condition (falls back to the id).
  const highlightMeta = conditionLabel(conditions, condition);
  const highlightLabel = highlightMeta?.label ?? condition;

  const hasScope = !!model && !!examMode;
  const hasRows = rows.length > 0;

  return (
    <div className="px-4 py-10">
      <div className="mb-8">
        <Breadcrumb className="mb-4">
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/evidence">Evidence</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>Tasks</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-4xl font-normal tracking-tighter font-mono">
              Tasks
            </h1>
            <p className="mt-4 text-sm text-muted-foreground">
              Per-item scores across all conditions
              {hasScope ? (
                <>
                  {" "}
                  for <span className="text-foreground">{model}</span> at{" "}
                  <span className="text-foreground">{examMode}</span>
                  {condition ? (
                    <>
                      , highlighting{" "}
                      <span className="text-foreground">{highlightLabel}</span>
                    </>
                  ) : null}
                </>
              ) : null}
              . Sort by disagreement to find where conditions diverge most.
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/evidence">Back to evidence</Link>
          </Button>
        </div>
      </div>

      {!isLoading && (!hasScope || !hasRows) ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ListTree />
            </EmptyMedia>
            <EmptyTitle>
              {hasScope ? "No tasks for this scope" : "No scope selected"}
            </EmptyTitle>
            <EmptyDescription>
              {hasScope
                ? "This model / consumer-mode has no scored run records. The run-records sidecar may be absent, or the scope carries no items."
                : "Open this view from an evidence comparison cell to scope it by model and consumer mode."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <TaskList
          rows={rows}
          conditions={conditions ?? null}
          highlightCondition={condition || null}
          onRowClick={(row) =>
            navigate(`/trace?record=${encodeURIComponent(row.recordId)}`)
          }
          isLoading={isLoading || (isFetching && rows.length === 0)}
        />
      )}
    </div>
  );
}
