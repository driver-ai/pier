// Data-quality flags (Plan 07, Task 8).
//
// Surfaces the run's active data-quality notes (Plan 07a `data_notes.json`,
// served at `/api/data-notes`). Config-driven — no note text is hardcoded here;
// everything is read from the fetched notes (mirrors `useConditions` /
// `ConditionLabel`, DEC-009/DEC-010: present evidence only).
//
//   - `useDataNotes`      TanStack hook over `fetchDataNotes` (404 -> []).
//   - `DataQualityBadge`  a small warning badge shown next to a metric when any
//                         active note's `affects` includes that metric id; the
//                         tooltip lists the affecting notes' title/description.
//   - `DataNotesSurface`  lists all active notes (id · title · description ·
//                         affects) for the evidence landing.

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "~/components/ui/tooltip";
import { fetchDataNotes } from "~/lib/api";
import type { DataNote } from "~/lib/types";
import { cn } from "~/lib/utils";

/**
 * Load the run's active data-quality notes. Returns `[]` (via the fetcher) when
 * the run has no `data_notes.json` — the sidecar is optional, mirroring the
 * conditions/aggregates fetchers. Cached indefinitely: notes are static per run.
 */
export function useDataNotes() {
  return useQuery({
    queryKey: ["dataNotes"],
    queryFn: fetchDataNotes,
    staleTime: Infinity,
  });
}

/** Pure lookup: notes whose `affects` includes the given metric id. */
export function notesForMetric(
  notes: DataNote[] | null | undefined,
  metric: string
): DataNote[] {
  if (!notes) return [];
  return notes.filter((n) => n.affects.includes(metric));
}

/**
 * A small warning badge rendered inline next to a metric. Shows only when an
 * active note affects `metric`; renders nothing otherwise (so callers can drop
 * it beside any metric unconditionally). The tooltip lists each affecting note.
 */
export function DataQualityBadge({
  metric,
  className,
}: {
  metric: string;
  className?: string;
}) {
  const { data: notes } = useDataNotes();
  const active = notesForMetric(notes, metric);

  if (active.length === 0) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex items-center gap-1 text-xs cursor-default text-amber-600 dark:text-amber-500",
            className
          )}
          data-data-quality-flag={metric}
          aria-label={`Data-quality note affects ${metric}`}
        >
          <AlertTriangle className="size-3.5" aria-hidden />
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <div className="space-y-2 text-left">
          {active.map((note) => (
            <div key={note.id}>
              <div className="font-medium">{note.title}</div>
              <div className="text-background/80">{note.description}</div>
            </div>
          ))}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Lists all active data-quality notes for a run. Renders nothing when there are
 * no notes (an untroubled run shows no section). Presentational — config-driven.
 */
export function DataNotesSurface({ className }: { className?: string }) {
  const { data: notes } = useDataNotes();
  const active = notes ?? [];

  if (active.length === 0) return null;

  return (
    <section className={cn("space-y-3 border border-border p-4", className)}>
      <div className="flex items-center gap-2">
        <AlertTriangle className="size-4 text-amber-600 dark:text-amber-500" aria-hidden />
        <h2 className="text-sm font-medium">Data notes</h2>
        <span className="text-xs text-muted-foreground">({active.length})</span>
      </div>
      <ul className="space-y-3">
        {active.map((note) => (
          <li key={note.id} className="space-y-1 text-sm">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-xs text-muted-foreground">
                {note.id}
              </span>
              <span className="font-medium">{note.title}</span>
            </div>
            <p className="text-sm text-muted-foreground">{note.description}</p>
            {note.affects.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                <span className="text-xs text-muted-foreground">Affects:</span>
                {note.affects.map((metric) => (
                  <span
                    key={metric}
                    className="rounded-sm border border-border px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
                  >
                    {metric}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
