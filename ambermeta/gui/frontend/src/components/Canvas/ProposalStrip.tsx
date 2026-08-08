import { useState } from "react";
import { Modal, Button } from "@/components/common";
import { useInferLineages, useSetLineages, useUpdateStep } from "@/api/hooks";
import type { LineageProposal, ProposedMember } from "@/types";

/**
 * Shows the grouping discovery inferred and lets the user accept it -- the surface this
 * whole branch exists to deliver. Before this component, a replica tag could only be
 * created from a control that appeared once a tag already existed, which made a five-way
 * campaign (equil/01..05 feeding prod/01..05) impossible to declare through the GUI at all.
 *
 * Two modes, one component. `proposed` is driven by what discovery inferred and offers a
 * binary Accept / Not replicas. `manual` is driven by the same segment picker, always
 * open, for when inference refused or got the grouping wrong; member rows stay editable in
 * both, because that is what covers the irregular remainder a segment picker cannot
 * express (a run named oddly, a member with an extra or a missing directory).
 *
 * Rendered as a `Modal` deliberately, not inline in the canvas. `Modal` increments the
 * global open-modal counter `App.tsx` reads to suspend Ctrl+Z
 * (`useUndoShortcuts({ enabled: !modalOpen })`). Were this strip inline instead, Ctrl+Z
 * would stay live while it was open, and a user reviewing five proposed members could
 * rewind the very document the strip is describing out from under itself mid-review.
 */

/** Every member currently sharing `tags[m.tag]` collapses into one PATCH, carrying the
 *  union of their step ids -- so retagging two proposed members to the same string merges
 *  them into one lineage in one request, rather than leaving the second write's tag
 *  silently win. Grouping happens before anything is sent, which is also what makes the
 *  request count "N tags", not "N members": the two can differ. */
function groupByTag(
  members: ProposedMember[],
  tags: Record<string, string>,
): { tag: string; ids: string[] }[] {
  const order: string[] = [];
  const byTag = new Map<string, string[]>();
  for (const m of members) {
    // A field emptied mid-edit falls back to the member's own proposed tag rather than
    // sending an empty string: "" is a real, distinct lineage value as far as the server
    // is concerned (only `null` clears a tag), and a blank input is almost certainly a
    // user who has not finished typing, not someone declaring an unnamed member.
    const tag = (tags[m.tag] ?? m.tag).trim() || m.tag;
    if (!byTag.has(tag)) { byTag.set(tag, []); order.push(tag); }
    byTag.get(tag)!.push(...m.step_ids);
  }
  return order.map((tag) => ({ tag, ids: byTag.get(tag) as string[] }));
}

/** `segments[i]`'s distinct values, joined for one segment-picker button's label. Past
 *  three the label would run the button off the strip's own fixed 560px width (five
 *  replicas -- equil/01..05 -- is the motivating case, not a hypothetical), so it
 *  truncates and leaves the member table underneath, which already scrolls, to carry the
 *  rest: "01|02|03…" for five values, never a fourth pipe-joined segment. */
function segmentLabel(values: string[]): string {
  const distinct = Array.from(new Set(values));
  const shown = distinct.slice(0, 3).join("|");
  return distinct.length > 3 ? `${shown}…` : shown;
}

/** `tags` starts as the identity map -- every proposed tag editable in place, changed
 *  only where the user types something else. Recomputed (not merged) whenever the
 *  segment picker replaces the shown proposal, so a stale edit against a member that no
 *  longer exists cannot leak into the next accept. */
function identityTags(p: LineageProposal): Record<string, string> {
  return Object.fromEntries(p.members.map((m) => [m.tag, m.tag]));
}

export function ProposalStrip({
  proposal, mode, onClose,
}: {
  proposal: LineageProposal;
  mode: "proposed" | "manual";
  onClose: () => void;
}) {
  // Seeded once from the prop and held here, not re-derived on every render: the segment
  // picker below replaces this proposal wholesale (a different column can name a wholly
  // different set of members), and re-deriving from `proposal` on every render would
  // discard that in favour of what the caller originally passed in.
  const [shown, setShown] = useState(proposal);
  const [tags, setTags] = useState(() => identityTags(proposal));
  const [changeOpen, setChangeOpen] = useState(false);
  const [wireHandoffs, setWireHandoffs] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<{ applied: number; total: number } | null>(null);

  const infer = useInferLineages();
  const setLineages = useSetLineages();
  const updateStep = useUpdateStep();

  // Always open in manual mode -- there is no proposed grouping to hide it behind, only
  // the picker itself. In proposed mode it starts collapsed behind "Change ▾": most
  // reviews of a correct proposal never need it, and showing the raw path-segment
  // machinery up front would bury the two buttons (Accept / Not replicas) that answer
  // the question the strip actually opened to ask.
  const pickerVisible = mode === "manual" || changeOpen;
  const runDirCount = shown.members.reduce((n, m) => n + m.sources.length, 0);

  // Called from a button's onClick, not from render -- `useInferLineages()` itself is
  // called exactly once, at the top of the component, above. Calling a hook from inside
  // this handler (as an earlier draft of this component did) is an invalid hook call
  // that throws at runtime the moment the segment picker is clicked.
  function pickSegment(index: number) {
    infer.mutate(index, {
      onSuccess: (res) => {
        if (!res.proposal) return;
        setShown(res.proposal);
        setTags(identityTags(res.proposal));
      },
    });
  }

  async function accept() {
    setResult(null);
    setApplying(true);
    const groups = groupByTag(shown.members, tags);
    const handoffsToWire = wireHandoffs ? shown.handoffs : [];
    const total = groups.length + handoffsToWire.length;
    let done = 0;
    try {
      // Tags FIRST, handoffs second -- load-bearing, not stylistic, and the one ordering
      // this component's own commit argues hardest for. Tagging a member first leaves
      // every one of its proposed handoffs intra-member (producer and consumer now share
      // a lineage), so `_check_continues_from` raises no "branch, not a continuation"
      // warning and `_sever_crossed_refs` has nothing crossing a lineage boundary to
      // sever. Reversed, each PUT below would land on a still-untagged pair, get accepted
      // as an ordinary cross-directory restart, and then get silently deleted the moment
      // the matching PATCH ran a heartbeat later -- discarding the very edge this block
      // exists to write, with no error to say so.
      for (const g of groups) {
        await setLineages.mutateAsync({ ids: g.ids, lineage: g.tag });
        done += 1;
      }
      for (const h of handoffsToWire) {
        await updateStep.mutateAsync({
          id: h.consumer_id,
          body: { input_coords: { source: "step", ref: h.producer_id, path: null } },
        });
        done += 1;
      }
      onClose();
    } catch {
      // A failure partway through leaves `done` of `total` requests applied and the rest
      // not -- there is no transaction spanning N separate PATCH/PUT calls, so claiming
      // success here would be a worse lie than claiming nothing. Reporting nothing would
      // be its own lie in the other direction: real edits already landed, and a plain
      // retry would re-tag the members that already succeeded.
      //
      // Deliberately no Undo toast. `setDocument` (run by every one of the mutations
      // above, via `docMutation`) expires edit toasts on every response it handles, so an
      // offer raised after request 1 lands is destroyed the instant request 2's response
      // arrives -- and even if it survived, a single Undo click pops only the newest of
      // the N undo frames these calls just pushed, silently leaving the rest applied.
      setResult({ applied: done, total });
    } finally {
      setApplying(false);
    }
  }

  return (
    <Modal
      open
      title={mode === "manual" ? "Tag runs by path segment" : "Proposed run lineages"}
      onClose={onClose}
    >
      <p className="text-sm text-ink">
        {mode === "manual"
          ? "Which part of the path names the replica?"
          : `${runDirCount} run directories look like ${shown.members.length} repeated members`}
      </p>

      {mode === "proposed" && (
        <button
          type="button"
          onClick={() => setChangeOpen((v) => !v)}
          aria-expanded={changeOpen}
          className="mt-1 text-xs text-ink-muted hover:text-ink"
        >
          Change ▾
        </button>
      )}

      {pickerVisible && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {shown.segments.map((values, i) => (
            <button
              key={i}
              type="button"
              disabled={infer.isPending}
              onClick={() => pickSegment(i)}
              className={`px-2 py-1 rounded border border-hairline font-mono text-xs disabled:opacity-40 ${
                i === shown.segment_index ? "text-accent" : "text-ink-secondary hover:text-ink"
              }`}
            >
              {segmentLabel(values)}
            </button>
          ))}
        </div>
      )}

      {/* font-mono text-xs + its own overflow-x-auto: the Modal this sits inside is
          fixed-width (w-[min(560px,92vw)]), and a member table with five rows of
          "equil/01 (18) + prod/01 (202)" runs well past that on any reasonable font. */}
      <div className="mt-3 space-y-1 overflow-x-auto">
        {shown.members.map((m) => (
          <div key={m.tag} className="flex items-center gap-2 whitespace-nowrap font-mono text-xs">
            <input
              aria-label={`tag for ${m.tag}`}
              value={tags[m.tag] ?? m.tag}
              onChange={(e) => setTags((s) => ({ ...s, [m.tag]: e.target.value }))}
              className="w-20 shrink-0 rounded border border-hairline bg-app px-1 py-0.5 text-ink"
            />
            <span className="text-ink-secondary">
              {m.sources.map((s) => `${s.directory} (${s.run_count})`).join(" + ")}
            </span>
          </div>
        ))}
      </div>

      {shown.handoffs.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-hairline pt-2">
          <p className="text-xs text-ink-secondary">
            AMBER&apos;s own restart files show these runs continuing across the directory
            boundary the tags above just drew:
          </p>
          <ul className="space-y-0.5">
            {shown.handoffs.map((h) => (
              <li key={h.consumer_id} className="font-mono text-xs text-ink">
                {h.producer} → {h.consumer}
                <span className="block text-ink-muted">{h.evidence}</span>
              </li>
            ))}
          </ul>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => setWireHandoffs(true)}
              className={`text-xs ${wireHandoffs ? "text-accent" : "text-ink-muted hover:text-ink"}`}
            >
              Wire these
            </button>
            <button
              type="button"
              onClick={() => setWireHandoffs(false)}
              className={`text-xs ${!wireHandoffs ? "text-accent" : "text-ink-muted hover:text-ink"}`}
            >
              Leave unlinked
            </button>
          </div>
        </div>
      )}

      {/* Both numbers as bare interpolations inside one element: Testing Library's
          getNodeText joins only DIRECT text-node children, so wrapping either number in
          its own <span> or <strong> would break `findByText(/applied 1 of 2/i)`. */}
      {result && (
        <p className="mt-3 text-xs text-error">applied {result.applied} of {result.total}</p>
      )}

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button disabled={applying} onClick={onClose}>
          {mode === "manual" ? "Cancel" : "Not replicas"}
        </Button>
        <Button variant="primary" disabled={applying} onClick={accept}>
          {mode === "manual" ? "Apply" : "Accept"}
        </Button>
      </div>
    </Modal>
  );
}
