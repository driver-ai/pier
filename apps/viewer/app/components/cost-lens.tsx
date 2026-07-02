// CostLens — quality-vs-cost scatter (Plan 03, Task 6).
//
// One point per condition × model: X = a precomputed cost stat, Y = quality
// (`quality.mean`). The cost axis is selectable across the three precomputed
// aggregate cost stats (`cost_gather` / `cost_consumer` / `cost_total`, default
// total). pier reads ONLY the precomputed aggregate cost stats — there is NO
// client-side roll-up from `run_records` (dry-run 03 Gap 8, forbidden).
//
// This COPIES the SVG scatter pattern from pier's bespoke
// `job-efficiency-chart.tsx` (`placeLabels` / `MarkerShape` / `familyColor` /
// log-scale axis math) into a bespoke component driven by our
// `ConditionAggregate[]`. The efficiency chart itself is NOT reusable (bound to
// `JobHeatmapData`; dry-run 03 Gap 6). Reused directly: `ChartToolbar`,
// `model-family.ts`, `Empty`, `IndeterminateBar`. Rails (b0 floor / oracle
// ceiling) render as diamond reference marks. Null cost/quality points are
// skipped — no NaN geometry (dry-run 03 Gap 7). Presents evidence only
// (DEC-010).

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import {
  MarkerShape,
  placeLabels,
  type ShapeKey,
} from "~/components/job-scatter-chart";
import {
  ChartToolbar,
  ChartToolbarSelect,
} from "~/components/ui/chart-toolbar";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "~/components/ui/empty";
import { IndeterminateBar } from "~/components/ui/indeterminate-bar";
import {
  bareModelName,
  FAMILY_CONFIG,
  FAMILY_ORDER,
  familyColor,
  getFamily,
  sortByFamilyRank,
} from "~/lib/model-family";
import type { ConditionAggregate, ConditionMeta, Stat } from "~/lib/types";
import { cn } from "~/lib/utils";

// ---------------------------------------------------------------------------
// Cost metric (X axis) — reads a precomputed aggregate cost Stat.
// ---------------------------------------------------------------------------

type CostKey = "cost_total" | "cost_gather" | "cost_consumer";

interface CostMetric {
  key: CostKey;
  label: string;
  axisLabel: string;
}

const COST_METRICS: CostMetric[] = [
  { key: "cost_total", label: "Total cost", axisLabel: "Avg total cost" },
  { key: "cost_gather", label: "Gather cost", axisLabel: "Avg gather cost" },
  {
    key: "cost_consumer",
    label: "Consumer cost",
    axisLabel: "Avg consumer cost",
  },
];

function costStat(agg: ConditionAggregate, key: CostKey): Stat | null {
  return agg[key];
}

function formatCost(value: number): string {
  if (value >= 1) return `$${value.toFixed(2)}`;
  if (value >= 0.01) return `$${value.toFixed(3)}`;
  if (value <= 0) return "$0";
  return `$${value.toPrecision(2)}`;
}

function formatPercent(v: number): string {
  return `${(v * 100).toFixed(0)}`;
}

// ---------------------------------------------------------------------------
// Point construction (one per condition × model)
// ---------------------------------------------------------------------------

interface CostPoint {
  rowKey: string;
  /** Marker label, e.g. "gpt-5.5 · oracle". */
  label: string;
  model: string;
  condition: string;
  conditionLabel: string;
  family: string;
  rankIndex: number;
  rankCount: number;
  isRail: boolean;
  /** X = cost, Y = quality. Both finite by construction. */
  x: number;
  y: number;
}

interface BuiltCost {
  points: CostPoint[];
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

function buildCost(
  aggregates: ConditionAggregate[],
  conditions: ConditionMeta[] | null | undefined,
  costKey: CostKey,
  examMode: string | null
): BuiltCost | null {
  const labelById = new Map<string, string>(
    (conditions ?? []).map((c) => [c.id, c.label])
  );
  const railById = new Map<string, boolean>(
    (conditions ?? []).map((c) => [c.id, c.is_rail])
  );

  const scoped =
    examMode == null
      ? aggregates
      : aggregates.filter((a) => a.exam_mode === examMode);

  // Group by (model, family) to derive within-family color ranks.
  type Raw = {
    model: string;
    condition: string;
    conditionLabel: string;
    isRail: boolean;
    family: string;
    x: number;
    y: number;
  };
  const raws: Raw[] = [];
  for (const agg of scoped) {
    const cost = costStat(agg, costKey);
    const x = cost?.mean;
    const y = agg.quality?.mean;
    // Skip points with null/non-finite cost or quality — no NaN geometry.
    if (x == null || !Number.isFinite(x)) continue;
    if (y == null || !Number.isFinite(y)) continue;
    raws.push({
      model: agg.model,
      condition: agg.condition,
      conditionLabel: labelById.get(agg.condition) ?? agg.condition,
      isRail: railById.get(agg.condition) ?? false,
      family: getFamily(null, agg.model),
      x,
      y,
    });
  }

  if (raws.length === 0) return null;

  // Rank each model within its family (best→worst) for color assignment; every
  // condition of a given model shares that model's color.
  const modelsByFamily = new Map<string, string[]>();
  for (const r of raws) {
    const list = modelsByFamily.get(r.family) ?? [];
    if (!list.includes(r.model)) list.push(r.model);
    modelsByFamily.set(r.family, list);
  }
  const rankOf = new Map<string, { rankIndex: number; rankCount: number }>();
  for (const [family, models] of modelsByFamily.entries()) {
    const sorted = sortByFamilyRank(models, family, (m) => bareModelName(m));
    sorted.forEach((model, i) => {
      rankOf.set(model, { rankIndex: i, rankCount: sorted.length });
    });
  }

  const points: CostPoint[] = raws.map((r) => {
    const rank = rankOf.get(r.model) ?? { rankIndex: 0, rankCount: 1 };
    return {
      rowKey: `${r.model}::${r.condition}`,
      label: `${bareModelName(r.model)} · ${r.conditionLabel}`,
      model: r.model,
      condition: r.condition,
      conditionLabel: r.conditionLabel,
      family: r.family,
      rankIndex: rank.rankIndex,
      rankCount: rank.rankCount,
      isRail: r.isRail,
      x: r.x,
      y: r.y,
    };
  });

  let xMin = Number.POSITIVE_INFINITY;
  let xMax = Number.NEGATIVE_INFINITY;
  let yMin = Number.POSITIVE_INFINITY;
  let yMax = Number.NEGATIVE_INFINITY;
  for (const p of points) {
    if (p.x < xMin) xMin = p.x;
    if (p.x > xMax) xMax = p.x;
    if (p.y < yMin) yMin = p.y;
    if (p.y > yMax) yMax = p.y;
  }
  if (!Number.isFinite(xMin)) xMin = 0;
  if (!Number.isFinite(xMax)) xMax = 1;
  if (!Number.isFinite(yMin)) yMin = 0;
  if (!Number.isFinite(yMax)) yMax = 1;

  return { points, xMin, xMax, yMin, yMax };
}

// ---------------------------------------------------------------------------
// Axis helpers (copied from the efficiency chart scale math)
// ---------------------------------------------------------------------------

type XScaleMode = "linear" | "log";

function linearTicks(min: number, max: number, count = 6): number[] {
  if (Math.abs(max - min) < 1e-9) return [min];
  return Array.from(
    { length: count },
    (_, i) => min + ((max - min) * i) / (count - 1)
  );
}

function logTicks(min: number, max: number): number[] {
  const lo = Math.log10(Math.max(min, Number.MIN_VALUE));
  const hi = Math.log10(Math.max(max, Number.MIN_VALUE));
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  const ticks: number[] = [];
  for (let p = Math.floor(lo); p <= Math.ceil(hi); p += 1) {
    for (const m of [1, 2, 5]) {
      const tick = m * 10 ** p;
      if (tick >= min * 0.999 && tick <= max * 1.001) ticks.push(tick);
    }
  }
  if (ticks.length > 8) {
    return linearTicks(lo, hi, 6).map((v) => 10 ** v);
  }
  return ticks.length > 0 ? ticks : [min, max];
}

function padDomain(min: number, max: number): [number, number] {
  if (Math.abs(max - min) < 1e-9) {
    const pad = Math.max(Math.abs(max) * 0.1, 1);
    return [min - pad, max + pad];
  }
  const pad = (max - min) * 0.08;
  return [min - pad, max + pad];
}

function buildYDomain(
  min: number,
  max: number,
  usePercent: boolean
): [number, number] {
  if (usePercent) {
    const lo = Math.max(0, Math.floor(min * 10) / 10 - 0.05);
    const hi = Math.min(1, Math.ceil(max * 10) / 10 + 0.05);
    if (hi - lo < 0.2) {
      return [Math.max(0, lo - 0.1), Math.min(1, hi + 0.1)];
    }
    return [lo, hi];
  }
  return padDomain(min, max);
}

function formatScore(v: number): string {
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const WIDTH = 900;
const MARGIN_TOP = 48;
const MARGIN_BOTTOM = 76;
const MARGIN_LEFT = 76;
const MARGIN_RIGHT = 52;
const PLOT_W = WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
const PLOT_H = 480;
const HEIGHT = MARGIN_TOP + PLOT_H + MARGIN_BOTTOM;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CostLensProps {
  aggregates: ConditionAggregate[] | undefined;
  conditions: ConditionMeta[] | null | undefined;
  /** Optional consumer-mode scope (mirrors the comparison's dimension). */
  examMode?: string | null;
  isLoading?: boolean;
  isFetching?: boolean;
}

export function CostLens({
  aggregates,
  conditions,
  examMode = null,
  isLoading,
  isFetching,
}: CostLensProps) {
  const [costKey, setCostKey] = useState<CostKey>("cost_total");
  const [xScaleMode, setXScaleMode] = useState<XScaleMode>("log");
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const metric =
    COST_METRICS.find((m) => m.key === costKey) ?? COST_METRICS[0];

  const chart = useMemo(
    () =>
      aggregates
        ? buildCost(aggregates, conditions, costKey, examMode)
        : null,
    [aggregates, conditions, costKey, examMode]
  );

  const controls = (
    <ChartToolbar
      description={
        <>
          Quality (mean score) vs{" "}
          <span className="text-foreground">
            {metric.label.toLowerCase()}
          </span>{" "}
          per condition × model. The X axis is inverted, so the{" "}
          <span className="text-foreground">top-right is most efficient</span>{" "}
          (high quality, low cost). Rails (b0 / oracle) are diamonds. Hue = model
          family.
        </>
      }
    >
      <ChartToolbarSelect
        label="Cost"
        value={costKey}
        onValueChange={(v) => setCostKey(v as CostKey)}
        options={COST_METRICS.map((m) => ({ value: m.key, label: m.label }))}
      />
      <ChartToolbarSelect
        label="X scale"
        value={xScaleMode}
        onValueChange={(v) => setXScaleMode(v as XScaleMode)}
        options={[
          { value: "log", label: "Log scale" },
          { value: "linear", label: "Linear" },
        ]}
      />
    </ChartToolbar>
  );

  if (isLoading || (!chart && isFetching)) {
    return (
      <div className="border bg-card relative min-h-80">
        {(isLoading || isFetching) && <IndeterminateBar className="-top-px" />}
      </div>
    );
  }

  if (!chart) {
    return (
      <div className="border bg-card relative">
        {controls}
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Search />
            </EmptyMedia>
            <EmptyTitle>No cost data</EmptyTitle>
            <EmptyDescription>
              No condition reports both the selected cost stat and a quality
              score. Try another cost metric.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  const { points, xMin, xMax, yMin, yMax } = chart;

  // Y axis: percent when all quality falls in the 0–1 range.
  const usePercent = yMin >= 0 && yMax <= 1;
  const [yLo, yHi] = buildYDomain(yMin, yMax, usePercent);
  const yRange = Math.max(yHi - yLo, 1e-6);

  // X axis: optionally log-scaled and always inverted (smaller cost = righter).
  const positiveXs = points.map((p) => p.x).filter((x) => x > 0);
  const positiveXMin =
    positiveXs.length > 0 ? Math.min(...positiveXs) : Number.POSITIVE_INFINITY;
  const canUseLog = Number.isFinite(positiveXMin) && xMax > 0;
  const effectiveScale: XScaleMode =
    xScaleMode === "log" && canUseLog ? "log" : "linear";
  const [linXLo, linXHi] = padDomain(xMin, xMax);
  const rawXLo =
    effectiveScale === "log"
      ? Math.max(positiveXMin, Number.MIN_VALUE)
      : linXLo;
  const rawXHi = effectiveScale === "log" ? xMax : linXHi;
  const xDomainLo = effectiveScale === "log" ? Math.log10(rawXLo) : rawXLo;
  const xDomainHi =
    effectiveScale === "log"
      ? Math.log10(Math.max(rawXHi, rawXLo * 1.001))
      : rawXHi;
  const xRange = Math.max(xDomainHi - xDomainLo, 1e-9);

  const xForValue = (v: number) => {
    const scaled =
      effectiveScale === "log" ? Math.log10(Math.max(v, rawXLo)) : v;
    const frac = (scaled - xDomainLo) / xRange;
    return MARGIN_LEFT + (1 - frac) * PLOT_W;
  };
  const yForValue = (v: number) =>
    MARGIN_TOP + (1 - (v - yLo) / yRange) * PLOT_H;

  const xTicks =
    effectiveScale === "log"
      ? logTicks(rawXLo, rawXHi)
      : linearTicks(rawXLo, rawXHi, 6);
  const yTicks = usePercent
    ? [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1].filter(
        (t) => t >= yLo - 1e-9 && t <= yHi + 1e-9
      )
    : linearTicks(yLo, yHi, 6);

  // Prioritise efficient points (high quality, low cost) for labelling.
  const placements = placeLabels(
    points,
    xForValue,
    yForValue,
    (label) => Math.max(label.length * 6.6 + 6, 18),
    14,
    {
      left: MARGIN_LEFT - 4,
      right: MARGIN_LEFT + PLOT_W + 4,
      top: MARGIN_TOP - 4,
      bottom: MARGIN_TOP + PLOT_H + 4,
    },
    (p) => p.y - (p.x - xMin) / Math.max(xMax - xMin, 1e-9)
  );

  const familyGroups = (() => {
    const map = new Map<string, CostPoint[]>();
    for (const p of points) {
      const list = map.get(p.family) ?? [];
      list.push(p);
      map.set(p.family, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => a.rankIndex - b.rankIndex || a.x - b.x);
    }
    return FAMILY_ORDER.filter((f) => map.has(f)).map((f) => ({
      family: f,
      members: map.get(f)!,
    }));
  })();

  const hovered = hoveredKey
    ? (points.find((p) => p.rowKey === hoveredKey) ?? null)
    : null;
  const hoveredColor = hovered
    ? familyColor(hovered.family, hovered.rankIndex, hovered.rankCount)
    : null;
  const hcx = hovered ? xForValue(hovered.x) : 0;
  const hcy = hovered ? yForValue(hovered.y) : 0;

  return (
    <div className="border bg-card relative">
      {isFetching && <IndeterminateBar className="-top-px" />}
      {controls}
      <div className="overflow-x-auto">
        <div className="relative mx-auto" style={{ width: WIDTH }}>
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            width={WIDTH}
            style={{ display: "block" }}
            role="img"
            aria-label={`Cost lens: quality vs ${metric.axisLabel}`}
          >
            <rect
              x={MARGIN_LEFT}
              y={MARGIN_TOP}
              width={PLOT_W}
              height={PLOT_H}
              fill="transparent"
              stroke="var(--border)"
              strokeWidth={1}
            />
            {xTicks.map((t) => {
              const x = xForValue(t);
              return (
                <g key={`xt-${t}`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={MARGIN_TOP}
                    y2={MARGIN_TOP + PLOT_H}
                    stroke="var(--border)"
                    strokeWidth={1}
                    strokeDasharray="2 4"
                    opacity={0.35}
                  />
                  <line
                    x1={x}
                    x2={x}
                    y1={MARGIN_TOP + PLOT_H}
                    y2={MARGIN_TOP + PLOT_H + 5}
                    stroke="var(--border)"
                  />
                  <text
                    x={x}
                    y={MARGIN_TOP + PLOT_H + 18}
                    textAnchor="middle"
                    fontSize={11}
                    className="fill-muted-foreground"
                  >
                    {formatCost(t)}
                  </text>
                </g>
              );
            })}
            {yTicks.map((t) => {
              const y = yForValue(t);
              return (
                <g key={`yt-${t}`}>
                  <line
                    x1={MARGIN_LEFT}
                    x2={MARGIN_LEFT + PLOT_W}
                    y1={y}
                    y2={y}
                    stroke="var(--border)"
                    strokeWidth={1}
                    strokeDasharray="2 4"
                    opacity={0.35}
                  />
                  <line
                    x1={MARGIN_LEFT - 5}
                    x2={MARGIN_LEFT}
                    y1={y}
                    y2={y}
                    stroke="var(--border)"
                  />
                  <text
                    x={MARGIN_LEFT - 8}
                    y={y + 3.5}
                    textAnchor="end"
                    fontSize={11}
                    className="fill-muted-foreground"
                  >
                    {usePercent ? formatPercent(t) : formatScore(t)}
                  </text>
                </g>
              );
            })}

            {/* Axis labels */}
            <text
              x={MARGIN_LEFT + PLOT_W / 2}
              y={HEIGHT - 30}
              textAnchor="middle"
              fontSize={12}
              className="fill-foreground"
            >
              {metric.axisLabel}
              {effectiveScale === "log" ? " (log)" : ""} — inverted
            </text>
            <text
              x={MARGIN_LEFT + PLOT_W / 2}
              y={HEIGHT - 14}
              textAnchor="middle"
              fontSize={10}
              className="fill-muted-foreground"
            >
              ← more expensive · cheaper →
            </text>
            <text
              x={22}
              y={MARGIN_TOP + PLOT_H / 2}
              textAnchor="middle"
              fontSize={12}
              transform={`rotate(-90 22 ${MARGIN_TOP + PLOT_H / 2})`}
              className="fill-foreground"
            >
              Quality{usePercent ? " (%)" : ""}
            </text>
            <text
              x={MARGIN_LEFT + PLOT_W - 6}
              y={MARGIN_TOP + 14}
              textAnchor="end"
              fontSize={10}
              className="fill-muted-foreground"
              fontStyle="italic"
            >
              most efficient ↗
            </text>

            {/* Hover crosshair */}
            {hovered && hoveredColor && (
              <g pointerEvents="none">
                <line
                  x1={hcx}
                  y1={hcy}
                  x2={hcx}
                  y2={MARGIN_TOP + PLOT_H}
                  stroke={hoveredColor}
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  opacity={0.85}
                />
                <line
                  x1={MARGIN_LEFT}
                  y1={hcy}
                  x2={hcx}
                  y2={hcy}
                  stroke={hoveredColor}
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  opacity={0.85}
                />
                <text
                  x={hcx}
                  y={MARGIN_TOP + PLOT_H + 18}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill={hoveredColor}
                  style={{
                    paintOrder: "stroke",
                    stroke: "var(--card)",
                    strokeWidth: 4,
                    strokeLinejoin: "round",
                  }}
                >
                  {formatCost(hovered.x)}
                </text>
                <text
                  x={MARGIN_LEFT - 8}
                  y={hcy + 3.5}
                  textAnchor="end"
                  fontSize={11}
                  fontWeight={600}
                  fill={hoveredColor}
                  style={{
                    paintOrder: "stroke",
                    stroke: "var(--card)",
                    strokeWidth: 4,
                    strokeLinejoin: "round",
                  }}
                >
                  {usePercent
                    ? `${formatPercent(hovered.y)}%`
                    : formatScore(hovered.y)}
                </text>
              </g>
            )}

            {/* Markers — rails as diamonds, competitors as circles; hovered
                rendered last so it wins z-order. */}
            {[...points]
              .sort((a, b) => {
                if (hoveredKey === a.rowKey) return 1;
                if (hoveredKey === b.rowKey) return -1;
                return 0;
              })
              .map((p) => {
                const cx = xForValue(p.x);
                const cy = yForValue(p.y);
                const color = familyColor(p.family, p.rankIndex, p.rankCount);
                const isHovered = hoveredKey === p.rowKey;
                const shape: ShapeKey = p.isRail ? "diamond" : "circle";
                return (
                  <g
                    key={`pt-${p.rowKey}`}
                    style={{ cursor: "pointer" }}
                    onMouseEnter={() => setHoveredKey(p.rowKey)}
                    onMouseLeave={() => setHoveredKey(null)}
                  >
                    <circle
                      cx={cx}
                      cy={cy}
                      r={14}
                      fill="transparent"
                      pointerEvents="all"
                    />
                    <MarkerShape
                      shape={shape}
                      cx={cx}
                      cy={cy}
                      r={isHovered ? 8.5 : 6}
                      fill={color}
                      opacity={p.isRail ? 0.65 : 1}
                      strokeWidth={isHovered ? 2 : 1.5}
                    />
                  </g>
                );
              })}

            {/* Inline labels */}
            {placements.map((pl) => {
              const color = familyColor(
                pl.point.family,
                pl.point.rankIndex,
                pl.point.rankCount
              );
              return (
                <g key={`lbl-${pl.point.rowKey}`} pointerEvents="none">
                  {Math.abs(pl.labelY - pl.cy) > 1.5 && (
                    <line
                      x1={pl.cx}
                      y1={pl.cy}
                      x2={pl.labelX + (pl.side === "right" ? -2 : 2)}
                      y2={pl.labelY}
                      stroke={color}
                      strokeWidth={1}
                      opacity={0.4}
                    />
                  )}
                  <text
                    x={pl.labelX}
                    y={pl.labelY + 4}
                    textAnchor={pl.side === "right" ? "start" : "end"}
                    fontSize={11}
                    fill={color}
                    style={{
                      paintOrder: "stroke",
                      stroke: "var(--background)",
                      strokeWidth: 3,
                      strokeLinejoin: "round",
                    }}
                  >
                    {pl.point.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
      <CostLegend
        familyGroups={familyGroups}
        hoveredKey={hoveredKey}
        setHovered={setHoveredKey}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function CostLegend({
  familyGroups,
  hoveredKey,
  setHovered,
}: {
  familyGroups: { family: string; members: CostPoint[] }[];
  hoveredKey: string | null;
  setHovered: (k: string | null) => void;
}) {
  return (
    <div className="border-t">
      <div className="flex flex-wrap gap-x-6 gap-y-2 px-4 py-3 text-xs">
        {familyGroups.map(({ family, members }) => (
          <div key={family} className="flex items-center gap-2">
            <span className="text-muted-foreground">
              {FAMILY_CONFIG[family]?.label ?? family}
            </span>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {members.map((m) => {
                const color = familyColor(m.family, m.rankIndex, m.rankCount);
                const isDimmed = hoveredKey !== null && hoveredKey !== m.rowKey;
                return (
                  <button
                    key={m.rowKey}
                    type="button"
                    className={cn(
                      "inline-flex items-center gap-1.5 transition-opacity",
                      isDimmed && "opacity-30"
                    )}
                    onMouseEnter={() => setHovered(m.rowKey)}
                    onMouseLeave={() => setHovered(null)}
                    title={m.label}
                  >
                    <svg width={12} height={12} viewBox="0 0 12 12">
                      <MarkerShape
                        shape={m.isRail ? "diamond" : "circle"}
                        cx={6}
                        cy={6}
                        r={4}
                        fill={color}
                        stroke="var(--background)"
                        strokeWidth={1}
                      />
                    </svg>
                    <span className="font-mono">{m.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
