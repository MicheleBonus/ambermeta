import { useEffect } from "react";
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider, useSelection } from "@/state/selection";
import { Inspector } from "./Inspector";

const FILE_PATH = "/work/wt_hmr.prmtop";

function SelectFile({ path }: { path: string }) {
  const { select } = useSelection();
  useEffect(() => { select("file", path); }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function setup() {
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <SelectFile path={FILE_PATH} />
        <Inspector />
      </SelectionProvider>
    </QueryClientProvider>
  );
}

describe("Inspector", () => {
  it("shows curated peek fields for a selected file, then lazy-loads the raw tab", async () => {
    server.use(
      http.get("/api/files/metadata", () =>
        HttpResponse.json({
          file_path: FILE_PATH,
          file_type: "prmtop",
          metadata: { details: { atoms: 42318, hmr_active: true }, kind: "prmtop" },
          warnings: [],
        })
      ),
      http.get("/api/files/raw", () =>
        HttpResponse.json({ path: FILE_PATH, content: "%VERSION  VERSION_STAMP", truncated: false })
      ),
    );

    setup();

    await waitFor(() => expect(screen.getByText("42318")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("tab", { name: /raw file/i }));

    await waitFor(() => expect(screen.getByText(/%VERSION/)).toBeInTheDocument());
  });
});
