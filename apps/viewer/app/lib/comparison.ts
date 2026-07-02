// Comparison data shaping (Plan 03, Task 4).
//
// Pure functions (no React, no fetching) that turn the precomputed
// `ConditionAggregate[]` into the geometry the `ConditionComparison` component
// (Task 5) renders: per-model groups of per-condition bars, ordered by the Plan
// 02 config `order`, valued for one of three views.
//
// pier does NOT re-aggregate (DEC-002/DEC-014 D4). `lift_vs_b0` and `span_pos`
// are precomputed by pier-analytics (which needs the b0/oracle cells to compute
// them), so a missing b0/oracle cell surfaces here as a `null` lift/span — which
// we mark as `isNA`. We NEVER emit NaN geometry (dry-run 03 Gap 7).

import type { ConditionAggregate, ConditionMeta, Stat } from "./types";

/** View toggle for the comparison. Default is "lift" (DEC-011). */
export type ChangeView = "absolute" | "lift" | "normalized";

export const DEFAULT_CHANGE_VIEW: ChangeView = "lift";

/** One condition's shaped bar within a model group. */
export interface ComparisonBar {
  /** Condition id (matches ConditionMeta.id / aggregate.condition). */
  condition: string;
  /** Human label from Plan 02 config; falls back to the raw id. */
  label: string;
  /**
   * The value for the active view, or `null` when unavailable (missing cell,
   * null quality/lift/span). Never NaN.
   */
  value: number | null;
  /** Confidence interval bounds for this condition (null when absent). */
  ciLow: number | null;
  ciHigh: number | null;
  /** True for the b0/oracle rails (from ConditionMeta.is_rail). */
  isRail: boolean;
  /**
   * True when there is no value to render for the active view — the component
   * shows a muted "n/a" marker instead of a bar.
   */
  isNA: boolean;
}

/** All conditions' shaped bars for a single model. */
export interface ComparisonGroup {
  model: string;
  bars: ComparisonBar[];
}

/** Shaped output the ConditionComparison component consumes. */
export interface ComparisonShape {
  view: ChangeView;
  groups: ComparisonGroup[];
}

/**
 * Pick the raw view value from an aggregate, returning `null` (never NaN) when
 * the source field is null/undefined or not finite.
 */
function viewValue(agg: ConditionAggregate, view: ChangeView): number | null {
  let raw: number | null | undefined;
  switch (view) {
    case "absolute":
      raw = agg.quality?.mean;
      break;
    case "lift":
      raw = agg.lift_vs_b0;
      break;
    case "normalized":
      raw = agg.span_pos;
      break;
  }
  if (raw == null || !Number.isFinite(raw)) return null;
  return raw;
}

/** CI bound guarded against null/NaN. */
function finiteOrNull(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null;
  return value;
}

/** Stable model ordering: first-seen order in the aggregates list. */
function modelOrder(aggregates: ConditionAggregate[]): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const agg of aggregates) {
    if (!seen.has(agg.model)) {
      seen.add(agg.model);
      order.push(agg.model);
    }
  }
  return order;
}

/**
 * Order conditions by the Plan 02 config `order` (DEC-009). When config is
 * absent, fall back to the aggregates' first-seen order — never a hardcoded id
 * list. Only conditions actually present in `aggregates` are returned.
 */
function orderConditions(
  aggregates: ConditionAggregate[],
  conditions: ConditionMeta[] | null | undefined
): string[] {
  const present = new Set(aggregates.map((a) => a.condition));
  if (conditions && conditions.length > 0) {
    const ordered = [...conditions]
      .sort((a, b) => a.order - b.order)
      .map((c) => c.id)
      .filter((id) => present.has(id));
    // Include any present conditions the config does not mention, appended in
    // first-seen order so nothing silently disappears.
    const known = new Set(ordered);
    const extras: string[] = [];
    for (const agg of aggregates) {
      if (!known.has(agg.condition) && !extras.includes(agg.condition)) {
        extras.push(agg.condition);
      }
    }
    return [...ordered, ...extras];
  }
  const order: string[] = [];
  for (const agg of aggregates) {
    if (!order.includes(agg.condition)) order.push(agg.condition);
  }
  return order;
}

/**
 * Shape `ConditionAggregate[]` into per-model comparison groups for the given
 * view (default "lift"), ordered by the Plan 02 config.
 *
 * Nulls are handled explicitly: a missing aggregate cell, a null
 * `quality`/`lift_vs_b0`/`span_pos`, or a missing b0/oracle rail (which yields a
 * null lift/span upstream) all produce a bar with `value: null` and
 * `isNA: true` — never NaN geometry (dry-run 03 Gap 7).
 */
export function shapeComparison(
  aggregates: ConditionAggregate[],
  conditions: ConditionMeta[] | null | undefined,
  view: ChangeView = DEFAULT_CHANGE_VIEW,
  examMode?: string
): ComparisonShape {
  const scoped =
    examMode == null
      ? aggregates
      : aggregates.filter((a) => a.exam_mode === examMode);

  const conditionIds = orderConditions(scoped, conditions);
  const labelById = new Map<string, string>(
    (conditions ?? []).map((c) => [c.id, c.label])
  );
  const railById = new Map<string, boolean>(
    (conditions ?? []).map((c) => [c.id, c.is_rail])
  );

  const groups: ComparisonGroup[] = [];
  for (const model of modelOrder(scoped)) {
    // Index this model's aggregates by condition. If duplicates exist (should
    // not, given the aggregate key), the first wins deterministically.
    const byCondition = new Map<string, ConditionAggregate>();
    for (const agg of scoped) {
      if (agg.model === model && !byCondition.has(agg.condition)) {
        byCondition.set(agg.condition, agg);
      }
    }

    const bars: ComparisonBar[] = conditionIds.map((condition) => {
      const agg = byCondition.get(condition);
      const label = labelById.get(condition) ?? condition;
      const isRail = railById.get(condition) ?? false;
      if (!agg) {
        // Missing cell for this (model, condition) → n/a marker, no geometry.
        return {
          condition,
          label,
          value: null,
          ciLow: null,
          ciHigh: null,
          isRail,
          isNA: true,
        };
      }
      const value = viewValue(agg, view);
      return {
        condition,
        label,
        value,
        ciLow: finiteOrNull(agg.ci_low),
        ciHigh: finiteOrNull(agg.ci_high),
        isRail,
        isNA: value === null,
      };
    });

    groups.push({ model, bars });
  }

  return { view, groups };
}

/** The exam modes present in the aggregates, in first-seen order. */
export function examModes(aggregates: ConditionAggregate[]): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const agg of aggregates) {
    if (!seen.has(agg.exam_mode)) {
      seen.add(agg.exam_mode);
      order.push(agg.exam_mode);
    }
  }
  return order;
}

/** Re-export for consumers that read the nested cost Stat directly. */
export type { Stat };
