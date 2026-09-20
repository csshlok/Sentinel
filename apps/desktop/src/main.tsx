import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { queryClient, router } from "./app/router";
import "./styles/app.css";
import { applyTheme, watchSystemTheme } from "./lib/theme";

// Before first paint, so a dark preference never flashes light.
applyTheme();
watchSystemTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
