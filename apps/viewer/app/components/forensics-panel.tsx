/**
 * ForensicsPanel (Plan 06, Task 7).
 *
 * Presentational grader-forensics display, driven by a `RunRecord` the parent
 * already fetched via `fetchRunRecords` (no dedicated backend endpoint — this
 * reuses `/api/run-records`).
 *
 * Renders the normalized `forensics.display` (question · answer · expected ·
 * pass/fail), then the typed `payload` per `forensics.exam_type`:
 *   - mcq   → the options list, gold option marked
 *   - cloze → gold + accept_set
 *   - claim → gold_verdict + correction
 *
 * This is additive to pier's existing `VerifierOutputViewer` / `RewardDetailsViewer`
 * — it does NOT duplicate their verdict rendering.
 *
 * `passed` is boolean upstream (score >= 1.0). A partial or abstained case
 * reads as NOT passed — never "ungraded". We surface an explicit
 * Abstained / Incorrect / Passed state.
 */
import { Badge } from "~/components/ui/badge";
import { cn } from "~/lib/utils";
import type { Forensics, RunRecord } from "~/lib/types";

// ---------------------------------------------------------------------------
// Typed payload shapes (narrowed from Forensics.payload: Record<string, unknown>)
// ---------------------------------------------------------------------------

interface McqOption {
  content?: string;
  is_gold?: boolean;
  is_abstention?: boolean;
  distractor_origin?: string;
}
interface McqPayload {
  question?: string;
  options?: McqOption[];
}
interface ClozePayload {
  question?: string;
  gold?: string;
  accept_set?: string[];
}
interface ClaimPayload {
  question?: string;
  gold_verdict?: boolean;
  correction?: string | null;
}

/** Parsed structure of a claim's `display.answer` (a JSON-encoded string). */
interface ClaimAnswer {
  verdict?: boolean;
  correction?: string | null;
  confidence?: string;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

/**
 * `display.answer` for mcq/claim is a JSON-encoded string; for cloze it is
 * plain text. Best-effort parse — returns the parsed object or null (raw).
 */
function tryParseJson(s: string | null | undefined): Record<string, unknown> | null {
  if (!s) return null;
  const trimmed = s.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------

type GradeState = "passed" | "abstained" | "incorrect" | "unknown";

function gradeState(record: RunRecord, display: { passed: boolean | null }): GradeState {
  if (record.abstained) return "abstained";
  if (display.passed === true) return "passed";
  if (display.passed === false) return "incorrect";
  return "unknown";
}

function GradeBadge({ state }: { state: GradeState }) {
  switch (state) {
    case "passed":
      return <Badge className="bg-emerald-600 text-white">Passed</Badge>;
    case "abstained":
      return (
        <Badge variant="outline" className="text-amber-600 border-amber-600">
          Abstained
        </Badge>
      );
    case "incorrect":
      return <Badge variant="destructive">Incorrect</Badge>;
    default:
      return <Badge variant="secondary">Ungraded</Badge>;
  }
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3 border border-border p-4">
      <h4 className="text-sm font-medium">{title}</h4>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Answer rendering (claim answer may be JSON-encoded)
// ---------------------------------------------------------------------------

function AnswerBlock({
  answer,
  examType,
}: {
  answer: string | null;
  examType: string | null;
}) {
  if (answer == null || answer === "") {
    return <span className="text-muted-foreground">—</span>;
  }

  // Claim answers (and mcq) may be a JSON-encoded string. Attempt structured
  // render; fall back to raw text otherwise.
  if (examType === "claim") {
    const parsed = tryParseJson(answer) as ClaimAnswer | null;
    if (parsed != null) {
      const verdict = parsed.verdict;
      return (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">verdict:</span>
            <Badge variant={verdict ? "default" : "secondary"}>
              {verdict === true ? "true" : verdict === false ? "false" : "—"}
            </Badge>
            {parsed.confidence != null && (
              <span className="text-xs text-muted-foreground">
                confidence: {parsed.confidence}
              </span>
            )}
          </div>
          {parsed.correction != null && parsed.correction !== "" && (
            <div>
              <span className="text-muted-foreground">correction: </span>
              {parsed.correction}
            </div>
          )}
        </div>
      );
    }
  }

  if (examType === "mcq") {
    const parsed = tryParseJson(answer);
    if (parsed != null) {
      const choice = parsed.choice;
      const rationale = parsed.rationale;
      const confidence = parsed.confidence;
      return (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">choice:</span>
            <Badge variant="secondary">{String(choice ?? "—")}</Badge>
            {confidence != null && (
              <span className="text-xs text-muted-foreground">
                confidence: {String(confidence)}
              </span>
            )}
          </div>
          {rationale != null && rationale !== "" && (
            <div className="text-muted-foreground">{String(rationale)}</div>
          )}
        </div>
      );
    }
  }

  return <span className="whitespace-pre-wrap">{answer}</span>;
}

// ---------------------------------------------------------------------------
// Per-exam-type payload sections
// ---------------------------------------------------------------------------

function McqPayloadSection({ payload }: { payload: McqPayload }) {
  const options = payload.options ?? [];
  if (options.length === 0) {
    return <div className="text-sm text-muted-foreground">No options.</div>;
  }
  return (
    <Section title="Options">
      <ul className="space-y-1.5">
        {options.map((opt, idx) => {
          const letter = String.fromCharCode(65 + idx); // A, B, C…
          return (
            <li
              key={idx}
              className={cn(
                "flex items-start gap-2 border border-border p-2 text-sm",
                opt.is_gold && "border-emerald-600/60 bg-emerald-600/5"
              )}
            >
              <span className="font-mono text-xs text-muted-foreground mt-0.5">
                {letter}
              </span>
              <span className="flex-1">{opt.content ?? ""}</span>
              <div className="flex shrink-0 items-center gap-1">
                {opt.is_gold && (
                  <Badge className="bg-emerald-600 text-white">gold</Badge>
                )}
                {opt.is_abstention && (
                  <Badge variant="outline">abstention</Badge>
                )}
                {opt.distractor_origin != null && (
                  <Badge variant="secondary">{opt.distractor_origin}</Badge>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function ClozePayloadSection({ payload }: { payload: ClozePayload }) {
  const accept = payload.accept_set ?? [];
  return (
    <Section title="Gold">
      <Field label="Gold">
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">
          {payload.gold ?? "—"}
        </code>
      </Field>
      <Field label="Accepted answers">
        {accept.length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {accept.map((a, idx) => (
              <code
                key={`${a}-${idx}`}
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
              >
                {a}
              </code>
            ))}
          </div>
        )}
      </Field>
    </Section>
  );
}

function ClaimPayloadSection({ payload }: { payload: ClaimPayload }) {
  return (
    <Section title="Gold">
      <Field label="Gold verdict">
        <Badge variant={payload.gold_verdict ? "default" : "secondary"}>
          {payload.gold_verdict === true
            ? "true"
            : payload.gold_verdict === false
              ? "false"
              : "—"}
        </Badge>
      </Field>
      {payload.correction != null && payload.correction !== "" && (
        <Field label="Correction">
          <span className="whitespace-pre-wrap">{payload.correction}</span>
        </Field>
      )}
    </Section>
  );
}

function PayloadSection({ forensics }: { forensics: Forensics }) {
  const { exam_type, payload } = forensics;
  switch (exam_type) {
    case "mcq":
      return <McqPayloadSection payload={payload as McqPayload} />;
    case "cloze":
      return <ClozePayloadSection payload={payload as ClozePayload} />;
    case "claim":
      return <ClaimPayloadSection payload={payload as ClaimPayload} />;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function ForensicsPanel({
  record,
  className,
}: {
  record: RunRecord | null | undefined;
  className?: string;
}) {
  if (!record || !record.forensics) {
    return (
      <div className={cn("text-sm text-muted-foreground", className)}>
        No grader forensics for this trial.
      </div>
    );
  }

  const forensics = record.forensics;
  const { display, exam_type } = forensics;
  const state = gradeState(record, display);

  return (
    <div className={cn("space-y-4", className)}>
      <Section title="Grade">
        <div className="flex items-center gap-2">
          <GradeBadge state={state} />
          {exam_type != null && <Badge variant="outline">{exam_type}</Badge>}
          {record.score != null && (
            <span className="text-xs text-muted-foreground tabular-nums">
              score {record.score.toFixed(2)}
            </span>
          )}
        </div>

        <Field label="Question">
          <span className="whitespace-pre-wrap">{display.question}</span>
        </Field>

        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Agent answer">
            <AnswerBlock answer={display.answer} examType={exam_type} />
          </Field>
          <Field label="Expected">
            {display.expected == null || display.expected === "" ? (
              <span className="text-muted-foreground">—</span>
            ) : (
              <span className="whitespace-pre-wrap">{display.expected}</span>
            )}
          </Field>
        </div>
      </Section>

      <PayloadSection forensics={forensics} />
    </div>
  );
}
