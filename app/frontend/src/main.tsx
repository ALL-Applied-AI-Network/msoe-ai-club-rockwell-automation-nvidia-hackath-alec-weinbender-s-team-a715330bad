import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/manrope";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, Navigate, RouterProvider, useParams } from "react-router";
import { JobsPage } from "./pages/jobs/JobsPage";
import { OverviewPage } from "./pages/overview/OverviewPage";
import { GpuPage } from "./pages/gpu/GpuPage";
import { NotBuiltPage } from "./pages/NotBuiltPage";
import "./theme";
import "./styles/tokens.css";
import "./styles/base.css";

// Hash routes (#/jobs/...) so deep links work while the backend serves the build as plain static files. The routes and
// what each page holds are docs/notes/frontend-plan.md, section 3. Routes ending in /* hand their sub-pages to the page's
// own <Routes>. Pages that pull in three.js or Recharts load on first visit (`lazy`), so the Overview stays light.
const router = createHashRouter([
  { path: "/", element: <OverviewPage /> },
  { path: "/jobs", element: <JobsPage /> },
  { path: "/new", element: <Navigate to="/new/part" replace /> },
  { path: "/evaluate", lazy: async () => ({ Component: (await import("./pages/evaluate/NewEvaluationPage")).NewEvaluationPage }) },
  { path: "/fingers/*", lazy: async () => ({ Component: (await import("./pages/fingers/FingersPage")).FingersPage }) },
  { path: "/gpu/*", element: <GpuPage /> },
  { path: "/new/:step", lazy: async () => ({ Component: (await import("./pages/wizard/WizardPage")).WizardPage }) },
  { path: "/jobs/:id", lazy: async () => ({ Component: (await import("./pages/job/JobPage")).JobPage }) },
  { path: "/jobs/:id/log", element: <LogRedirect /> }, // the old quick logger: now part of the validation page
  {
    path: "/jobs/:id/validation",
    lazy: async () => ({ Component: (await import("./pages/validation/JobValidationPage")).JobValidationPage }),
  },
  { path: "/parts/*", lazy: async () => ({ Component: (await import("./pages/parts/PartsPage")).PartsPage }) },
  {
    path: "/validation",
    lazy: async () => ({ Component: (await import("./pages/validation/ValidationPage")).ValidationPage }),
  },
  { path: "/cells/*", lazy: async () => ({ Component: (await import("./pages/cells/CellsPage")).CellsPage }) },
  { path: "/settings/*", element: <SettingsRedirect /> },
  { path: "*", element: <NotBuiltPage title="Page not found" plan="There's no page at this address." /> },
]);
const queryClient = new QueryClient();

/** The quick logger merged into the validation page's logging stage: an old #/jobs/:id/log link opens it there. */
function LogRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/jobs/${id}/validation`} replace />;
}

/** The cells used to live under Settings: an old #/settings/cells/:id link opens the same cell at #/cells/:id. */
function SettingsRedirect() {
  const rest = useParams()["*"] ?? "";
  return <Navigate to={rest.startsWith("cells/") ? `/${rest}` : "/cells"} replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
