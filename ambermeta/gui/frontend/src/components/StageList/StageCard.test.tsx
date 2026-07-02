import type { ReactNode } from "react";
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { DndContext, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { SelectionProvider } from "@/state/selection";
import { StageCard } from "./StageCard";
import type { StageModel } from "@/types";

// A bare <DndContext> activates dnd-kit's default PointerSensor on the very
// first pixel of pointer movement (no activation constraint), which then
// swallows the ensuing click/dblClick globally. That breaks userEvent
// interactions (dblClick/type/selectOptions) on controls nested inside the
// drag-listener element. Mirror App.tsx / FileBrowser.test.tsx with a
// distance-based activation constraint so this test exercises real
// click behavior instead of an artifact of the default sensor config.
function DndTestProvider({ children }: { children: ReactNode }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  return <DndContext sensors={sensors}>{children}</DndContext>;
}

const stage: StageModel = { id: "1", name: "min", role: "", prmtop: null, mdin: null,
  mdout: null, mdcrd: null, inpcrd: null, expected_gap_ps: null, gap_tolerance_ps: null, notes: [] };

function renderCard() {
  queryClient.clear();
  server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument })));
  return render(
    <QueryClientProvider client={queryClient}>
      <SelectionProvider><DndTestProvider>
        <StageCard stage={stage} index={0} isSelected={false} onSelect={() => {}} />
      </DndTestProvider></SelectionProvider>
    </QueryClientProvider>
  );
}

describe("StageCard inline edit", () => {
  it("renames on double-click + Enter", async () => {
    let sentName: unknown;
    server.use(http.put("/api/stages/:id", async ({ request }) =>
      { sentName = ((await request.json()) as { name?: string }).name; return HttpResponse.json(emptyDocument); }));
    renderCard();
    await userEvent.dblClick(screen.getByText("min"));
    const input = screen.getByDisplayValue("min");
    await userEvent.clear(input);
    await userEvent.type(input, "minim{Enter}");
    await waitFor(() => expect(sentName).toBe("minim"));
  });
  it("changes role via inline select", async () => {
    let sentRole: unknown;
    server.use(http.put("/api/stages/:id", async ({ request }) =>
      { sentRole = ((await request.json()) as { role?: string }).role; return HttpResponse.json(emptyDocument); }));
    renderCard();
    await userEvent.selectOptions(screen.getByLabelText(/stage role/i), "production");
    await waitFor(() => expect(sentRole).toBe("production"));
  });
  it("exposes a dedicated drag handle and keeps card click for select", async () => {
    let selected = false;
    queryClient.clear();
    server.use(http.get("/api/document", () => HttpResponse.json({ ...emptyDocument })));
    render(
      <QueryClientProvider client={queryClient}>
        <SelectionProvider><DndContext>
          <StageCard stage={stage} index={0} isSelected={false} onSelect={() => { selected = true; }} />
        </DndContext></SelectionProvider>
      </QueryClientProvider>
    );
    expect(screen.getByLabelText(/drag to reorder/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText("min"));
    expect(selected).toBe(true);
  });
});
