// Shared rails-vs-competitor styling for condition surfaces.
//
// Rails (the b0 floor and oracle ceiling — identified via `is_rail`, never
// by hardcoded ids, per DEC-009) are reference bounds, not competitors, so
// they render muted and bracketed. Competitors render normally. Keeping the
// treatment here (rather than inlined in `condition-label.tsx`) lets Plan
// 03's comparison view inherit the identical rails styling.

import type { ConditionMeta } from "./types";

/** Style tokens for a condition, keyed off whether it is a rail. */
export interface ConditionStyle {
  /** Whether this condition is a reference rail (vs. a competitor). */
  isRail: boolean;
  /** Tailwind classes for the condition's text. */
  className: string;
  /** Wrap a rail label in brackets; competitors pass through unchanged. */
  formatLabel: (label: string) => string;
}

/** Muted + bracketed treatment for rails; normal for competitors. */
export function conditionStyle(isRail: boolean): ConditionStyle {
  return {
    isRail,
    className: isRail ? "text-muted-foreground" : "",
    formatLabel: (label: string) => (isRail ? `[${label}]` : label),
  };
}

/** Convenience: derive the style straight from a condition. */
export function conditionStyleFor(condition: ConditionMeta): ConditionStyle {
  return conditionStyle(condition.is_rail);
}
