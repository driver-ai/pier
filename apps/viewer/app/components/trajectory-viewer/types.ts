/**
 * View-layer types for the trajectory viewer.
 *
 * Design tenet: stay true to ATIF. We do NOT reshape the trajectory —
 * one ATIF Step = one ViewStep, with a thin sidecar of view-derived
 * fields (parsed timestamps, normalized content parts, pre-resolved
 * sub-agent refs, pretty-printed tool args, etc.). The original ATIF
 * objects are kept untouched on `step` / `trajectory` / `result` so any
 * inspector can drill back to the canonical payload.
 *
 * Field naming: ATIF fields stay snake_case (we read them via `.step.*`
 * etc.); only view-derived sidecar fields are camelCase, by convention.
 */
import type { ContentPart, ObservationResult, Step, ToolCall, Trajectory } from "~/lib/types";

/**
 * Plan 05 enriched-trajectory overlay (the `enrichment` half of the
 * evidence envelope). Aligned to the raw ATIF by turn/call index — it is
 * NOT merged into the ATIF objects. The adapter attaches it as an
 * optional view-sidecar field (`viewEnrichment`), mirroring the existing
 * `epochMs` / `argsJson` / `subagent` sidecars.
 *
 * Field names are byte-exact per Plan 05's emission — do NOT rename.
 * Every field is optional so a partial or absent overlay degrades to the
 * raw-ATIF fallback rather than throwing.
 */

/** Per-call overlay (attached to `ResolvedToolCall.viewEnrichment`). */
export interface CallEnrichment {
  call_index?: number;
  function_name?: string;
  /** Channel classification (e.g. "read", "search", "execute"). */
  channel?: string;
  /** Whether this call landed in the task's gold set. */
  in_gold?: boolean;
  /** Attributed new input tokens for this call. */
  attributed_input_new?: number;
  /** Marginal cost of this call, in USD. */
  cost_usd?: number;
  /** True observation size, in tokens. */
  obs_tokens?: number;
  /** Truncated observation preview. */
  obs_excerpt?: string;
  /** Path(s) the call touched. */
  paths?: string[];
}

/** Per-turn overlay (attached to `ViewStep.viewEnrichment`). */
export interface StepEnrichment {
  index?: number;
  /** New (uncached) input tokens for this turn. */
  input_new?: number;
  /** Cached input tokens for this turn. */
  input_cached?: number;
  /** Cache-write tokens for this turn. */
  cache_write?: number;
  /** Output tokens for this turn. */
  output?: number;
  /** Total context size at this turn, in tokens. */
  context_size?: number;
  /** Output tokens attributed to gathered context. */
  output_attributed?: number;
  /** Baseline (un-attributed) tokens. */
  base_unattributed?: number;
  seconds?: number;
  model_text_excerpt?: string;
  /** Per-call overlays, aligned to the turn's tool calls by index. */
  calls?: CallEnrichment[];
}

/** The `enrichment` half of the Plan 05 envelope. */
export interface TrajectoryEnrichment {
  steps: StepEnrichment[];
}

/** Gather-only panel payloads (absent/null for consumer trajectories). */
export interface EnrichmentPanels {
  channel_mix?: unknown;
  tiers?: unknown;
  coverage?: unknown;
  off_gold?: unknown;
}

/**
 * The Plan 05 evidence envelope served by `/api/evidence/trajectory`.
 * `trajectory` is the untouched raw ATIF; the viewer overlays
 * `enrichment` by turn/call index and hand-rolls panels from `panels`.
 */
export interface EnrichedTrajectoryEnvelope {
  trajectory: Trajectory;
  enrichment?: TrajectoryEnrichment | null;
  panels?: EnrichmentPanels | null;
}

export interface ResolvedToolCall {
  /** Original ATIF tool call, untouched. */
  call: ToolCall;
  /** Pretty-printed JSON of `call.arguments` for the input panel. */
  argsJson: string;
  /** Optional Plan 05 per-call overlay (by call index). Absent when the
   *  trajectory was rendered from bare ATIF (fallback). */
  viewEnrichment?: CallEnrichment;
}

export interface ResolvedToolResult {
  /** Original ATIF observation result, untouched. */
  result: ObservationResult;
  /** Tool-call id this result pairs with. Falls back to a positional id
   *  when `source_call_id` is absent (some agents — mini-swe-agent in
   *  particular — emit observations without ids when call/result are 1:1
   *  positional). Empty string when no pairing is possible. */
  toolCallId: string;
  /** Concatenated text portion of `result.content`. */
  text: string;
  imageParts: Array<{ path: string; mediaType: string }>;
  isError: boolean;
  /** Pre-resolved sub-agent trajectory (when `subagent_trajectory_ref`
   *  resolves into the parent's `subagent_trajectories` array). */
  subagent?: ViewTrajectory;
}

export interface ViewStep {
  /** Original ATIF step, untouched. */
  step: Step;
  /** 0-based ordinal in `trajectory.steps` (preserved across
   *  preamble/turn split for things like flash + scroll). */
  index: number;
  /** Parsed `step.timestamp` as epoch ms, when present. */
  epochMs?: number;
  /** Normalized message content. A bare string in ATIF becomes
   *  `[{type: "text", text}]` so the renderer doesn't have to branch. */
  parts: ContentPart[];
  /** ATIF tool calls + view-derived fields (or `[]`). */
  toolCalls: ResolvedToolCall[];
  /** ATIF observation results + view-derived fields (or `[]`). */
  results: ResolvedToolResult[];
  /** `tool_call_id` → resolved result, for inline pairing in the row. */
  resultsByCallId: Map<string, ResolvedToolResult>;
  /** Results whose `source_call_id` doesn't match any tool call on this
   *  step. Rendered after the inline tool-call list so no data is hidden. */
  orphanResults: ResolvedToolResult[];
  /** Optional Plan 05 per-turn overlay (by turn index). Absent when the
   *  trajectory was rendered from bare ATIF (fallback). Per-call overlays
   *  live on each `ResolvedToolCall.viewEnrichment`, not here. */
  viewEnrichment?: StepEnrichment;
}

export interface ViewTrajectory {
  /** Original ATIF trajectory, untouched. */
  trajectory: Trajectory;
  agent: {
    name: string;
    version?: string;
    model?: string;
    /** "name · model" if model present, else "name". */
    displayName: string;
  };
  sessionId?: string;
  steps: ViewStep[];
  totalCostUsd?: number;
  totalSteps?: number;
}
