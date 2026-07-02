import { type RouteConfig, index, layout, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("compare", "routes/compare.tsx"),
  route("jobs/:jobName", "routes/job.tsx"),
  route("jobs/:jobName/critiques", "routes/critiques.tsx"),
  route(
    "jobs/:jobName/critiques/:critiqueRunName",
    "routes/critique-run.tsx"
  ),
  route(
    "jobs/:jobName/tasks/:source/:agent/:modelProvider/:modelName/:taskName",
    "routes/task.tsx"
  ),
  route(
    "jobs/:jobName/tasks/:source/:agent/:modelProvider/:modelName/:taskName/trials/:trialName",
    "routes/trial.tsx"
  ),
  layout("routes/evidence-layout.tsx", [
    route("evidence", "routes/evidence.tsx"),
    route("method", "routes/method.tsx"),
    route("tasks", "routes/tasks.tsx"),
    route("trajectories", "routes/trajectories.tsx"),
    route("trace", "routes/trace.tsx"),
  ]),
  route("task-definitions", "routes/task-definitions.tsx"),
  route("task-definitions/:taskName", "routes/task-definition.tsx"),
  route("prototypes/chart-toolbar", "routes/chart-toolbar-prototypes.tsx"),
] satisfies RouteConfig;
