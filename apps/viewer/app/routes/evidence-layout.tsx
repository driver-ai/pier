// Shared evidence-mode layout (Checkpoint-2 rework). Wraps the four evidence
// routes — /evidence, /method, /tasks, /trace — in ONE React Router pathless
// layout route so they share a persistent top nav bar and one consistent
// content container. This is a nested route layout (renders <Outlet/>), NOT the
// root shell in root.tsx.
//
// - Left: product title "Benchmark Evidence" linking to /evidence (mono, matches
//   the app's headings).
// - Nav tabs: Evidence (→/evidence) and Method (→/method) as keyboard-focusable
//   NavLinks with an active state driven by the current route. Tasks/Trace are
//   drill pages reached through Evidence, so they have no top-level tab — but
//   they keep the Evidence tab marked active (they belong to the Evidence flow).
// - Right: run identity from /api/config (reuses fetchConfig / ["config"]),
//   showing the folder basename in muted mono; hidden when unavailable.

import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation, useSearchParams } from "react-router";

import { fetchConfig } from "~/lib/api";
import { cn } from "~/lib/utils";

// The section a route belongs to, for active-tab resolution. Tasks and
// record-mode Trace are part of the Evidence flow, so they resolve to
// "evidence". The Trajectories browser (`/trajectories`) — and gather-mode
// `/trace?gather=` reached from it — resolve to "trajectories".
function activeSection(
  pathname: string,
  isGatherTrace: boolean
): "evidence" | "trajectories" | "method" {
  if (pathname.startsWith("/method")) return "method";
  if (pathname.startsWith("/trajectories")) return "trajectories";
  if (pathname.startsWith("/trace") && isGatherTrace) return "trajectories";
  return "evidence";
}

interface NavTabProps {
  to: string;
  active: boolean;
  children: React.ReactNode;
}

// A top-level nav tab. Active state is passed in (derived from the current
// route) rather than relying on NavLink's own matching, because /tasks and
// /trace must mark the Evidence tab active.
function NavTab({ to, active, children }: NavTabProps) {
  return (
    <NavLink
      to={to}
      className={cn(
        "border-b-2 px-1 py-3 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-foreground text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </NavLink>
  );
}

export default function EvidenceLayout() {
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();
  // Gather-mode trace (`?gather=` present, no `record`) belongs to the
  // Trajectories flow; record-mode trace stays under Evidence.
  const isGatherTrace =
    searchParams.has("gather") && !searchParams.get("record");
  const section = activeSection(pathname, isGatherTrace);

  // Run identity — reuse the shared ["config"] query. Hidden when unavailable.
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: fetchConfig,
    staleTime: Infinity,
  });

  // The folder basename (e.g. `frontier-0702`), tolerating trailing slashes.
  const folderBasename = config?.folder
    ? config.folder.replace(/\/+$/, "").split("/").pop() || null
    : null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-screen-2xl items-center gap-8 px-6">
          <NavLink
            to="/evidence"
            className="font-mono text-sm tracking-tight text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Benchmark Evidence
          </NavLink>
          <nav className="flex items-center gap-6">
            <NavTab to="/evidence" active={section === "evidence"}>
              Evidence
            </NavTab>
            <NavTab
              to="/trajectories"
              active={section === "trajectories"}
            >
              Trajectories
            </NavTab>
            <NavTab to="/method" active={section === "method"}>
              Method
            </NavTab>
          </nav>
          {folderBasename ? (
            <span className="ml-auto font-mono text-xs text-muted-foreground">
              {folderBasename}
            </span>
          ) : null}
        </div>
      </header>

      <main className="mx-auto w-full max-w-screen-2xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
