import { useSelection } from "@/state/selection";
import { useFileMetadata } from "@/api/hooks";
import { FilePeek } from "./FilePeek";
import { FileDetails } from "./FileDetails";
import { AssignActions } from "./AssignActions";
import { StepInspector } from "./StepInspector";
import { PhaseInspector } from "./PhaseInspector";
import { SuggestionsTray } from "@/components/Suggestions/SuggestionsTray";

function FileInspector({ path }: { path: string }) {
  const { data } = useFileMetadata(path);
  return (
    <div className="flex flex-col h-full">
      <FilePeek path={path} />
      {data?.file_type && <AssignActions path={path} fileType={data.file_type} />}
      <FileDetails path={path} />
    </div>
  );
}

export function Inspector() {
  const { sel } = useSelection();

  if (sel.kind === "file" && sel.id) {
    return <FileInspector path={sel.id} />;
  }

  if (sel.kind === "step" && sel.id) {
    return <StepInspector stepId={sel.id} />;
  }

  if (sel.kind === "phase" && sel.id) {
    return <PhaseInspector phaseId={sel.id} />;
  }

  if (sel.kind === "sim") {
    // Sim-settings editing is filled in by a later task; the suggestions tray
    // (draft-first Needs you / Applied) is the sim-level content meanwhile.
    return <SuggestionsTray />;
  }

  return <SuggestionsTray />;
}
