// Trace route (Plan 06, Task 6 + Task 8 wiring) — the `/trace?record=<record_id>`
// destination that Plan 04's task rows link to. This is pier's EVIDENCE-mode
// trace view (root sidecars, no job/trial tree), NOT the job/trial `trial.tsx`
// view — those are left untouched (materialized Task 6 note).
//
// Composes three views over one run record:
//   - Consumer tab → the enriched `TrajectoryViewer` over the consumer envelope
//     (the enrichment overlay renders inline via the adapter).
//   - Producer tab → the enriched `TrajectoryViewer` over the producer envelope
//     + the hand-rolled `GatherPanels`. FIRST-CLASS tab (not a pseudo-subagent).
//     The tab is HIDDEN when the producer envelope is null (b0 / oracle
//     producers have no gather trajectory — the endpoint returns 200-null). It
//     is shown with an explicit ERROR state when the producer fetch throws (a
//     dangling sidecar → HTTP 500), so a dangling ref reads distinctly from an
//     absent producer.
//   - Forensics tab → `ForensicsPanel` over the `RunRecord` (reuses
//     `/api/run-records`; no dedicated endpoint).
//
// Data:
//   - consumer + producer envelopes via `fetchEnrichedTrajectory` (Task 2
//     endpoint). 200-null → null (no trajectory); 500 → thrown error (dangling).
//   - the run record via `fetchRunRecords` (404 → []), found by `record_id`.
//
// URL-backed `activeTab` (nuqs) makes the view deep-linkable. Renders pier's
// `Empty` when the record is unknown / the consumer envelope is missing, and
// loading states while fetching. Presents evidence only (DEC-010).
//
// This route has TWO modes, keyed off which URL param is present:
//   - Record mode (`?record=<id>`) — the consumer/producer/forensics tab view
//     above. Record takes precedence when both params are present.
//   - Gather mode (`?gather=<ref>`, no record) — a single standalone gather
//     trajectory reached from the Trajectories browser. No tabs; it is just the
//     one gather envelope (`TrajectoryViewer` + `GatherPanels`), fetched by ref
//     via `fetchTrajectoryByRef`. A dangling ref (HTTP 500 → thrown) shows an
//     explicit error state, distinct from an empty resolve.

import { useQuery } from "@tanstack/react-query";
import { FileSearch, Waypoints } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useMemo } from "react";
import { Link } from "react-router";

import { ForensicsPanel } from "~/components/forensics-panel";
import { GatherPanels, TrajectoryViewer } from "~/components/trajectory-viewer";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "~/components/ui/breadcrumb";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import {
  fetchEnrichedTrajectory,
  fetchRunRecords,
  fetchTrajectoryByRef,
} from "~/lib/api";

type TabValue = "consumer" | "producer" | "forensics";

/**
 * Best-effort parse of a gather ref into `model / condition / seed` for the
 * header. Refs are opaque paths; when the parse finds nothing, callers fall
 * back to showing the raw ref. Never throws.
 */
function parseGatherRef(ref: string): {
  model: string | null;
  condition: string | null;
  seed: string | null;
} {
  // ref is the DEC-014 D2 producer ref: `gather:{run_id}:{model}:{condition}:{seed}`
  // (colon-delimited, byte-identical to what the emitter / `/api/gathers` produce).
  const parts = ref.split(":");
  if (parts[0] === "gather" && parts.length >= 5) {
    return {
      model: parts[2] ?? null,
      condition: parts[3] ?? null,
      seed: parts[4] ?? null,
    };
  }
  return { model: null, condition: null, seed: null };
}

export default function Trace() {
  // The canonical record id (Plan 04 links `/trace?record=<url-encoded id>`).
  const [record] = useQueryState("record", parseAsString.withDefault(""));
  // A standalone gather ref (Trajectories browser links `/trace?gather=<ref>`).
  const [gather] = useQueryState("gather", parseAsString.withDefault(""));

  // Record takes precedence when both are present.
  const isGatherMode = gather.length > 0 && record.length === 0;

  if (isGatherMode) {
    return <GatherTrace gatherRef={gather} />;
  }

  // URL-backed active tab — deep-linkable. Consumer is the default (null param).
  const [tabParam, setTabParam] = useQueryState(
    "tab",
    parseAsString.withDefault("consumer")
  );

  const hasRecord = record.length > 0;

  // Consumer envelope (the primary trajectory). 200-null → null; 500 → error.
  const {
    data: consumerEnvelope,
    isLoading: consumerLoading,
    error: consumerError,
  } = useQuery({
    queryKey: ["enrichedTrajectory", record, "consumer"],
    queryFn: () => fetchEnrichedTrajectory(record, "consumer"),
    enabled: hasRecord,
    staleTime: Infinity,
    retry: false,
  });

  // Producer envelope. null for b0/oracle (hide the tab); a thrown error means
  // a dangling sidecar (show the error state, distinct from the null case).
  const {
    data: producerEnvelope,
    isLoading: producerLoading,
    error: producerError,
  } = useQuery({
    queryKey: ["enrichedTrajectory", record, "producer"],
    queryFn: () => fetchEnrichedTrajectory(record, "producer"),
    enabled: hasRecord,
    staleTime: Infinity,
    retry: false,
  });

  // Run records (for forensics). 404 → []; find the one this trace is about.
  const { data: records, isLoading: recordsLoading } = useQuery({
    queryKey: ["runRecords"],
    queryFn: fetchRunRecords,
    staleTime: Infinity,
  });

  const runRecord = useMemo(
    () => records?.find((r) => r.record_id === record) ?? null,
    [records, record]
  );

  // A resolved producer envelope means the producer tab is a first-class tab.
  // A null envelope (no trajectory) hides it; an error keeps it visible so the
  // dangling case is surfaced rather than silently dropped.
  const producerHasEnvelope = producerEnvelope != null;
  const producerDangling = producerError != null;
  const showProducerTab = producerHasEnvelope || producerDangling;

  // Resolve the active tab, guarding against a deep-link to a hidden producer.
  const requestedTab: TabValue =
    tabParam === "producer" || tabParam === "forensics"
      ? tabParam
      : "consumer";
  const activeTab: TabValue =
    requestedTab === "producer" && !showProducerTab ? "consumer" : requestedTab;

  // A run record gives the richest header; fall back to the consumer envelope /
  // the raw id otherwise.
  const headerModel = runRecord?.model ?? null;
  const headerItem = runRecord?.item_id ?? null;
  const headerCondition = runRecord?.condition ?? null;

  const isLoading = consumerLoading || producerLoading || recordsLoading;

  // The record is unknown / has no consumer trajectory: no scope selected, or a
  // record id with neither a run record nor a consumer envelope to render.
  const consumerMissing =
    !consumerLoading && consumerEnvelope == null && consumerError == null;
  const nothingToShow =
    !hasRecord || (consumerMissing && !runRecord && !showProducerTab);

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
              <BreadcrumbPage>Trace</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-4xl font-normal tracking-tighter font-mono">
              Trace
            </h1>
            <p className="mt-4 text-sm text-muted-foreground">
              {hasRecord ? (
                <>
                  {headerItem ? (
                    <>
                      <span className="text-foreground">{headerItem}</span>
                      {headerCondition ? (
                        <>
                          {" · "}
                          <span className="text-foreground">
                            {headerCondition}
                          </span>
                        </>
                      ) : null}
                      {headerModel ? (
                        <>
                          {" · "}
                          <span className="text-foreground">{headerModel}</span>
                        </>
                      ) : null}
                    </>
                  ) : (
                    <span className="font-mono text-foreground">{record}</span>
                  )}
                </>
              ) : (
                "Open a trace from a task row to inspect its trajectories."
              )}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/evidence">Back to evidence</Link>
          </Button>
        </div>
      </div>

      {nothingToShow && !isLoading ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileSearch />
            </EmptyMedia>
            <EmptyTitle>
              {hasRecord ? "No trace for this record" : "No record selected"}
            </EmptyTitle>
            <EmptyDescription>
              {hasRecord
                ? "This record has no consumer trajectory to show. The evidence sidecar may be absent, or the record id is unknown."
                : "Open this view from a task row to inspect a run record's consumer / producer trajectories and grader forensics."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Tabs
          value={activeTab}
          onValueChange={(value) =>
            setTabParam(value === "consumer" ? null : value)
          }
        >
          <TabsList className="mb-6">
            <TabsTrigger value="consumer">Consumer</TabsTrigger>
            {showProducerTab && (
              <TabsTrigger value="producer">Producer</TabsTrigger>
            )}
            <TabsTrigger value="forensics">Forensics</TabsTrigger>
          </TabsList>

          <TabsContent value="consumer" className="mt-0">
            <Card>
              <CardHeader>
                <CardTitle>Consumer trajectory</CardTitle>
              </CardHeader>
              <CardContent>
                {consumerLoading ? (
                  <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                    Loading trajectory…
                  </div>
                ) : consumerError ? (
                  <div className="text-sm text-destructive">
                    Failed to load the consumer trajectory:{" "}
                    {consumerError instanceof Error
                      ? consumerError.message
                      : "unknown error"}
                    .
                  </div>
                ) : consumerEnvelope ? (
                  <TrajectoryViewer trajectory={consumerEnvelope} />
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No consumer trajectory for this record.
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {showProducerTab && (
            <TabsContent value="producer" className="mt-0">
              {producerDangling ? (
                // Dangling sidecar (HTTP 500) — distinct from a null producer.
                // A null producer hides the tab entirely; here the ref exists
                // but points at a missing trajectory.
                <Card>
                  <CardHeader>
                    <CardTitle>Producer trajectory</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-sm text-destructive">
                      The producer trajectory reference is dangling — its sidecar
                      could not be resolved
                      {producerError instanceof Error
                        ? `: ${producerError.message}`
                        : "."}
                    </div>
                  </CardContent>
                </Card>
              ) : producerLoading ? (
                <Card>
                  <CardHeader>
                    <CardTitle>Producer trajectory</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                      Loading trajectory…
                    </div>
                  </CardContent>
                </Card>
              ) : producerEnvelope ? (
                <div className="flex flex-col gap-6">
                  <Card>
                    <CardHeader>
                      <CardTitle>Producer trajectory</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <TrajectoryViewer trajectory={producerEnvelope} />
                    </CardContent>
                  </Card>
                  <GatherPanels panels={producerEnvelope.panels} />
                </div>
              ) : null}
            </TabsContent>
          )}

          <TabsContent value="forensics" className="mt-0">
            <Card>
              <CardHeader>
                <CardTitle>Grader forensics</CardTitle>
              </CardHeader>
              <CardContent>
                {recordsLoading ? (
                  <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                    Loading forensics…
                  </div>
                ) : (
                  <ForensicsPanel record={runRecord} />
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

/**
 * Single standalone-gather view (gather mode). Fetches the gather envelope by
 * `ref` and renders it as one trajectory + its gather panels — no consumer /
 * producer / forensics tabs, because there is only the one gather here. A
 * dangling ref (HTTP 500 → thrown) surfaces as an explicit error; an envelope
 * that resolves to nothing surfaces as `Empty`.
 */
function GatherTrace({ gatherRef }: { gatherRef: string }) {
  const {
    data: envelope,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["gatherTrajectory", gatherRef],
    queryFn: () => fetchTrajectoryByRef(gatherRef),
    enabled: gatherRef.length > 0,
    staleTime: Infinity,
    retry: false,
  });

  const ident = useMemo(() => parseGatherRef(gatherRef), [gatherRef]);

  // Nothing to show: the fetch resolved to a null / trajectory-less envelope.
  const nothingToShow =
    !isLoading && error == null && (envelope == null || envelope.trajectory == null);

  return (
    <div>
      <div className="mb-8">
        <Breadcrumb className="mb-4">
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink asChild>
                <Link to="/trajectories?view=gathers">Trajectories</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>Gather</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-4xl font-normal tracking-tighter font-mono">
              Gather
            </h1>
            <p className="mt-4 text-sm text-muted-foreground">
              {ident.model || ident.condition || ident.seed ? (
                <>
                  {ident.model ? (
                    <span className="text-foreground">{ident.model}</span>
                  ) : null}
                  {ident.condition ? (
                    <>
                      {" · "}
                      <span className="text-foreground">{ident.condition}</span>
                    </>
                  ) : null}
                  {ident.seed ? (
                    <>
                      {" · seed "}
                      <span className="text-foreground">{ident.seed}</span>
                    </>
                  ) : null}
                </>
              ) : (
                <span className="font-mono text-foreground">{gatherRef}</span>
              )}
            </p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/trajectories?view=gathers">Back to trajectories</Link>
          </Button>
        </div>
      </div>

      {error != null ? (
        // Dangling gather ref (HTTP 500) — distinct from an empty resolve.
        <Card>
          <CardHeader>
            <CardTitle>Gather trajectory</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm text-destructive">
              The gather reference is dangling — its trajectory could not be
              resolved
              {error instanceof Error ? `: ${error.message}` : "."}
            </div>
          </CardContent>
        </Card>
      ) : nothingToShow ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Waypoints />
            </EmptyMedia>
            <EmptyTitle>No gather for this reference</EmptyTitle>
            <EmptyDescription>
              This reference resolved to no trajectory. It may be absent from the
              current run.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Gather trajectory</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  Loading trajectory…
                </div>
              ) : envelope ? (
                <TrajectoryViewer trajectory={envelope} />
              ) : null}
            </CardContent>
          </Card>
          {envelope?.panels ? (
            <GatherPanels panels={envelope.panels} />
          ) : null}
        </div>
      )}
    </div>
  );
}
