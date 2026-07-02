// ConditionComparison — the evidence dashboard's lead element (Plan 03, Task 5).
//
// A purpose-built grouped bar chart: one group per model, one bar per condition
// within a group, ordered by the Plan 02 config. The default view is "lift"
// (change vs the no-context baseline; DEC-011); the toggle switches to absolute
// quality or normalized (b0→oracle) span position. Rails (b0 floor / oracle
// ceiling) are marked via the shared `condition-style` treatment. Every bar
// carries its CI as an error bar. `isNA` / `value === null` bars render a muted
// "n/a" marker — NEVER NaN geometry (dry-run 03 Gap 7).
//
// This COPIES the SVG/scale/label conventions of pier's bespoke charts
// (`job-efficiency-chart.tsx`) rather than reusing them (those are bound to
// `JobHeatmapData`; dry-run 03 Gap 6). It reuses only the data-agnostic
// primitives: `ChartToolbar`, `model-family.ts` colors, `Empty`,
// `IndeterminateBar`. Presents evidence only — no stated conclusions (DEC-010).

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

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
  type ChangeView,
  DEFAULT_CHANGE_VIEW,
  examModes,
  shapeComparison,
  type ComparisonBar,
} from "~/lib/comparison";
import { conditionStyle } from "~/lib/condition-style";
import { bareModelName, familyColor, getFamily } from "~/lib/model-family";
import type { ConditionAggregate, ConditionMeta } from "~/lib/types";
import { cn } from "~/lib/utils";

// ---------------------------------------------------------------------------
// View metadata
// ---------------------------------------------------------------------------

interface ViewMeta {
  key: ChangeView;
  label: string;
  description: string;
  /** Values are in the 0–1 range (render as percent). */
  isFraction: boolean;
  /** Baseline value on the axis (bars grow away from it). */
  baseline: number;
  format: (v: number) => string;
}

function formatPercent(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function formatSignedPercent(v: number): string {
  const pct = v * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(0)}%`;
}

const VIEW_META: Record<ChangeView, ViewMeta> = {
  absolute: {
    key: "absolute",
    label: "Absolute",
    description: "absolute quality (mean score) per condition",
    isFraction: true,
    baseline: 0,
    format: formatPercent,
  },
  lift: {
    key: "lift",
    label: "Lift vs b0",
    description: "change in quality vs the no-context baseline (b0)",
    isFraction: true,
    baseline: 0,
    format: formatSignedPercent,
  },
  normalized: {
    key: "normalized",
    label: "Normalized",
    description: "position on the b0 (floor) → oracle (ceiling) span",
    isFraction: true,
    baseline: 0,
    format: formatPercent,
  },
};

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const WIDTH = 900;
const MARGIN_TOP = 40;
const MARGIN_BOTTOM = 96;
const MARGIN_LEFT = 76;
const MARGIN_RIGHT = 24;
const PLOT_W = WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
const GROUP_GAP = 28;
const BAR_GAP = 6;
const ROW_H = 200;

// ---------------------------------------------------------------------------
// Domain
// ---------------------------------------------------------------------------

interface Domain {
  lo: number;
  hi: number;
}

/**
 * Compute a symmetric-friendly value domain across every finite bar value and
 * CI bound, always including the view baseline so bars have a common origin.
 * Never produces a degenerate (zero-width) range.
 */
function computeDomain(bars: ComparisonBar[], baseline: number): Domain {
  let lo = baseline;
  let hi = baseline;
  for (const bar of bars) {
    for (const v of [bar.value, bar.ciLow, bar.ciHigh]) {
      if (v == null || !Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (hi - lo < 1e-9) {
    lo -= 0.1;
    hi += 0.1;
  }
  const pad = (hi - lo) * 0.08;
  return { lo: lo - pad, hi: hi + pad };
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ConditionComparisonProps {
  /** Precomputed aggregates (pier does not re-aggregate). */
  aggregates: ConditionAggregate[] | undefined;
  /** Plan 02 condition config for labels + rails ordering. */
  conditions: ConditionMeta[] | null | undefined;
  /**
   * Optional controlled consumer (exam) mode. When provided (together with
   * `onExamModeChange`), the selector is driven by the parent so the comparison
   * and the cost lens stay locked to the SAME consumer mode (DEC-012). When
   * omitted, the component owns the selection internally (standalone fallback).
   */
  examMode?: string | null;
  onExamModeChange?: (mode: string) => void;
  isLoading?: boolean;
  isFetching?: boolean;
}

/**
 * The lead comparison view. `shapeComparison` is called here (the presentational
 * component owns shaping) so the route only supplies raw aggregates + config.
 */
export function ConditionComparison({
  aggregates,
  conditions,
  examMode: controlledExamMode,
  onExamModeChange,
  isLoading,
  isFetching,
}: ConditionComparisonProps) {
  const [view, setView] = useState<ChangeView>(DEFAULT_CHANGE_VIEW);
  const [uncontrolledExamMode, setUncontrolledExamMode] = useState<
    string | null
  >(null);
  const [hovered, setHovered] = useState<string | null>(null);

  // Controlled when the parent supplies both the value and a change handler,
  // else the component owns the selection (standalone fallback).
  const isControlled =
    controlledExamMode !== undefined && onExamModeChange !== undefined;
  const examMode = isControlled ? controlledExamMode : uncontrolledExamMode;
  const setExamMode = isControlled ? onExamModeChange : setUncontrolledExamMode;

  const modes = useMemo(
    () => examModes(aggregates ?? []),
    [aggregates]
  );

  // Resolve the active exam mode: the explicit selection if still present, else
  // the first available (folds consumer mode in as a dimension; DEC-012).
  const activeMode =
    examMode && modes.includes(examMode) ? examMode : (modes[0] ?? null);

  const shape = useMemo(() => {
    if (!aggregates || aggregates.length === 0) return null;
    return shapeComparison(
      aggregates,
      conditions,
      view,
      activeMode ?? undefined
    );
  }, [aggregates, conditions, view, activeMode]);

  const viewMeta = VIEW_META[view];

  const controls = (
    <ChartToolbar
      description={
        <>
          Each bar is one condition&rsquo;s{" "}
          <span className="text-foreground">{viewMeta.description}</span>,
          grouped per model. Rails (the b0 floor and oracle ceiling) are shown
          bracketed and muted; the whiskers are the confidence interval. Hue =
          model family.
        </>
      }
    >
      <ChartToolbarSelect
        label="View"
        value={view}
        onValueChange={(v) => setView(v as ChangeView)}
        options={[
          { value: "absolute", label: VIEW_META.absolute.label },
          { value: "lift", label: VIEW_META.lift.label },
          { value: "normalized", label: VIEW_META.normalized.label },
        ]}
      />
      {modes.length > 0 && (
        <ChartToolbarSelect
          label="Consumer mode"
          value={activeMode ?? undefined}
          onValueChange={(v) => setExamMode(v)}
          options={modes.map((m) => ({ value: m, label: m }))}
        />
      )}
    </ChartToolbar>
  );

  if (isLoading || (!shape && isFetching)) {
    return (
      <div className="border bg-card relative min-h-80">
        {(isLoading || isFetching) && <IndeterminateBar className="-top-px" />}
      </div>
    );
  }

  if (!shape || shape.groups.length === 0) {
    return (
      <div className="border bg-card relative">
        {controls}
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Search />
            </EmptyMedia>
            <EmptyTitle>No condition aggregates</EmptyTitle>
            <EmptyDescription>
              This run has no condition aggregates to compare. The evidence
              sidecar may be absent, or the selected consumer mode has no data.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    );
  }

  return (
    <div className="border bg-card relative">
      {isFetching && <IndeterminateBar className="-top-px" />}
      {controls}
      <div className="divide-y">
        {shape.groups.map((group) => (
          <ModelRow
            key={group.model}
            model={group.model}
            bars={group.bars}
            viewMeta={viewMeta}
            hovered={hovered}
            setHovered={setHovered}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One model's row of condition bars
// ---------------------------------------------------------------------------

function ModelRow({
  model,
  bars,
  viewMeta,
  hovered,
  setHovered,
}: {
  model: string;
  bars: ComparisonBar[];
  viewMeta: ViewMeta;
  hovered: string | null;
  setHovered: (k: string | null) => void;
}) {
  const bare = bareModelName(model);
  const family = getFamily(null, model);
  const color = familyColor(family, 0, 1);

  const domain = useMemo(
    () => computeDomain(bars, viewMeta.baseline),
    [bars, viewMeta.baseline]
  );
  const range = Math.max(domain.hi - domain.lo, 1e-6);

  const n = bars.length;
  const slot = n > 0 ? PLOT_W / n : PLOT_W;
  const barW = Math.max(slot - BAR_GAP, 4);

  const plotTop = MARGIN_TOP;
  const plotBottom = plotTop + ROW_H;
  const yForValue = (v: number) =>
    plotTop + (1 - (v - domain.lo) / range) * ROW_H;
  const baselineY = yForValue(viewMeta.baseline);

  const height = MARGIN_TOP + ROW_H + MARGIN_BOTTOM;

  // Y axis ticks: a handful across the domain.
  const yTicks = Array.from(
    { length: 5 },
    (_, i) => domain.lo + (range * i) / 4
  );

  return (
    <div>
      <div className="px-4 pt-3 pb-1">
        <span className="font-mono text-sm" style={{ color }}>
          {bare}
        </span>
      </div>
      <div className="overflow-x-auto">
        <div className="relative mx-auto" style={{ width: WIDTH }}>
          <svg
            viewBox={`0 0 ${WIDTH} ${height}`}
            width={WIDTH}
            style={{ display: "block" }}
            role="img"
            aria-label={`${bare}: ${viewMeta.label} per condition`}
          >
            {/* Y gridlines + ticks */}
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
                  <text
                    x={MARGIN_LEFT - 8}
                    y={y + 3.5}
                    textAnchor="end"
                    fontSize={11}
                    className="fill-muted-foreground"
                  >
                    {viewMeta.format(t)}
                  </text>
                </g>
              );
            })}

            {/* Baseline (origin) line */}
            <line
              x1={MARGIN_LEFT}
              x2={MARGIN_LEFT + PLOT_W}
              y1={baselineY}
              y2={baselineY}
              stroke="var(--border)"
              strokeWidth={1.5}
            />

            {bars.map((bar, i) => {
              const cx = MARGIN_LEFT + i * slot + slot / 2;
              const barX = cx - barW / 2;
              const style = conditionStyle(bar.isRail);
              const isHovered = hovered === `${model}::${bar.condition}`;

              // n/a — muted marker at the baseline, NEVER NaN geometry.
              if (bar.isNA || bar.value == null) {
                return (
                  <g
                    key={bar.condition}
                    onMouseEnter={() =>
                      setHovered(`${model}::${bar.condition}`)
                    }
                    onMouseLeave={() => setHovered(null)}
                  >
                    <rect
                      x={barX}
                      y={plotTop}
                      width={barW}
                      height={ROW_H}
                      fill="transparent"
                      pointerEvents="all"
                    />
                    <text
                      x={cx}
                      y={baselineY - 6}
                      textAnchor="middle"
                      fontSize={11}
                      className="fill-muted-foreground"
                      fontStyle="italic"
                    >
                      n/a
                    </text>
                    <ConditionTick
                      cx={cx}
                      y={plotBottom}
                      label={bar.label}
                      style={style}
                    />
                  </g>
                );
              }

              const valueY = yForValue(bar.value);
              const barTop = Math.min(valueY, baselineY);
              const barHeight = Math.abs(valueY - baselineY);
              const fill = bar.isRail ? "var(--muted-foreground)" : color;
              const opacity = bar.isRail ? 0.5 : 1;
              const hasCI = bar.ciLow != null && bar.ciHigh != null;

              return (
                <g
                  key={bar.condition}
                  onMouseEnter={() => setHovered(`${model}::${bar.condition}`)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <rect
                    x={barX}
                    y={barTop}
                    width={barW}
                    height={Math.max(barHeight, 1)}
                    fill={fill}
                    opacity={isHovered ? Math.min(opacity + 0.3, 1) : opacity}
                    rx={1}
                  />

                  {/* CI whiskers */}
                  {hasCI && (
                    <g stroke="var(--foreground)" strokeWidth={1} opacity={0.7}>
                      <line
                        x1={cx}
                        x2={cx}
                        y1={yForValue(bar.ciLow!)}
                        y2={yForValue(bar.ciHigh!)}
                      />
                      <line
                        x1={cx - 4}
                        x2={cx + 4}
                        y1={yForValue(bar.ciHigh!)}
                        y2={yForValue(bar.ciHigh!)}
                      />
                      <line
                        x1={cx - 4}
                        x2={cx + 4}
                        y1={yForValue(bar.ciLow!)}
                        y2={yForValue(bar.ciLow!)}
                      />
                    </g>
                  )}

                  {/* Value label */}
                  <text
                    x={cx}
                    y={(valueY <= baselineY ? valueY - 5 : valueY + 13)}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={isHovered ? 600 : 400}
                    className="fill-foreground"
                    style={{
                      paintOrder: "stroke",
                      stroke: "var(--card)",
                      strokeWidth: 3,
                      strokeLinejoin: "round",
                    }}
                  >
                    {viewMeta.format(bar.value)}
                  </text>

                  <ConditionTick
                    cx={cx}
                    y={plotBottom}
                    label={bar.label}
                    style={style}
                  />
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// X-axis condition tick label (rails bracketed + muted via condition-style)
// ---------------------------------------------------------------------------

function ConditionTick({
  cx,
  y,
  label,
  style,
}: {
  cx: number;
  y: number;
  label: string;
  style: { isRail: boolean; formatLabel: (label: string) => string };
}) {
  return (
    <text
      x={cx}
      y={y + 16}
      textAnchor="middle"
      fontSize={11}
      className={cn(
        style.isRail ? "fill-muted-foreground" : "fill-foreground"
      )}
    >
      {style.formatLabel(label)}
    </text>
  );
}
