// TaskList — the per-item drill table for the tasks route (Plan 04, Task 4).
//
// Presentational: the route shapes `RunRecord[]` into `TaskRow[]` via
// `taskRowsFor` (Task 3) and passes them here. This component only renders +
// sorts. Columns: item, question (render "—" on null), one column per condition
// (keyed/ordered by the passed config; the highlighted condition visually
// marked; rails styled via `condition-style` / `ConditionLabel`), and a
// disagreement column. Numeric columns are sortable; disagreement is the default
// sort (desc). Row click → `onRowClick(row)` (the route wires navigation into
// the trace view by `row.recordId`). No hardcoded condition ids — the column set
// derives from the config `order` restricted to ids present in the rows, exactly
// as `taskRowsFor` orders `scores` (DEC-009). Presents evidence only (DEC-010).

import { type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { ConditionLabel } from "~/components/condition-label";
import {
  DataTable,
  SortableHeader,
} from "~/components/ui/data-table";
import { conditionStyle } from "~/lib/condition-style";
import type { TaskRow } from "~/lib/tasks";
import type { ConditionMeta } from "~/lib/types";
import { cn } from "~/lib/utils";

export interface TaskListProps {
  /** Shaped rows from `taskRowsFor` (already scoped + sorted by the route). */
  rows: TaskRow[];
  /** Plan 02 condition config for column order + labels + rails styling. */
  conditions: ConditionMeta[] | null;
  /** The clicked condition id — its column is visually marked (not a filter). */
  highlightCondition?: string | null;
  /** Row click → the route navigates to the trace view by `row.recordId`. */
  onRowClick?: (row: TaskRow) => void;
  isLoading?: boolean;
}

/** Percent formatter shared by the per-condition + disagreement cells. */
function formatScore(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

/**
 * Order condition ids by the Plan 02 config `order` restricted to ids that
 * actually appear in the rows' `scores`, appending any present-but-unconfigured
 * ids in first-seen order. Mirrors `taskRowsFor`'s `orderConditions` so the
 * columns line up with the shaped `scores` map. Never a hardcoded id list.
 */
function orderColumnIds(
  rows: TaskRow[],
  conditions: ConditionMeta[] | null
): string[] {
  const firstSeen: string[] = [];
  for (const row of rows) {
    for (const id of Object.keys(row.scores)) {
      if (!firstSeen.includes(id)) firstSeen.push(id);
    }
  }
  const present = new Set(firstSeen);
  if (conditions && conditions.length > 0) {
    const ordered = [...conditions]
      .sort((a, b) => a.order - b.order)
      .map((c) => c.id)
      .filter((id) => present.has(id));
    const known = new Set(ordered);
    const extras = firstSeen.filter((id) => !known.has(id));
    return [...ordered, ...extras];
  }
  return firstSeen;
}

export function TaskList({
  rows,
  conditions,
  highlightCondition,
  onRowClick,
  isLoading,
}: TaskListProps) {
  const columnIds = useMemo(
    () => orderColumnIds(rows, conditions),
    [rows, conditions]
  );

  const railById = useMemo(
    () => new Map((conditions ?? []).map((c) => [c.id, c.is_rail])),
    [conditions]
  );

  const columns = useMemo<ColumnDef<TaskRow>[]>(() => {
    const conditionCols: ColumnDef<TaskRow>[] = columnIds.map((cid) => {
      const isHighlight = highlightCondition === cid;
      const isRail = railById.get(cid) === true;
      const style = conditionStyle(isRail);
      return {
        id: `condition:${cid}`,
        // Numeric access for the sort model (null sorts as -Infinity).
        accessorFn: (row) => {
          const v = row.scores[cid];
          return v == null ? Number.NEGATIVE_INFINITY : v;
        },
        header: ({ column }) => (
          <SortableHeader
            column={column}
            className={cn(isHighlight && "font-semibold text-foreground")}
          >
            <ConditionLabel
              id={cid}
              className={cn(isHighlight && "font-semibold text-foreground")}
            />
          </SortableHeader>
        ),
        cell: ({ row }) => (
          <span
            className={cn(
              "font-mono tabular-nums text-sm",
              style.className,
              isHighlight && "font-semibold text-foreground"
            )}
          >
            {formatScore(row.original.scores[cid] ?? null)}
          </span>
        ),
        sortingFn: "basic",
        enableSorting: true,
      };
    });

    return [
      {
        id: "item",
        accessorFn: (row) => row.itemId,
        header: ({ column }) => (
          <SortableHeader column={column}>Item</SortableHeader>
        ),
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.itemId}
          </span>
        ),
        sortingFn: "alphanumeric",
        enableSorting: true,
      },
      {
        id: "question",
        accessorFn: (row) => row.question ?? "",
        header: "Question",
        cell: ({ row }) => (
          <div className="max-w-md whitespace-normal break-words text-sm">
            {row.original.question ?? (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
        ),
        enableSorting: false,
      },
      ...conditionCols,
      {
        id: "disagreement",
        accessorFn: (row) => row.disagreement,
        header: ({ column }) => (
          <SortableHeader column={column}>Disagreement</SortableHeader>
        ),
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-sm">
            {formatScore(row.original.disagreement)}
          </span>
        ),
        sortingFn: "basic",
        enableSorting: true,
      },
    ];
  }, [columnIds, highlightCondition, railById]);

  // Default sort: disagreement DESC. Controlled so the header shows the active
  // sort indicator and the user can re-sort; rows also arrive pre-sorted this
  // way from `taskRowsFor`, so the first paint matches.
  const [sorting, setSorting] = useState<SortingState>([
    { id: "disagreement", desc: true },
  ]);

  return (
    <DataTable
      columns={columns}
      data={rows}
      onRowClick={onRowClick}
      getRowId={(row) => row.recordId}
      isLoading={isLoading}
      sorting={sorting}
      onSortingChange={setSorting}
      emptyState="No tasks for this scope."
    />
  );
}
