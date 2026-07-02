// The Method page explains how the experiment is run: the conditions under
// test (config-driven via `useConditions`, DEC-009), the two consumer modes,
// the models swept (read from the run data, not hardcoded), the exam types the
// grader supports, and how abstentions are handled. Non-condition/model prose
// is literal (easy to edit later).

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { ConditionLabel } from "~/components/condition-label";
import { useConditions } from "~/lib/conditions";
import { fetchConditionAggregates } from "~/lib/api";

interface MethodSectionProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

function MethodSection({ title, description, children }: MethodSectionProps) {
  return (
    <section className="border-t border-border py-8">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="md:col-span-1">
          <h2 className="text-lg font-mono tracking-tight">{title}</h2>
          {description ? (
            <p className="mt-2 text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="md:col-span-3">{children}</div>
      </div>
    </section>
  );
}

interface TermProps {
  term: React.ReactNode;
  children: React.ReactNode;
}

function Term({ term, children }: TermProps) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-sm font-medium">{term}</dt>
      <dd className="text-sm text-muted-foreground">{children}</dd>
    </div>
  );
}

// Consumer modes — literal prose (see file header). Not config-driven.
const CONSUMER_MODES = [
  {
    id: "sealed",
    label: "Sealed",
    description:
      "The model answers the exam from a frozen context nugget with no further gathering (pure seal).",
  },
  {
    id: "pts",
    label: "Prepare-then-seal (pts)",
    description:
      "A question-blind citation-following pass enriches the frozen notes first, then the sealed exam runs against them.",
  },
];

// Exam types the grader supports — literal prose.
const EXAM_TYPES = [
  "mcq",
  "cloze",
  "claim",
  "rubric",
  "exhaustiveness",
  "elicitation",
];

export default function Method() {
  const { data: conditions, isPending } = useConditions();

  // Models are read from the run data (the distinct model ids in the
  // aggregates), not hardcoded — so the Method page always reflects the
  // actual sweep. Shares the ["conditionAggregates"] query cache with /evidence.
  const { data: aggregates, isPending: modelsPending } = useQuery({
    queryKey: ["conditionAggregates"],
    queryFn: fetchConditionAggregates,
    staleTime: Infinity,
  });

  const models = useMemo(
    () =>
      aggregates
        ? [...new Set(aggregates.map((a) => a.model))].sort()
        : [],
    [aggregates]
  );

  // Sort a copy by `order` (config-driven); never mutate the query cache.
  const sortedConditions = useMemo(
    () =>
      conditions ? [...conditions].sort((a, b) => a.order - b.order) : null,
    [conditions]
  );

  return (
    <div className="max-w-5xl">
      <div className="mb-8">
        <h1 className="text-4xl font-normal tracking-tighter font-mono">
          Method
        </h1>
        <p className="mt-4 text-sm text-muted-foreground">
          How the experiment is run.
        </p>
      </div>

      <MethodSection
        title="Conditions"
        description="What each trial is given as context before the exam. Rails are reference bounds, not competitors."
      >
        {isPending ? (
          <p className="text-sm text-muted-foreground">Loading conditions…</p>
        ) : sortedConditions && sortedConditions.length > 0 ? (
          <dl className="flex flex-col gap-4">
            {sortedConditions.map((condition) => (
              <Term
                key={condition.id}
                term={<ConditionLabel id={condition.id} />}
              >
                {condition.description}
              </Term>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            Condition metadata is unavailable for this run.
          </p>
        )}
      </MethodSection>

      <MethodSection
        title="Consumer modes"
        description="How the model consumes its context when taking the exam."
      >
        <dl className="flex flex-col gap-4">
          {CONSUMER_MODES.map((mode) => (
            <Term key={mode.id} term={mode.label}>
              {mode.description}
            </Term>
          ))}
        </dl>
      </MethodSection>

      <MethodSection
        title="Models"
        description="The models swept in this run, read from the run data."
      >
        {modelsPending ? (
          <p className="text-sm text-muted-foreground">Loading models…</p>
        ) : models.length > 0 ? (
          <ul className="flex flex-col gap-1 text-sm font-mono">
            {models.map((model) => (
              <li key={model}>{model}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Model list is unavailable for this run.
          </p>
        )}
      </MethodSection>

      <MethodSection
        title="Exam types"
        description="The formats the grader supports."
      >
        <ul className="flex flex-col gap-1 text-sm font-mono">
          {EXAM_TYPES.map((examType) => (
            <li key={examType}>{examType}</li>
          ))}
        </ul>
      </MethodSection>

      <MethodSection title="Abstention">
        <p className="text-sm text-muted-foreground">
          A model may decline to answer when it lacks sufficient grounding.
          Abstentions are tracked separately and are not scored as wrong
          answers.
        </p>
      </MethodSection>
    </div>
  );
}
