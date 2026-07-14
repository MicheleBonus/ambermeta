// src/App.test.tsx
import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/api/queryClient";
import App from "@/App";

it("renders the three panes over an empty document", async () => {
  render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
  await waitFor(() => {
    expect(screen.getByTestId("pane-files")).toBeInTheDocument();
    expect(screen.getByTestId("pane-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("pane-inspector")).toBeInTheDocument();
  });
});
