// Trajectories browser route — a top-level nav destination (between Evidence
// and Method) that lists the run's trajectories two ways:
//
//   - Trials sub-view: every scored run record (Plan 01/03 `/api/run-records`,
//     404 → []) as a paginated, filterable, sortable table. A row links to the
//     record-mode trace at `/trace?record=<record_id>`.
//   - Gathers sub-view: every standalone gather (producer) trajectory
//     (`/api/gathers`, 404 → []). A row links to the gather-mode trace at
//     `/trace?gather=<ref>`.
//
// The sub-view is URL-backed (nuqs `view`, default "trials") so the page is
// deep-linkable. Filters are derived from the loaded data (distinct values) and
// applied client-side — no filtered endpoint, no hardcoded condition ids
// (DEC-009/DEC-010, presents evidence only). Condition labels/rails come from
// `useConditions` + `ConditionLabel`. The ~3456-row Trials table paginates via
// react-table's client pagination so the DOM stays small.

import { useQuery } from "@tanstack/react-query";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Route, Waypoints } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";

import { ConditionLabel } from "~/components/condition-label";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
} from "~/components/ui/breadcrumb";
import { Button } from "~/components/ui/button";
import { SortableHeader } from "~/components/ui/data-table";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "~/components/ui/table";
import { fetchGathers, fetchRunRecords } from "~/lib/api";
import { conditionLabel, useConditions } from "~/lib/conditions";
import { cn } from "~/lib/utils";
import type { ConditionMeta, GatherSummary, RunRecord } from "~/lib/types";

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

type SubView = "trials" | "gathers";

const ALL = "__all__";
const PAGE_SIZE = 50;

/** Distinct, sorted non-empty string values of one field across rows. */
function distinct<T>(
  rows: T[],
  pick: (row: T) => string | null | undefined
): string[] {
  const set = new Set<string>();
  for (const r of rows) {
    const v = pick(r);
    if (v != null && v !== "") set.add(v);
  }
  return [...set].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

/** Distinct seed values (numbers) across rows, ascending; nulls dropped. */
function distinctSeeds<T>(
  rows: T[],
  pick: (row: T) => number | null | undefined
): number[] {
  const set = new Set<number>();
  for (const r of rows) {
    const v = pick(r);
    if (v != null && Number.isFinite(v)) set.add(v);
  }
  return [...set].sort((a, b) => a - b);
}

/**
 * A labeled "All"-defaulting filter dropdown. `value` is `ALL` when unfiltered.
 * Condition options render through the config label; everything else is raw.
 */
function FilterSelect({
  label,
  value,
  onChange,
  options,
  formatOption,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
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
          <SelectItem value={ALL}>All</SelectItem>
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

function fmtPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtUsd(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `$${v.toFixed(4)}`;
}

function fmtScore(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(3);
}

// ---------------------------------------------------------------------------
// Trials sub-view
// ---------------------------------------------------------------------------

function TrialsView() {
  const navigate = useNavigate();

  const {
    data: records,
    isLoading: recordsLoading,
    isFetching: recordsFetching,
  } = useQuery({
    queryKey: ["runRecords"],
    queryFn: fetchRunRecords,
    staleTime: Infinity,
  });

  const { data: conditions, isLoading: condLoading } = useConditions();

  const isLoading = recordsLoading || condLoading;

  const rows = records ?? [];

  // Filter state — all default to unfiltered (ALL).
  const [model, setModel] = useState<string>(ALL);
  const [condition, setCondition] = useState<string>(ALL);
  const [examMode, setExamMode] = useState<string>(ALL);
  const [seed, setSeed] = useState<string>(ALL);

  const modelOpts = useMemo(() => distinct(rows, (r) => r.model), [rows]);
  const conditionOpts = useMemo(
    () => orderedConditionOptions(rows, conditions ?? null),
    [rows, conditions]
  );
  const examModeOpts = useMemo(
    () => distinct(rows, (r) => r.exam_mode),
    [rows]
  );
  const seedOpts = useMemo(
    () => distinctSeeds(rows, (r) => r.seed).map(String),
    [rows]
  );

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (model !== ALL && r.model !== model) return false;
      if (condition !== ALL && r.condition !== condition) return false;
      if (examMode !== ALL && r.exam_mode !== examMode) return false;
      if (seed !== ALL && String(r.seed ?? "") !== seed) return false;
      return true;
    });
  }, [rows, model, condition, examMode, seed]);

  const columns = useMemo<ColumnDef<RunRecord>[]>(
    () => [
      {
        accessorKey: "item_id",
        header: ({ column }) => (
          <SortableHeader column={column}>Item</SortableHeader>
        ),
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.item_id}</span>
        ),
      },
      {
        accessorKey: "condition",
        header: ({ column }) => (
          <SortableHeader column={column}>Condition</SortableHeader>
        ),
        cell: ({ row }) => <ConditionLabel id={row.original.condition} />,
      },
      {
        accessorKey: "model",
        header: ({ column }) => (
          <SortableHeader column={column}>Model</SortableHeader>
        ),
      },
      {
        accessorKey: "exam_mode",
        header: ({ column }) => (
          <SortableHeader column={column}>Consumer mode</SortableHeader>
        ),
      },
      {
        accessorKey: "seed",
        header: ({ column }) => (
          <SortableHeader column={column}>Seed</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) =>
          row.original.seed == null ? "—" : row.original.seed,
      },
      {
        accessorKey: "score",
        header: ({ column }) => (
          <SortableHeader column={column}>Score</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) => fmtScore(row.original.score),
      },
      {
        accessorKey: "abstained",
        header: ({ column }) => (
          <SortableHeader column={column}>Abstained</SortableHeader>
        ),
        cell: ({ row }) => (row.original.abstained ? "yes" : "no"),
      },
      {
        id: "producer",
        accessorFn: (r) => (r.producer_trajectory_ref ? 1 : 0),
        header: ({ column }) => (
          <SortableHeader column={column}>Producer?</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) =>
          row.original.producer_trajectory_ref ? "yes" : "no",
      },
    ],
    []
  );

  return (
    <PaginatedTable
      columns={columns}
      data={filtered}
      isLoading={isLoading}
      isFetching={recordsFetching}
      getRowId={(r) => r.record_id}
      onRowClick={(r) =>
        navigate(`/trace?record=${encodeURIComponent(r.record_id)}`)
      }
      emptyIcon={<Route />}
      emptyTitle="No run records"
      emptyDescription="This run has no scored run records. The run-records sidecar may be absent, or the active filters exclude everything."
      filters={
        <>
          <FilterSelect
            label="Model"
            value={model}
            onChange={setModel}
            options={modelOpts}
          />
          <FilterSelect
            label="Condition"
            value={condition}
            onChange={setCondition}
            options={conditionOpts}
            formatOption={(id) =>
              conditionLabel(conditions ?? null, id)?.label ?? id
            }
          />
          <FilterSelect
            label="Consumer mode"
            value={examMode}
            onChange={setExamMode}
            options={examModeOpts}
          />
          <FilterSelect
            label="Seed"
            value={seed}
            onChange={setSeed}
            options={seedOpts}
          />
        </>
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Gathers sub-view
// ---------------------------------------------------------------------------

function GathersView() {
  const navigate = useNavigate();

  const {
    data: gathers,
    isLoading: gathersLoading,
    isFetching: gathersFetching,
  } = useQuery({
    queryKey: ["gathers"],
    queryFn: fetchGathers,
    staleTime: Infinity,
  });

  const { data: conditions, isLoading: condLoading } = useConditions();

  const isLoading = gathersLoading || condLoading;
  const rows = gathers ?? [];

  const [model, setModel] = useState<string>(ALL);
  const [condition, setCondition] = useState<string>(ALL);
  const [seed, setSeed] = useState<string>(ALL);

  const modelOpts = useMemo(() => distinct(rows, (r) => r.model), [rows]);
  const conditionOpts = useMemo(
    () => orderedConditionOptions(rows, conditions ?? null),
    [rows, conditions]
  );
  const seedOpts = useMemo(
    () => distinctSeeds(rows, (r) => r.seed).map(String),
    [rows]
  );

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (model !== ALL && r.model !== model) return false;
      if (condition !== ALL && r.condition !== condition) return false;
      if (seed !== ALL && String(r.seed ?? "") !== seed) return false;
      return true;
    });
  }, [rows, model, condition, seed]);

  const columns = useMemo<ColumnDef<GatherSummary>[]>(
    () => [
      {
        accessorKey: "model",
        header: ({ column }) => (
          <SortableHeader column={column}>Model</SortableHeader>
        ),
      },
      {
        accessorKey: "condition",
        header: ({ column }) => (
          <SortableHeader column={column}>Condition</SortableHeader>
        ),
        cell: ({ row }) => <ConditionLabel id={row.original.condition} />,
      },
      {
        accessorKey: "seed",
        header: ({ column }) => (
          <SortableHeader column={column}>Seed</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) =>
          row.original.seed == null ? "—" : row.original.seed,
      },
      {
        accessorKey: "mean_coverage",
        header: ({ column }) => (
          <SortableHeader column={column}>Coverage</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) => fmtPct(row.original.mean_coverage),
      },
      {
        accessorKey: "cost_usd",
        header: ({ column }) => (
          <SortableHeader column={column}>Cost</SortableHeader>
        ),
        sortingFn: "basic",
        cell: ({ row }) => fmtUsd(row.original.cost_usd),
      },
    ],
    []
  );

  return (
    <PaginatedTable
      columns={columns}
      data={filtered}
      isLoading={isLoading}
      isFetching={gathersFetching}
      getRowId={(r) => r.ref}
      onRowClick={(r) =>
        navigate(`/trace?gather=${encodeURIComponent(r.ref)}`)
      }
      emptyIcon={<Waypoints />}
      emptyTitle="No gathers"
      emptyDescription="This run has no standalone gather trajectories. The gathers sidecar may be absent, or the active filters exclude everything."
      filters={
        <>
          <FilterSelect
            label="Model"
            value={model}
            onChange={setModel}
            options={modelOpts}
          />
          <FilterSelect
            label="Condition"
            value={condition}
            onChange={setCondition}
            options={conditionOpts}
            formatOption={(id) =>
              conditionLabel(conditions ?? null, id)?.label ?? id
            }
          />
          <FilterSelect
            label="Seed"
            value={seed}
            onChange={setSeed}
            options={seedOpts}
          />
        </>
      }
    />
  );
}

/**
 * Distinct condition ids present in the rows, ordered by the config `order`
 * (DEC-009). Present ids the config does not mention are appended first-seen.
 */
function orderedConditionOptions(
  rows: Array<{ condition: string }>,
  conditions: ConditionMeta[] | null
): string[] {
  const present = distinct(rows, (r) => r.condition);
  if (!conditions || conditions.length === 0) return present;
  const presentSet = new Set(present);
  const ordered = [...conditions]
    .sort((a, b) => a.order - b.order)
    .map((c) => c.id)
    .filter((id) => presentSet.has(id));
  const known = new Set(ordered);
  const extras = present.filter((id) => !known.has(id));
  return [...ordered, ...extras];
}

// ---------------------------------------------------------------------------
// Paginated table (client pagination — keeps the DOM small for ~3456 rows)
// ---------------------------------------------------------------------------

interface PaginatedTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  isLoading: boolean;
  isFetching: boolean;
  getRowId: (row: TData) => string;
  onRowClick: (row: TData) => void;
  filters: React.ReactNode;
  emptyIcon: React.ReactNode;
  emptyTitle: string;
  emptyDescription: string;
}

function PaginatedTable<TData>({
  columns,
  data,
  isLoading,
  isFetching,
  getRowId,
  onRowClick,
  filters,
  emptyIcon,
  emptyTitle,
  emptyDescription,
}: PaginatedTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const table = useReactTable({
    data,
    columns,
    getRowId,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: PAGE_SIZE } },
  });

  const pageRows = table.getRowModel().rows;
  const pageIndex = table.getState().pagination.pageIndex;
  const pageCount = table.getPageCount();
  const total = data.length;

  const showEmpty = !isLoading && total === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">{filters}</div>

      {showEmpty ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">{emptyIcon}</EmptyMedia>
            <EmptyTitle>{emptyTitle}</EmptyTitle>
            <EmptyDescription>{emptyDescription}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <div className="relative border bg-card">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody className={cn(isFetching && "opacity-60")}>
                {pageRows.length ? (
                  pageRows.map((row) => (
                    <TableRow
                      key={row.id}
                      onClick={() => onRowClick(row.original)}
                      className="cursor-pointer"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="h-24 text-center text-muted-foreground"
                    >
                      {isLoading ? "Loading…" : "No results."}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {total.toLocaleString()} row{total === 1 ? "" : "s"}
              {pageCount > 1 ? (
                <>
                  {" · page "}
                  {pageIndex + 1} of {pageCount}
                </>
              ) : null}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Route
// ---------------------------------------------------------------------------

export default function Trajectories() {
  const [viewParam, setViewParam] = useQueryState(
    "view",
    parseAsString.withDefault("trials")
  );
  const view: SubView = viewParam === "gathers" ? "gathers" : "trials";

  return (
    <div>
      <div className="mb-8">
        <Breadcrumb className="mb-4">
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbPage>Trajectories</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-4xl font-normal tracking-tighter font-mono">
              Trajectories
            </h1>
            <p className="mt-4 text-sm text-muted-foreground">
              Browse every scored trial and standalone gather in this run. Open
              a row to inspect its trajectory.
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/evidence">Back to evidence</Link>
          </Button>
        </div>
      </div>

      {/* Sub-view segmented control. */}
      <div className="mb-6 inline-flex items-center gap-1 rounded-md border bg-card p-1">
        <SubViewButton
          active={view === "trials"}
          onClick={() => setViewParam(null)}
        >
          Trials
        </SubViewButton>
        <SubViewButton
          active={view === "gathers"}
          onClick={() => setViewParam("gathers")}
        >
          Gathers
        </SubViewButton>
      </div>

      {view === "trials" ? <TrialsView /> : <GathersView />}
    </div>
  );
}

function SubViewButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-sm px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}
