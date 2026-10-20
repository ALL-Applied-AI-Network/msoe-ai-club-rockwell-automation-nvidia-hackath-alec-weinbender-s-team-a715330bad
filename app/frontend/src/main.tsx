import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router";
import { api } from "./backend/client";
import "./styles/tokens.css";
import "./styles/base.css";

// Hash routes (#/jobs/...) so deep links work while the backend serves the build as plain static files.
const router = createHashRouter([{ path: "/", element: <Home /> }]);
const queryClient = new QueryClient();

function Home() {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: async () => (await api.GET("/api/meta")).data,
  });
  return (
    <main>
      <h1>Gripper Finger Designer</h1>
      <p>
        {meta.isPending ? "Connecting to the backend…" : meta.data ? `Sim: ${meta.data.sim.badge}` : "Backend not reachable"}
      </p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
