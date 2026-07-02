/**
 * Gather-only panels (Plan 06, Task 5).
 *
 * Renders the three panels of a gather trajectory's `panels` envelope:
 *   - channel-mix   (per-channel token/cost split — a stacked bar)
 *   - tiers         (context gathered by tier: file / structural / overview)
 *   - coverage / off-gold (mean gold coverage, systematic misses, off-gold reads)
 *
 * HAND-ROLLED to mirror the local `TokenBar` / `TimingBar` pattern in
 * `routes/trial.tsx` (stacked segment bar + legend + total). Only
 * `ChartToolbar` / `IndeterminateBar` are shared ui primitives; there is no
 * drop-in bar/stacked-bar/donut, so the bars are built here.
 *
 * Gather-only: when `panels` is null/undefined (consumer trajectories), the
 * component renders nothing. Every sub-field is tolerated absent.
 */
import { useState } from "react";

import { cn } from "~/lib/utils";
import type {
  ChannelMixEntry,
  CoveragePanel,
  EnrichmentPanels,
  OffGoldEntry,
  TierEntry,
  TiersPanel,
} from "./types";

/** Deterministic, design-system chart colors (cycled). */
const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

function fmtInt(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return "-";
  return Math.round(n).toLocaleString();
}

function fmtUsd(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return "-";
  return `$${n.toFixed(2)}`;
}

function fmtPct(n: number | undefined | null): string {
  if (n == null || !Number.isFinite(n)) return "-";
  return `${n.toFixed(1)}%`;
}

interface Segment {
  label: string;
  value: number;
  color: string;
  detail?: string;
}

/**
 * A single hand-rolled stacked bar with a hover tooltip and legend — the
 * `TokenBar` pattern from `trial.tsx`, generalized to arbitrary segments.
 * Applies the same min-width scaling so tiny slices stay visible.
 */
function StackedBar({ segments }: { segments: Segment[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [hoverPos, setHoverPos] = useState(0);

  const total = segments.reduce((a, s) => a + s.value, 0);

  if (total === 0) {
    return (
      <div className="space-y-2">
        <div className="h-8 bg-muted" />
        <div className="text-sm text-muted-foreground">No data</div>
      </div>
    );
  }

  const minWidth = 1;
  const rawWidths = segments.map((s) =>
    s.value > 0 ? (s.value / total) * 100 : 0
  );
  const needsMinimum = rawWidths.map((w) => w > 0 && w < minWidth);
  const extraNeeded = needsMinimum.reduce(
    (sum, needs, idx) => (needs ? sum + (minWidth - rawWidths[idx]) : sum),
    0
  );
  const largeTotal = rawWidths.reduce(
    (sum, w, idx) => (!needsMinimum[idx] && w > 0 ? sum + w : sum),
    0
  );
  const scaleFactor =
    largeTotal > 0 ? (largeTotal - extraNeeded) / largeTotal : 1;
  const adjustedWidths = rawWidths.map((w, idx) => {
    if (w === 0) return 0;
    if (needsMinimum[idx]) return minWidth;
    return w * scaleFactor;
  });

  const cumulativeWidths: number[] = [];
  let cumulative = 0;
  for (const w of adjustedWidths) {
    cumulativeWidths.push(cumulative);
    cumulative += w;
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        {hovered !== null && (
          <div
            className="absolute bottom-full mb-2 z-10 -translate-x-1/2 pointer-events-none"
            style={{ left: `${hoverPos}%` }}
          >
            <div className="bg-popover border border-border rounded-md shadow-md px-3 py-2 whitespace-nowrap">
              <div className="text-sm font-medium">{segments[hovered].label}</div>
              <div className="text-sm text-muted-foreground">
                {fmtInt(segments[hovered].value)} tokens
              </div>
              {segments[hovered].detail != null && (
                <div className="text-sm text-muted-foreground">
                  {segments[hovered].detail}
                </div>
              )}
            </div>
          </div>
        )}
        <div className="flex h-8 overflow-hidden">
          {segments.map((segment, idx) => {
            if (segment.value === 0) return null;
            const widthPercent = adjustedWidths[idx];
            const isOtherHovered = hovered !== null && hovered !== idx;
            const center = cumulativeWidths[idx] + widthPercent / 2;
            return (
              <div
                key={segment.label}
                className="transition-opacity duration-150"
                style={{
                  width: `${widthPercent}%`,
                  backgroundColor: segment.color,
                  opacity: isOtherHovered ? 0.3 : 1,
                }}
                onMouseEnter={() => {
                  setHovered(idx);
                  setHoverPos(center);
                }}
                onMouseLeave={() => setHovered(null)}
              />
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {segments.map((segment, idx) => {
          if (segment.value === 0) return null;
          return (
            <div key={segment.label} className="flex items-center gap-1.5 text-xs">
              <div
                className="w-2.5 h-2.5 rounded-sm"
                style={{ backgroundColor: segment.color }}
              />
              <span className="text-muted-foreground">
                {segment.label}
                {needsMinimum[idx] && " (scaled)"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PanelSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 border border-border p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="text-sm font-medium">{title}</h4>
        {subtitle != null && (
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        )}
      </div>
      {children}
    </section>
  );
}

function ChannelMixSection({
  channels,
  totalTokens,
  totalCostUsd,
}: {
  channels: Record<string, ChannelMixEntry>;
  totalTokens?: number | null;
  totalCostUsd?: number | null;
}) {
  const entries = Object.entries(channels).sort(
    (a, b) => (b[1].tokens ?? 0) - (a[1].tokens ?? 0)
  );
  if (entries.length === 0) {
    return <div className="text-sm text-muted-foreground">No channel data</div>;
  }
  const segments: Segment[] = entries.map(([name, e], idx) => ({
    label: name,
    value: e.tokens ?? 0,
    color: CHART_COLORS[idx % CHART_COLORS.length],
    detail: `${e.calls ?? 0} calls · ${fmtUsd(e.cost_usd)}`,
  }));
  const subtitle = [
    totalTokens != null ? `${fmtInt(totalTokens)} tok` : null,
    totalCostUsd != null ? fmtUsd(totalCostUsd) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <PanelSection title="Channel mix" subtitle={subtitle || undefined}>
      <StackedBar segments={segments} />
      <div className="mt-2 space-y-1">
        {entries.map(([name, e], idx) => (
          <div
            key={name}
            className="flex items-center justify-between gap-2 text-xs border-b border-border py-1 last:border-0"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <div
                className="w-2 h-2 rounded-sm shrink-0"
                style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }}
              />
              <span className="truncate">{name}</span>
            </div>
            <div className="flex items-center gap-3 text-muted-foreground tabular-nums shrink-0">
              <span>{e.calls ?? 0} calls</span>
              <span>{fmtInt(e.tokens)} tok</span>
              <span>{fmtPct(e.pct_tokens)}</span>
              <span>{fmtUsd(e.cost_usd)}</span>
            </div>
          </div>
        ))}
      </div>
    </PanelSection>
  );
}

function TiersSection({ tiers }: { tiers: TiersPanel }) {
  const entries = Object.entries(tiers) as Array<[string, TierEntry]>;
  const ranked = entries.sort(
    (a, b) => (b[1].pct_tokens ?? 0) - (a[1].pct_tokens ?? 0)
  );
  if (ranked.length === 0) {
    return <div className="text-sm text-muted-foreground">No tier data</div>;
  }
  const segments: Segment[] = ranked.map(([name, t], idx) => ({
    label: name,
    value: t.tokens ?? 0,
    color: CHART_COLORS[idx % CHART_COLORS.length],
    detail: `${t.count ?? 0} items`,
  }));
  return (
    <PanelSection title="Tiers">
      <StackedBar segments={segments} />
      <div className="mt-2 space-y-3">
        {ranked.map(([name, t], idx) => (
          <TierRow
            key={name}
            name={name}
            tier={t}
            color={CHART_COLORS[idx % CHART_COLORS.length]}
          />
        ))}
      </div>
    </PanelSection>
  );
}

function TierRow({
  name,
  tier,
  color,
}: {
  name: string;
  tier: TierEntry;
  color: string;
}) {
  const [open, setOpen] = useState(false);
  const items = tier.items ?? [];
  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center justify-between gap-2 py-1 text-left",
          items.length > 0 && "cursor-pointer hover:text-foreground"
        )}
        disabled={items.length === 0}
      >
        <div className="flex items-center gap-1.5 min-w-0">
          <div
            className="w-2 h-2 rounded-sm shrink-0"
            style={{ backgroundColor: color }}
          />
          <span className="font-medium">{name}</span>
          <span className="text-muted-foreground">({tier.count ?? 0})</span>
        </div>
        <div className="flex items-center gap-3 text-muted-foreground tabular-nums shrink-0">
          <span>{fmtInt(tier.tokens)} tok</span>
          <span>{fmtPct(tier.pct_tokens)}</span>
        </div>
      </button>
      {open && items.length > 0 && (
        <ul className="mt-1 ml-3.5 space-y-0.5 border-l border-border pl-3">
          {items.map((item) => (
            <li
              key={item}
              className="font-mono text-[11px] text-muted-foreground break-all"
            >
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CoverageOffGoldSection({
  coverage,
  offGold,
}: {
  coverage?: CoveragePanel | null;
  offGold?: OffGoldEntry[] | null;
}) {
  const misses = coverage?.systematic_misses ?? [];
  const off = offGold ?? [];
  const meanCov = coverage?.mean_coverage;
  return (
    <PanelSection
      title="Coverage & off-gold"
      subtitle={
        meanCov != null ? `mean coverage ${(meanCov * 100).toFixed(0)}%` : undefined
      }
    >
      {meanCov != null && (
        <div className="space-y-1">
          <div className="h-2.5 w-full overflow-hidden bg-muted">
            <div
              className="h-full"
              style={{
                width: `${Math.min(100, Math.max(0, meanCov * 100))}%`,
                backgroundColor: "var(--chart-2)",
              }}
            />
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium">
            Systematic misses
            <span className="ml-1 text-muted-foreground">({misses.length})</span>
          </div>
          {misses.length === 0 ? (
            <div className="text-xs text-muted-foreground">None</div>
          ) : (
            <ul className="space-y-0.5">
              {misses.map(([path, count]) => (
                <li
                  key={path}
                  className="flex items-center justify-between gap-2 text-[11px]"
                >
                  <span className="font-mono text-muted-foreground break-all">
                    {path}
                  </span>
                  <span className="tabular-nums text-muted-foreground shrink-0">
                    {fmtInt(count)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="mb-1 text-xs font-medium">
            Off-gold reads
            <span className="ml-1 text-muted-foreground">({off.length})</span>
          </div>
          {off.length === 0 ? (
            <div className="text-xs text-muted-foreground">None</div>
          ) : (
            <ul className="space-y-0.5">
              {off.map((entry, idx) => (
                <li
                  key={`${entry.path ?? "?"}-${idx}`}
                  className="flex items-center justify-between gap-2 text-[11px]"
                >
                  <span className="font-mono text-muted-foreground break-all">
                    {entry.path ?? "(unknown)"}
                  </span>
                  <span className="tabular-nums text-muted-foreground shrink-0">
                    {fmtInt(entry.injected_tokens)} tok
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </PanelSection>
  );
}

/**
 * Gather panels. Renders nothing for consumer trajectories (`panels` null) or
 * when there is no panel content at all. Presentational — the parent passes
 * the envelope's `panels`.
 */
export function GatherPanels({
  panels,
  className,
}: {
  panels?: EnrichmentPanels | null;
  className?: string;
}) {
  if (!panels) return null;

  const channelMix = panels.channel_mix;
  const tiers = panels.tiers;
  const coverage = panels.coverage;
  const offGold = panels.off_gold;

  const hasChannelMix =
    channelMix?.channels != null &&
    Object.keys(channelMix.channels).length > 0;
  const hasTiers = tiers != null && Object.keys(tiers).length > 0;
  const hasCoverage =
    coverage?.mean_coverage != null ||
    (coverage?.systematic_misses?.length ?? 0) > 0 ||
    (offGold?.length ?? 0) > 0;

  if (!hasChannelMix && !hasTiers && !hasCoverage) return null;

  return (
    <div className={cn("space-y-4", className)}>
      {hasChannelMix && channelMix?.channels != null && (
        <ChannelMixSection
          channels={channelMix.channels}
          totalTokens={channelMix.total_tokens}
          totalCostUsd={channelMix.total_cost_usd}
        />
      )}
      {hasTiers && tiers != null && <TiersSection tiers={tiers} />}
      {hasCoverage && (
        <CoverageOffGoldSection coverage={coverage} offGold={offGold} />
      )}
    </div>
  );
}
