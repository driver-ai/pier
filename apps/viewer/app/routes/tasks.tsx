// Tasks browser route — now a first-class, directly-navigable destination
// (reached from the top nav Tasks tab) AND a drill target from an Evidence
// `ConditionComparison` cell. It lists per-item scores across conditions for a
// chosen {model, exam_mode} scope, filterable by task type.
//
// Scope + filters (all nuqs-backed, deep-linkable):
//   - `model` — which model's matrix to show. Defaults to the first model in the
//     records when absent (so the page renders straight from the nav tab).
//   - `exam_mode` — consumer mode. Defaults to "sealed" if present, else the
//     first exam_mode. These two drive the `taskRowsFor` scope. Each may be set
//     to "All" (the ALL sentinel, cleared from the URL): the matrix then expands
//     so every row is still exactly one (model, mode) — scores are never blended.
//   - `task_type` — the item's `exam_type` (mcq/cloze/claim/rubric/…); defaults
//     to "All". When set, filters the rows to `row.examType === task_type`.
//   - `condition` — OPTIONAL highlight carried when drilled from a bar (a column
//     is visually marked); absent when navigated from the nav tab. Never a
//     required filter.
//
// Data: reuses Plan 01/03's `/api/run-records` via `fetchRunRecords` (404 → [])
// and Plan 02's condition config via `useConditions` — no filtered endpoint, no
// aggregate re-fetch (Architecture Fit). `taskRowsFor` (Task 3) shapes the
// served records client-side into per-item rows, pre-sorted by disagreement
// DESC; `TaskList` (Task 4) renders + re-sorts. Filter options are derived from
// the loaded data (distinct values) — no hardcoded condition/exam_type ids.
//
// A row click navigates into the Plan 06 trace view by the row's canonical
// `record_id` at `/trace?record=<recordId>`. Presents evidence only (DEC-010).

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { fetchRunRecords } from "~/lib/api";
import { conditionLabel, useConditions } from "~/lib/conditions";
import { taskRowsFor } from "~/lib/tasks";
import type { RunRecord } from "~/lib/types";

const ALL = "__all__";

/** Distinct, sorted non-empty string values of one field across records. */
function distinct(
  rows: RunRecord[],
  pick: (row: RunRecord) => string | null | undefined
): string[] {
  const set = new Set<string>();
  for (const r of rows) {
    const v = pick(r);
    if (v != null && v !== "") set.add(v);
  }
  return [...set].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/**
 * A labeled scope/filter dropdown mirroring trajectories.tsx's `FilterSelect`.
 * When `allowAll` is set an "All" option is prepended — used for task type and,
 * via row-expansion, the model and consumer-mode scope selects.
 */
function FilterSelect({
  label,
  value,
  onChange,
  options,
  allowAll,
  formatOption,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  allowAll?: boolean;
  formatOption?: (v: string) => string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger size="sm" className="min-w-[9rem]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allowAll ? <SelectItem value={ALL}>All</SelectItem> : null}
          {options.map((opt) => (
            <SelectItem key={opt} value={opt}>
              {formatOption ? formatOption(opt) : opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

export default function Tasks() {
  const navigate = useNavigate();

  // Scope + filters + highlight (URL params, deep-link).
  const [modelParam, setModel] = useQueryState(
    "model",
    parseAsString.withDefault("")
  );
  const [examModeParam, setExamMode] = useQueryState(
    "exam_mode",
    parseAsString.withDefault("")
  );
  const [taskType, setTaskType] = useQueryState(
    "task_type",
    parseAsString.withDefault(ALL)
  );
  // Highlight only — set when drilled from an Evidence bar; absent from the nav.
  const [condition] = useQueryState("condition", parseAsString.withDefault(""));

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

  const rows = records ?? [];

  // Filter options derived from the loaded data (never hardcoded ids).
  const modelOpts = useMemo(() => distinct(rows, (r) => r.model), [rows]);
  const examModeOpts = useMemo(
    () => distinct(rows, (r) => r.exam_mode),
    [rows]
  );
  const taskTypeOpts = useMemo(
    () => distinct(rows, (r) => r.exam_type),
    [rows]
  );

  // Effective scope. `null` means "All" (row-expansion, not a blend). "All" is
  // opt-in via the ALL sentinel; the DEFAULTS stay concrete so the page renders
  // scoped from the nav tab. A present-but-invalid value falls back to the
  // concrete default (never silently to All).
  //   Model → All when ALL; else first present.
  //   exam_mode → All when ALL; else "sealed" if present, else the first.
  const model: string | null =
    modelParam === ALL
      ? null
      : modelParam && modelOpts.includes(modelParam)
        ? modelParam
        : modelOpts[0] ?? "";
  const examMode: string | null =
    examModeParam === ALL
      ? null
      : examModeParam && examModeOpts.includes(examModeParam)
        ? examModeParam
        : examModeOpts.includes("sealed")
          ? "sealed"
          : examModeOpts[0] ?? "";

  // The value the selects display: the ALL sentinel when the axis is All, else
  // the resolved concrete value.
  const modelValue = model === null ? ALL : model;
  const examModeValue = examMode === null ? ALL : examMode;

  // Shape scoped rows, then apply the task-type filter (row-level, post-shape).
  // `null` on an axis expands rows over that axis (each row still one model+mode).
  const shapedRows = useMemo(() => {
    if (!records) return [];
    if (model === "" || examMode === "") return [];
    return taskRowsFor(
      records,
      { model, examMode },
      conditions ?? null,
      condition || undefined
    );
  }, [records, model, examMode, conditions, condition]);

  const visibleRows = useMemo(() => {
    if (taskType === ALL) return shapedRows;
    return shapedRows.filter((r) => r.examType === taskType);
  }, [shapedRows, taskType]);

  // Human-readable label for the highlighted condition (falls back to the id).
  const highlightMeta = conditionLabel(conditions, condition);
  const highlightLabel = highlightMeta?.label ?? condition;

  // A scope is valid when each axis is either All (null) or a concrete non-empty
  // value; only the "no models/modes present at all" empty-data case is invalid.
  const hasScope = model !== "" && examMode !== "";
  const hasRows = visibleRows.length > 0;

  return (
    <div>
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
              Per-item scores across conditions. Filter by model, consumer mode,
              and task type; sort by disagreement. Set model or consumer mode to
              All to expand one row per (model, mode) — scores stay per-row, not
              blended.
              {condition ? (
                <>
                  {" "}
                  Highlighting{" "}
                  <span className="text-foreground">{highlightLabel}</span>.
                </>
              ) : null}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/evidence">Back to evidence</Link>
          </Button>
        </div>
      </div>

      {/* Scope + filters — all deep-linkable via nuqs. */}
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <FilterSelect
          label="Model"
          value={modelValue}
          // Model/mode default to a concrete value when the param is absent, so
          // "All" must be stored as the ALL sentinel in the URL — NOT cleared
          // (a cleared param resolves back to the concrete default). Differs from
          // Task type, whose absent-default is already All.
          onChange={(v) => setModel(v)}
          options={modelOpts}
          allowAll
        />
        <FilterSelect
          label="Consumer mode"
          value={examModeValue}
          onChange={(v) => setExamMode(v)}
          options={examModeOpts}
          allowAll
        />
        <FilterSelect
          label="Task type"
          value={taskType}
          onChange={(v) => setTaskType(v === ALL ? null : v)}
          options={taskTypeOpts}
          allowAll
        />
      </div>

      {!isLoading && (!hasScope || !hasRows) ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <ListTree />
            </EmptyMedia>
            <EmptyTitle>No tasks for this scope</EmptyTitle>
            <EmptyDescription>
              This model / consumer-mode / task-type combination has no scored
              run records. The run-records sidecar may be absent, or the active
              filters exclude everything.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <TaskList
          rows={visibleRows}
          conditions={conditions ?? null}
          highlightCondition={condition || null}
          showModel={model === null}
          showMode={examMode === null}
          onRowClick={(row) =>
            navigate(`/trace?record=${encodeURIComponent(row.recordId)}`)
          }
          isLoading={isLoading || (isFetching && visibleRows.length === 0)}
        />
      )}
    </div>
  );
}
