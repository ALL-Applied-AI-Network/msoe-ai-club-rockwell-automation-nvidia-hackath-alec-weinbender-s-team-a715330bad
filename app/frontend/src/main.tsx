import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router";
import { ExperimentsPage } from "./pages/experiments/ExperimentsPage";
import { GpuPage } from "./pages/gpu/GpuPage";
import { NotBuiltPage } from "./pages/NotBuiltPage";
import "./styles/tokens.css";
import "./styles/base.css";

// Hash routes (#/jobs/...) so deep links work while the backend serves the build as plain static files. The routes and
// what each page holds are docs/notes/frontend-plan.md, section 3. Routes ending in /* hand their sub-pages to the page's
// own <Routes>. Pages that pull in three.js or Recharts load on first visit (`lazy`), so the Experiments page stays light.
const router = createHashRouter([
  { path: "/", element: <ExperimentsPage /> },
  { path: "/gpu/*", element: <GpuPage /> },
  { path: "/new/:step", lazy: async () => ({ Component: (await import("./pages/wizard/WizardPage")).WizardPage }) },
  { path: "/jobs/:id", lazy: async () => ({ Component: (await import("./pages/job/JobPage")).JobPage }) },
  { path: "/jobs/:id/log", lazy: async () => ({ Component: (await import("./pages/log/QuickLogPage")).QuickLogPage }) },
  {
    path: "/jobs/:id/validation",
    lazy: async () => ({ Component: (await import("./pages/validation/JobValidationPage")).JobValidationPage }),
  },
  { path: "/parts/*", lazy: async () => ({ Component: (await import("./pages/parts/PartsPage")).PartsPage }) },
  {
    path: "/validation",
    lazy: async () => ({ Component: (await import("./pages/validation/ValidationPage")).ValidationPage }),
  },
  { path: "/settings/*", lazy: async () => ({ Component: (await import("./pages/settings/SettingsPage")).SettingsPage }) },
  { path: "*", element: <NotBuiltPage title="Page not found" plan="There's no page at this address." /> },
]);
const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
