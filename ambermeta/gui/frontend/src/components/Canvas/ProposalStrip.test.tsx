/**
 * What the strip claims and what it sends.
 *
 * The two failures it exists to prevent: applying anything the user did not accept, and
 * reporting success after a partial apply. Two tags are two PATCHes and two undo frames --
 * a failure on the second leaves one applied, and saying "done" there is worse than saying
 * nothing. The seventh test pins the one ordering invariant the whole component argues for
 * in its commit message and that nothing else in the tree exercises: tags before handoffs.
 */
import { it, expect, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server, emptyDocument } from "@/test/server";
import { queryClient } from "@/api/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { ProposalStrip } from "./ProposalStrip";
import type { LineageProposal } from "@/types";

afterEach(() => queryClient.clear());

const proposal: LineageProposal = {
  segment_index: 1,
  segments: [["equil", "prod"], ["01", "02"]],
  members: [
    { tag: "01", step_ids: ["a1", "a2"], sources: [
      { directory: "equil/01", run_count: 18 }, { directory: "prod/01", run_count: 202 }] },
    { tag: "02", step_ids: ["b1"], sources: [
      { directory: "equil/02", run_count: 18 }, { directory: "prod/02", run_count: 201 }] },
  ],
  handoffs: [],
};

function show(p: LineageProposal = proposal, mode: "proposed" | "manual" = "proposed") {
  return render(
    <QueryClientProvider client={queryClient}>
      <ProposalStrip proposal={p} mode={mode} onClose={() => {}} />
    </QueryClientProvider>);
}

it("names each proposed member and the directories it is built from", async () => {
  show();
  // "01" is rendered as the VALUE of an editable input (Step 4: the tag field is
  // editable before Accept), not as a bare text node -- Testing Library's getNodeText
  // only reads an input's .value for type=submit|button|reset, so a text query for "01"
  // would find nothing even against a correct implementation.
  expect(await screen.findByLabelText("tag for 01")).toHaveValue("01");
  expect(screen.getByLabelText("tag for 02")).toHaveValue("02");
  expect(screen.getByText(/equil\/01 \(18\)/)).toBeInTheDocument();
  expect(screen.getByText(/prod\/01 \(202\)/)).toBeInTheDocument();
});

it("sends one bulk request per tag, carrying that tag's step ids", async () => {
  const seen: unknown[] = [];
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    seen.push(await request.json());
    return HttpResponse.json(emptyDocument);
  }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(seen).toHaveLength(2));
  expect(seen[0]).toEqual({ ids: ["a1", "a2"], lineage: "01" });
  expect(seen[1]).toEqual({ ids: ["b1"], lineage: "02" });
});

it("applies nothing when the user declines", async () => {
  let calls = 0;
  server.use(http.patch("/api/steps/lineage", () => { calls += 1;
    return HttpResponse.json(emptyDocument); }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Not replicas" }));
  expect(calls).toBe(0);
});

it("reports a partial apply rather than claiming success", async () => {
  let calls = 0;
  server.use(http.patch("/api/steps/lineage", () => {
    calls += 1;
    return calls === 1
      ? HttpResponse.json(emptyDocument)
      : HttpResponse.json({ detail: "no such step" }, { status: 404 });
  }));
  show();
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  expect(await screen.findByText(/applied 1 of 2/i)).toBeInTheDocument();
});

it("lets the user retag a member before applying", async () => {
  const seen: unknown[] = [];
  server.use(http.patch("/api/steps/lineage", async ({ request }) => {
    seen.push(await request.json());
    return HttpResponse.json(emptyDocument);
  }));
  show();
  const field = screen.getByLabelText("tag for 01");
  await userEvent.clear(field);
  await userEvent.type(field, "rep1");
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(seen).toHaveLength(2));
  expect(seen[0]).toEqual({ ids: ["a1", "a2"], lineage: "rep1" });
});

it("offers the segment picker in manual mode", async () => {
  show(proposal, "manual");
  // Two distinct values each, well under the truncate-past-three rule -- "equil|prod" and
  // "01|02", never "01…02" (that shorthand only applies once a segment has more than
  // three distinct values, e.g. five replicas: "01|02|03…").
  expect(await screen.findByRole("button", { name: "equil|prod" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "01|02" })).toBeInTheDocument();
});

it("writes the tags before the handoffs", async () => {
  const order: string[] = [];
  server.use(
    http.patch("/api/steps/lineage", () => { order.push("tag"); return HttpResponse.json(emptyDocument); }),
    http.put("/api/steps/:id", async ({ request, params }) => {
      order.push(`edge:${params.id}`);
      expect(await request.json()).toEqual({
        input_coords: { source: "step", ref: "a2", path: null },
      });
      return HttpResponse.json(emptyDocument);
    }),
  );
  show({ ...proposal, handoffs: [
    { consumer_id: "b1", producer_id: "a2", consumer: "prod/02/01_prod",
      producer: "equil/02/18_ntp_equi", evidence: "18_ntp_equi.restrt" },
  ] });
  await userEvent.click(screen.getByRole("button", { name: "Wire these" }));
  await userEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(order).toEqual(["tag", "tag", "edge:b1"]));
});
