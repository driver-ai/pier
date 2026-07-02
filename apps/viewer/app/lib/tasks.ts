// Task-drill data shaping (Plan 04, Task 3).
//
// Pure functions (no React, no fetching, no input mutation) that turn the served
// `RunRecord[]` (Plan 01 `/api/run-records`) into the per-item task rows the
// `TaskList` component (Task 4) renders. Scoped to a clicked comparison cell's
// `{model, examMode}`; the clicked condition is a highlight, not a filter
// (DEC-014 D2, dry-run 04 MEDIUM 1).
//
// This module is the authoritative spec for the shaping behavior — no TS unit
// runner is wired in this app, so `bun run typecheck` + the Task 6 render smoke
// are the gates. The behavior encoded here mirrors the Plan 04 "Disagreement —
// precise definition" section exactly.

import type { ConditionMeta, RunRecord } from "./types";

/** One shaped task row: an item's per-condition scores + drill target. */
export type TaskRow = {
  /** The grouping key — the benchmark item this row summarizes. */
  itemId: string;
  /**
   * Normalized display question (DEC-014 D3) from any sibling record's
   * `forensics.display.question`; `null` when no sibling has forensics
   * (TaskList renders "—").
   */
  question: string | null;
  /**
   * Canonical `record_id` (DEC-014 D2) of a deterministic representative record
   * for this row → the Plan 06 trace view. Always a real id from the group.
   */
  recordId: string;
  /**
   * Per-condition mean score keyed by condition id, ordered per the Plan 02
   * config `order` (first-seen fallback when `conditions` is null). A condition
   * with only null seed scores maps to `null`.
   */
  scores: Record<string, number | null>;
  /**
   * `max − min` over the NON-RAIL conditions' mean scores (b0/oracle excluded),
   * ignoring conditions with a null score. `0` when fewer than 2 non-rail
   * conditions have a score.
   */
  disagreement: number;
};

/** Scope selector carried from the clicked comparison cell. */
export interface TaskScope {
  model: string;
  examMode: string;
}

/** Mean over finite numbers; `null` when there are none. */
function meanOrNull(values: number[]): number | null {
  if (values.length === 0) return null;
  let sum = 0;
  for (const v of values) sum += v;
  return sum / values.length;
}

/**
 * Order condition ids by the Plan 02 config `order` (DEC-009), restricted to the
 * ids actually present in this scoped record set. When `conditions` is null/empty
 * fall back to first-seen order — never a hardcoded id list. Present ids the
 * config does not mention are appended in first-seen order so nothing vanishes.
 */
function orderConditions(
  records: RunRecord[],
  conditions: ConditionMeta[] | null
): string[] {
  const firstSeen: string[] = [];
  for (const r of records) {
    if (!firstSeen.includes(r.condition)) firstSeen.push(r.condition);
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

/**
 * Shape scoped run records into per-item task rows.
 *
 * - Filters to `f.model` && `f.examMode`, groups by `item_id`.
 * - Per-condition score = mean over seeds, ignoring null scores (all-null → null).
 * - `scores` keyed by condition id, ordered per the Plan 02 config `order`
 *   (first-seen fallback when `conditions` is null).
 * - Disagreement = `max − min` over non-rail conditions' means only (b0/oracle
 *   excluded), excluding null-scored conditions; `0` when < 2 remain.
 * - `question` = a sibling record's `forensics.display.question` (prefer the
 *   highlighted condition's record when `highlightCondition` is given); `null`
 *   when none has forensics.
 * - `recordId` = a deterministic representative: prefer the highlight condition's
 *   record, else the first record by condition `order`, else the first record.
 * - Rows sorted by disagreement DESC, then `item_id` ASC (stable/deterministic).
 * - Pure: inputs are not mutated; empty input → `[]`.
 */
export function taskRowsFor(
  records: RunRecord[],
  f: TaskScope,
  conditions: ConditionMeta[] | null,
  highlightCondition?: string
): TaskRow[] {
  const scoped = records.filter(
    (r) => r.model === f.model && r.exam_mode === f.examMode
  );
  if (scoped.length === 0) return [];

  const conditionOrder = orderConditions(scoped, conditions);
  // Rank a condition id by config order for deterministic representative picks.
  const orderRank = new Map<string, number>();
  conditionOrder.forEach((id, i) => orderRank.set(id, i));
  const railById = new Map<string, boolean>(
    (conditions ?? []).map((c) => [c.id, c.is_rail])
  );

  // Group by item, preserving first-seen item order for stable grouping.
  const groups = new Map<string, RunRecord[]>();
  for (const r of scoped) {
    const g = groups.get(r.item_id);
    if (g) g.push(r);
    else groups.set(r.item_id, [r]);
  }

  const rows: TaskRow[] = [];
  for (const [itemId, group] of groups) {
    // Per-condition seed-mean scores.
    const seedScores = new Map<string, number[]>();
    for (const r of group) {
      if (r.score == null || !Number.isFinite(r.score)) continue;
      const arr = seedScores.get(r.condition);
      if (arr) arr.push(r.score);
      else seedScores.set(r.condition, [r.score]);
    }

    // `scores` keyed by condition id, ordered per config; every ordered
    // condition present in the group is emitted (null when only-null seeds).
    const scores: Record<string, number | null> = {};
    const meanByCondition = new Map<string, number | null>();
    const conditionsInGroup = new Set(group.map((r) => r.condition));
    for (const cid of conditionOrder) {
      if (!conditionsInGroup.has(cid)) continue;
      const mean = meanOrNull(seedScores.get(cid) ?? []);
      scores[cid] = mean;
      meanByCondition.set(cid, mean);
    }

    // Disagreement over non-rail conditions with a non-null mean.
    const nonRailMeans: number[] = [];
    for (const [cid, mean] of meanByCondition) {
      if (mean == null) continue;
      if (railById.get(cid) === true) continue;
      nonRailMeans.push(mean);
    }
    const disagreement =
      nonRailMeans.length < 2
        ? 0
        : Math.max(...nonRailMeans) - Math.min(...nonRailMeans);

    // Representative record: prefer the highlight condition's record, else the
    // first by condition order, else the first record in the group.
    const representative = pickRepresentative(
      group,
      orderRank,
      highlightCondition
    );

    // Question: prefer the highlight condition's forensics, else any sibling's.
    const question = pickQuestion(group, highlightCondition);

    rows.push({
      itemId,
      question,
      recordId: representative.record_id,
      scores,
      disagreement,
    });
  }

  // Sort: disagreement DESC, then item_id ASC (deterministic tie-break).
  rows.sort((a, b) => {
    if (b.disagreement !== a.disagreement) {
      return b.disagreement - a.disagreement;
    }
    return a.itemId < b.itemId ? -1 : a.itemId > b.itemId ? 1 : 0;
  });

  return rows;
}

/**
 * Deterministic representative record for a row's trace link. Prefers a record
 * matching `highlightCondition`; else the record whose condition ranks first in
 * config order (ties broken by lowest `record_id`); else the first record.
 */
function pickRepresentative(
  group: RunRecord[],
  orderRank: Map<string, number>,
  highlightCondition?: string
): RunRecord {
  if (highlightCondition) {
    const hit = group
      .filter((r) => r.condition === highlightCondition)
      .sort((a, b) => (a.record_id < b.record_id ? -1 : 1))[0];
    if (hit) return hit;
  }
  const RANK_MAX = Number.MAX_SAFE_INTEGER;
  let best = group[0];
  let bestRank = orderRank.get(best.condition) ?? RANK_MAX;
  for (const r of group) {
    const rank = orderRank.get(r.condition) ?? RANK_MAX;
    if (rank < bestRank || (rank === bestRank && r.record_id < best.record_id)) {
      best = r;
      bestRank = rank;
    }
  }
  return best;
}

/**
 * A sibling record's normalized display question. Prefers the highlight
 * condition's record when it has forensics; else any sibling with forensics;
 * `null` when none has forensics.
 */
function pickQuestion(
  group: RunRecord[],
  highlightCondition?: string
): string | null {
  if (highlightCondition) {
    const hit = group.find(
      (r) =>
        r.condition === highlightCondition && r.forensics?.display?.question
    );
    if (hit?.forensics?.display?.question) {
      return hit.forensics.display.question;
    }
  }
  for (const r of group) {
    const q = r.forensics?.display?.question;
    if (q) return q;
  }
  return null;
}
