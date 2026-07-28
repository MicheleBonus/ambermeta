import { useState } from "react";
import {
  useDocument, useAddTopology, useSetStartingStructure, useAssign, useCreatePhase, useCreateStep,
} from "@/api/hooks";
import { Button } from "@/components/common";
import { stemName } from "@/lib/format";
import { ROLE_OPTIONS } from "@/lib/roles";
import type { FileType, StageRole, PhaseModel, StepModel } from "@/types";

function flattenSteps(phases: PhaseModel[]): { phase: PhaseModel; step: StepModel }[] {
  return phases.flatMap((phase) => phase.steps.map((step) => ({ phase, step })));
}

export function AssignActions({ path, fileType }: { path: string; fileType: FileType }) {
  const { data: doc } = useDocument();
  const addTopology = useAddTopology();
  const setStartingStructure = useSetStartingStructure();
  const assign = useAssign();
  const createPhase = useCreatePhase();
  const createStep = useCreateStep();
  const [role, setRole] = useState<StageRole>("production");

  const phases = doc?.simulation.phases ?? [];
  const steps = flattenSteps(phases);

  if (fileType === "prmtop") {
    const looksHmr = path.toLowerCase().includes("hmr");
    return (
      <div className="p-3 border-t border-hairline space-y-2">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Assign</div>
        <div className="flex gap-2">
          <Button
            variant={looksHmr ? "primary" : "ghost"}
            onClick={() => addTopology.mutate({ path, kind: "hmr" })}
          >
            Add to pool as HMR
          </Button>
          <Button
            variant={looksHmr ? "ghost" : "primary"}
            onClick={() => addTopology.mutate({ path, kind: "normal" })}
          >
            Add to pool as normal
          </Button>
        </div>
        <label className="block text-xs text-ink-secondary">
          Set as phase default ▾
          <select
            aria-label="Set as phase default"
            defaultValue=""
            className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app text-sm text-ink"
            onChange={(e) => {
              const phaseId = e.target.value;
              e.target.value = "";
              if (phaseId) assign.mutate({ path, target_type: "phase_topology", target_id: phaseId });
            }}
          >
            <option value="" disabled>Choose a phase…</option>
            {phases.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-ink-secondary">
          Assign to a step ▾
          <select
            aria-label="Assign to a step"
            defaultValue=""
            className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app text-sm text-ink"
            onChange={(e) => {
              const stepId = e.target.value;
              e.target.value = "";
              if (stepId) assign.mutate({ path, target_type: "step_topology", target_id: stepId });
            }}
          >
            <option value="" disabled>Choose a step…</option>
            {steps.map(({ phase, step }) => (
              <option key={step.id} value={step.id}>{phase.name} / {step.name}</option>
            ))}
          </select>
        </label>
      </div>
    );
  }

  if (fileType === "inpcrd") {
    return (
      <div className="p-3 border-t border-hairline space-y-2">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Assign</div>
        <Button variant="primary" onClick={() => setStartingStructure.mutate(path)}>
          Set as starting structure
        </Button>
      </div>
    );
  }

  if (fileType === "mdin") {
    return (
      <div className="p-3 border-t border-hairline space-y-2">
        <div className="text-xs text-ink-muted uppercase tracking-wide">Assign</div>
        <label className="block text-xs text-ink-secondary">
          Role
          <select
            aria-label="Step role"
            value={role}
            onChange={(e) => setRole(e.target.value as StageRole)}
            className="w-full mt-1 px-2 py-1 border border-hairline rounded bg-app text-sm text-ink"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r.value || "none"} value={r.value}>{r.label}</option>
            ))}
          </select>
        </label>
        <Button
          variant="primary"
          onClick={async () => {
            let phaseId = phases.find((p) => p.role === role)?.id;
            if (!phaseId) {
              const label = ROLE_OPTIONS.find((r) => r.value === role)?.label ?? "Phase";
              const newDoc = await createPhase.mutateAsync({ name: label, role });
              phaseId = newDoc.simulation.phases.find((p) => p.role === role)?.id
                ?? newDoc.simulation.phases[newDoc.simulation.phases.length - 1]?.id;
            }
            if (!phaseId) return;
            await createStep.mutateAsync({ phaseId, body: { name: stemName(path), mdin: path } });
          }}
        >
          Create a step
        </Button>
      </div>
    );
  }

  return null;
}
