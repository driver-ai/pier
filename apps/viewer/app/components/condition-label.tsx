// Renders a condition's human-readable label with a hover-description tooltip
// and a distinct rails marker. All metadata is config-driven via `useConditions`
// (DEC-009); rails styling comes from the shared `conditionStyle` util so the
// treatment matches every other condition surface (Plan 03's comparison view).

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "~/components/ui/tooltip";
import { conditionLabel, useConditions } from "~/lib/conditions";
import { conditionStyle } from "~/lib/condition-style";
import { cn } from "~/lib/utils";

interface ConditionLabelProps {
  /** The condition id to render (matched against the loaded config). */
  id: string;
  className?: string;
}

export function ConditionLabel({ id, className }: ConditionLabelProps) {
  const { data: conditions } = useConditions();
  const meta = conditionLabel(conditions, id);

  // Fall back to the raw id while conditions load or when the id is unknown.
  if (!meta) {
    return <span className={cn("text-sm", className)}>{id}</span>;
  }

  const style = conditionStyle(meta.is_rail);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn("text-sm cursor-default", style.className, className)}
          data-rail={meta.is_rail || undefined}
        >
          {style.formatLabel(meta.label)}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p>{meta.description}</p>
      </TooltipContent>
    </Tooltip>
  );
}
