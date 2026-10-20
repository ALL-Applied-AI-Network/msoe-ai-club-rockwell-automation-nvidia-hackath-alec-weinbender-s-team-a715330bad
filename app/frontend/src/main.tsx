import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router";
import { GpuPanel } from "./components/GpuPanel";
import { Page } from "./components/Page";
import "./styles/tokens.css";
import "./styles/base.css";

// Hash routes (#/jobs/...) so deep links work while the backend serves the build as plain static files.
const router = createHashRouter([{ path: "/", element: <Home /> }]);
const queryClient = new QueryClient();

function Home() {
  return (
    <Page>
      <GpuPanel />
    </Page>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
