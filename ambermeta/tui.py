"""Terminal User Interface for building simulation protocol manifests.

This module provides an interactive TUI for creating and editing AMBER
simulation protocol manifests, with features like:
- File browser with directory tree navigation
- Stage creation with file linking
- Visual grouping by numeric sequences
- Export to YAML, JSON, TOML, or CSV formats
- Undo/redo for selections
- Save/load partial work

Requires: textual>=0.40.0 (install with `pip install ambermeta[tui]`)


FUTURE GUI IMPLEMENTATION PLAN
==============================

A graphical user interface (GUI) would complement this TUI for users who prefer
visual drag-and-drop workflows. Here's a design plan for future implementation:

FRAMEWORK OPTIONS:
- PyQt6/PySide6: Full-featured, cross-platform, good for complex UIs
- Dear PyGui: Fast rendering, good for data visualization
- Tkinter: Built-in, lightweight, but dated appearance
- Web-based (Flask/FastAPI + React): Modern, but requires browser

RECOMMENDED: PyQt6 with Qt Designer for layout

CORE FEATURES:
1. File Browser Panel (left side)
   - Tree view of simulation files
   - Icons for file types (prmtop, mdin, mdout, mdcrd, inpcrd)
   - Context menu: "Set as Global Prmtop", "Set as HMR Prmtop", "Add to Stage"
   - Drag files directly onto stages

2. Stage Builder Panel (center)
   - Visual cards/tiles for each stage
   - Drag-and-drop reordering
   - Drop zones for each file type
   - Visual indicators for missing files
   - Sequence grouping with expandable sections

3. Properties Panel (right side)
   - Stage properties when a stage is selected
   - Global settings when nothing selected
   - Role dropdown, gap settings, notes

4. Visual Features:
   - Drag lines connecting restart outputs to inputs
   - Color-coded stages by role (min=red, heat=orange, equil=yellow, prod=green)
   - Timeline view showing stage sequence
   - Validation warnings with red highlights

5. Toolbar:
   - Auto-detect from folder
   - Export (with format preview)
   - Undo/Redo buttons
   - Zoom controls for timeline view

6. Drag-and-Drop Workflows:
   - Drag folder → Auto-generate stages
   - Drag file → Add to selected stage or create new
   - Drag stage → Reorder in sequence
   - Drag between stages → Link files

IMPLEMENTATION MODULES:
- ambermeta/gui/__init__.py - Main entry point
- ambermeta/gui/main_window.py - QMainWindow subclass
- ambermeta/gui/file_browser.py - QTreeView for files
- ambermeta/gui/stage_canvas.py - Visual stage builder
- ambermeta/gui/properties.py - Property editor panel
- ambermeta/gui/dialogs.py - Export, settings dialogs
- ambermeta/gui/resources/ - Icons, stylesheets

CLI INTEGRATION:
  ambermeta protocol build --gui  # Launch GUI instead of TUI

This plan maintains compatibility with the existing ProtocolState class,
which can be shared between TUI and GUI implementations.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.message import Message
    from textual.reactive import reactive
    from textual.screen import ModalScreen
    from textual.widget import Widget
    from textual.widgets import (
        Button,
        DataTable,
        DirectoryTree,
        Footer,
        Header,
        Input,
        Label,
        ListItem,
        ListView,
        OptionList,
        RadioButton,
        RadioSet,
        Rule,
        Select,
        Static,
        TabbedContent,
        TabPane,
        Tree,
    )
    from textual.widgets.tree import TreeNode
    from textual.widgets.option_list import Option

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from ambermeta.protocol import (
    detect_numeric_sequences,
    infer_stage_role_from_path,
    smart_group_files,
)


# File extension mappings
FILE_EXTENSIONS = {
    "prmtop": {".prmtop", ".parm7", ".top"},
    "mdin": {".mdin", ".in"},
    "mdout": {".mdout", ".out"},
    "mdcrd": {".mdcrd", ".nc", ".crd", ".x"},
    "inpcrd": {".rst", ".rst7", ".ncrst", ".restrt", ".inpcrd"},
}

STAGE_ROLES = ["minimization", "heating", "equilibration", "production"]


def get_file_type(path: str) -> Optional[str]:
    """Determine the file type based on extension."""
    ext = Path(path).suffix.lower()
    name = Path(path).name.lower()

    for file_type, extensions in FILE_EXTENSIONS.items():
        if ext in extensions:
            return file_type
        # Also check by name pattern
        if file_type in name:
            return file_type
    return None


@dataclass
class StageFile:
    """Represents a file assigned to a stage."""
    path: str
    file_type: str  # prmtop, mdin, mdout, mdcrd, inpcrd

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "type": self.file_type}


@dataclass
class Stage:
    """Represents a simulation stage in the protocol."""
    name: str
    role: str = ""  # minimization, heating, equilibration, production
    files: Dict[str, str] = field(default_factory=dict)  # type -> path
    expected_gap_ps: Optional[float] = None
    gap_tolerance_ps: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    sequence_base: Optional[str] = None
    sequence_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert stage to manifest dictionary format."""
        result: Dict[str, Any] = {"name": self.name}
        if self.role:
            result["stage_role"] = self.role
        for file_type, path in self.files.items():
            result[file_type] = path
        if self.expected_gap_ps is not None:
            result["gaps"] = {"expected": self.expected_gap_ps}
            if self.gap_tolerance_ps is not None:
                result["gaps"]["tolerance"] = self.gap_tolerance_ps
        if self.notes:
            result["notes"] = self.notes
        return result


@dataclass
class UndoState:
    """Represents a state for undo/redo."""
    stages: List[Stage]
    global_prmtop: Optional[str]
    description: str


class ProtocolState:
    """Manages the state of the protocol being built."""

    def __init__(self, base_directory: str):
        self.base_directory = os.path.abspath(base_directory)
        self.stages: List[Stage] = []
        self.global_prmtop: Optional[str] = None
        self.hmr_prmtop: Optional[str] = None
        self.auto_link_restarts: bool = True

        # Undo/redo stacks
        self._undo_stack: List[UndoState] = []
        self._redo_stack: List[UndoState] = []
        self._max_undo = 50

        # File discovery cache
        self._discovered_files: Dict[str, Dict[str, str]] = {}
        self._sequences: Dict[str, List[str]] = {}

    def discover_files(self, recursive: bool = True) -> None:
        """Discover simulation files in the directory."""
        self._discovered_files = smart_group_files(
            self.base_directory,
            recursive=recursive
        )

        # Extract sequence information
        stems = list(self._discovered_files.keys())
        self._sequences = detect_numeric_sequences(stems)

    def get_discovered_files(self) -> Dict[str, Dict[str, str]]:
        """Get discovered files grouped by stem."""
        return self._discovered_files

    def get_sequences(self) -> Dict[str, List[str]]:
        """Get detected numeric sequences."""
        return self._sequences

    def _save_state(self, description: str) -> None:
        """Save current state for undo."""
        state = UndoState(
            stages=[Stage(**{
                "name": s.name,
                "role": s.role,
                "files": dict(s.files),
                "expected_gap_ps": s.expected_gap_ps,
                "gap_tolerance_ps": s.gap_tolerance_ps,
                "notes": list(s.notes),
                "sequence_base": s.sequence_base,
                "sequence_index": s.sequence_index,
            }) for s in self.stages],
            global_prmtop=self.global_prmtop,
            description=description,
        )
        self._undo_stack.append(state)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> Optional[str]:
        """Undo the last action. Returns description of undone action."""
        if not self._undo_stack:
            return None

        # Save current state for redo
        current = UndoState(
            stages=[Stage(**{
                "name": s.name,
                "role": s.role,
                "files": dict(s.files),
                "expected_gap_ps": s.expected_gap_ps,
                "gap_tolerance_ps": s.gap_tolerance_ps,
                "notes": list(s.notes),
                "sequence_base": s.sequence_base,
                "sequence_index": s.sequence_index,
            }) for s in self.stages],
            global_prmtop=self.global_prmtop,
            description="(current)",
        )
        self._redo_stack.append(current)

        # Restore previous state
        state = self._undo_stack.pop()
        self.stages = state.stages
        self.global_prmtop = state.global_prmtop
        return state.description

    def redo(self) -> Optional[str]:
        """Redo the last undone action. Returns description of redone action."""
        if not self._redo_stack:
            return None

        # Save current state for undo
        current = UndoState(
            stages=[Stage(**{
                "name": s.name,
                "role": s.role,
                "files": dict(s.files),
                "expected_gap_ps": s.expected_gap_ps,
                "gap_tolerance_ps": s.gap_tolerance_ps,
                "notes": list(s.notes),
                "sequence_base": s.sequence_base,
                "sequence_index": s.sequence_index,
            }) for s in self.stages],
            global_prmtop=self.global_prmtop,
            description="(current)",
        )
        self._undo_stack.append(current)

        # Restore next state
        state = self._redo_stack.pop()
        self.stages = state.stages
        self.global_prmtop = state.global_prmtop
        return state.description

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def add_stage(self, stage: Stage) -> None:
        """Add a new stage."""
        self._save_state(f"Add stage '{stage.name}'")
        self.stages.append(stage)

    def remove_stage(self, index: int) -> None:
        """Remove a stage by index."""
        if 0 <= index < len(self.stages):
            name = self.stages[index].name
            self._save_state(f"Remove stage '{name}'")
            self.stages.pop(index)

    def update_stage(self, index: int, stage: Stage) -> None:
        """Update a stage by index."""
        if 0 <= index < len(self.stages):
            self._save_state(f"Update stage '{stage.name}'")
            self.stages[index] = stage

    def move_stage(self, from_index: int, to_index: int) -> None:
        """Move a stage from one position to another."""
        if 0 <= from_index < len(self.stages) and 0 <= to_index < len(self.stages):
            name = self.stages[from_index].name
            self._save_state(f"Move stage '{name}'")
            stage = self.stages.pop(from_index)
            self.stages.insert(to_index, stage)

    def set_global_prmtop(self, path: Optional[str]) -> None:
        """Set the global prmtop file."""
        self._save_state("Set global prmtop")
        self.global_prmtop = path

    def create_stages_from_sequence(self, base_pattern: str, role: str = "") -> List[Stage]:
        """Create stages from a detected numeric sequence."""
        if base_pattern not in self._sequences:
            return []

        self._save_state(f"Create stages from sequence '{base_pattern}'")
        new_stages = []

        for idx, stem in enumerate(self._sequences[base_pattern]):
            if stem in self._discovered_files:
                files = {k: v for k, v in self._discovered_files[stem].items()
                        if not k.startswith("_")}

                stage = Stage(
                    name=stem,
                    role=role or infer_stage_role_from_path(stem) or "",
                    files=files,
                    sequence_base=base_pattern,
                    sequence_index=idx,
                )
                new_stages.append(stage)
                self.stages.append(stage)

        return new_stages

    def create_stage_from_stem(self, stem: str, role: str = "") -> Optional[Stage]:
        """Create a single stage from a discovered stem."""
        if stem not in self._discovered_files:
            return None

        self._save_state(f"Create stage '{stem}'")
        files = {k: v for k, v in self._discovered_files[stem].items()
                if not k.startswith("_")}

        # Get sequence info if available
        seq_base = self._discovered_files[stem].get("_sequence_base")
        seq_idx = self._discovered_files[stem].get("_sequence_index")

        stage = Stage(
            name=stem,
            role=role or infer_stage_role_from_path(stem) or "",
            files=files,
            sequence_base=seq_base,
            sequence_index=int(seq_idx) if seq_idx else None,
        )
        self.stages.append(stage)
        return stage

    def to_manifest(self, use_absolute_paths: bool = True) -> List[Dict[str, Any]]:
        """Convert the protocol to a manifest format."""
        manifest = []

        for stage in self.stages:
            entry = stage.to_dict()

            # Apply global prmtop if stage doesn't have one
            if self.global_prmtop and "prmtop" not in entry:
                entry["prmtop"] = self.global_prmtop

            # Convert to absolute paths if requested
            if use_absolute_paths:
                for key in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]:
                    if key in entry and entry[key]:
                        path = entry[key]
                        if not os.path.isabs(path):
                            entry[key] = os.path.join(self.base_directory, path)

            manifest.append(entry)

        return manifest

    def export_yaml(self, path: str, use_absolute_paths: bool = True) -> None:
        """Export manifest to YAML format."""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is required for YAML export. Install with: pip install pyyaml")

        manifest = {"stages": self.to_manifest(use_absolute_paths)}
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)

    def export_json(self, path: str, use_absolute_paths: bool = True) -> None:
        """Export manifest to JSON format."""
        manifest = self.to_manifest(use_absolute_paths)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def export_toml(self, path: str, use_absolute_paths: bool = True) -> None:
        """Export manifest to TOML format."""
        manifest = self.to_manifest(use_absolute_paths)

        lines = ["# AmberMeta Protocol Manifest", ""]
        for stage in manifest:
            lines.append("[[stages]]")
            for key, value in stage.items():
                if isinstance(value, dict):
                    # Handle nested dicts like gaps
                    for k, v in value.items():
                        lines.append(f'{key}_{k} = {repr(v)}')
                elif isinstance(value, list):
                    # Handle lists like notes
                    lines.append(f'{key} = {json.dumps(value)}')
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f'{key} = {value}')
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def export_csv(self, path: str, use_absolute_paths: bool = True) -> None:
        """Export manifest to CSV format."""
        import csv

        manifest = self.to_manifest(use_absolute_paths)

        # Determine all columns
        all_keys = set()
        for stage in manifest:
            all_keys.update(stage.keys())

        # Standard column order
        columns = ["name", "stage_role", "prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]
        for key in sorted(all_keys):
            if key not in columns:
                columns.append(key)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for stage in manifest:
                row = {}
                for key in columns:
                    value = stage.get(key, "")
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value)
                    row[key] = value
                writer.writerow(row)

    def save_session(self, path: str) -> None:
        """Save the current session state to a file."""
        session = {
            "base_directory": self.base_directory,
            "global_prmtop": self.global_prmtop,
            "hmr_prmtop": self.hmr_prmtop,
            "auto_link_restarts": self.auto_link_restarts,
            "stages": [s.to_dict() for s in self.stages],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2)

    @classmethod
    def load_session(cls, path: str) -> "ProtocolState":
        """Load a session state from a file."""
        with open(path, "r", encoding="utf-8") as f:
            session = json.load(f)

        state = cls(session["base_directory"])
        state.global_prmtop = session.get("global_prmtop")
        state.hmr_prmtop = session.get("hmr_prmtop")
        state.auto_link_restarts = session.get("auto_link_restarts", True)

        for stage_data in session.get("stages", []):
            stage = Stage(
                name=stage_data["name"],
                role=stage_data.get("stage_role", ""),
                files={k: v for k, v in stage_data.items()
                       if k in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"] and v},
                expected_gap_ps=stage_data.get("gaps", {}).get("expected"),
                gap_tolerance_ps=stage_data.get("gaps", {}).get("tolerance"),
                notes=stage_data.get("notes", []),
            )
            state.stages.append(stage)

        return state


if TEXTUAL_AVAILABLE:

    class FilteredFileTree(Tree[str]):
        """A file tree that filters to show only simulation files."""

        COMPONENT_CLASSES = {"file-icon", "dir-icon", "sequence-icon"}

        def __init__(
            self,
            path: str,
            *,
            show_all: bool = False,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(
                Path(path).name,
                data=path,
                name=name,
                id=id,
                classes=classes,
            )
            self.path = Path(path)
            self.show_all = show_all
            self._valid_extensions = set()
            for exts in FILE_EXTENSIONS.values():
                self._valid_extensions.update(exts)

        def on_mount(self) -> None:
            self._load_directory(self.root, self.path)
            self.root.expand()

        def _is_simulation_file(self, path: Path) -> bool:
            """Check if a file is a simulation-related file."""
            if path.is_dir():
                return True
            return path.suffix.lower() in self._valid_extensions

        def _load_directory(self, node: TreeNode[str], path: Path) -> None:
            """Load directory contents into the tree."""
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return

            for entry in entries:
                if entry.name.startswith("."):
                    continue

                if entry.is_dir():
                    # Check if directory contains any simulation files
                    has_sim_files = any(
                        self._is_simulation_file(f)
                        for f in entry.rglob("*")
                        if f.is_file()
                    ) if not self.show_all else True

                    if has_sim_files or self.show_all:
                        child = node.add(f"[bold blue]{entry.name}/[/]", data=str(entry))
                        child.allow_expand = True
                elif self.show_all or self._is_simulation_file(entry):
                    file_type = get_file_type(str(entry))
                    icon = self._get_file_icon(file_type)
                    child = node.add(f"{icon} {entry.name}", data=str(entry))
                    child.allow_expand = False

        def _get_file_icon(self, file_type: Optional[str]) -> str:
            """Get an icon for the file type."""
            icons = {
                "prmtop": "[green]P[/]",
                "mdin": "[yellow]I[/]",
                "mdout": "[cyan]O[/]",
                "mdcrd": "[magenta]T[/]",
                "inpcrd": "[blue]R[/]",
            }
            return icons.get(file_type, "[dim]*[/]")

        def _on_tree_node_expanded(self, event: Tree.NodeExpanded[str]) -> None:
            """Handle tree node expansion."""
            node = event.node
            if node.data and not node.children:
                path = Path(node.data)
                if path.is_dir():
                    self._load_directory(node, path)


    class StageList(Widget):
        """Widget for displaying and managing stages."""

        class StageSelected(Message):
            """Sent when a stage is selected."""
            def __init__(self, index: int, stage: Stage) -> None:
                self.index = index
                self.stage = stage
                super().__init__()

        class StageAction(Message):
            """Sent when an action is requested on a stage."""
            def __init__(self, action: str, index: int) -> None:
                self.action = action
                self.index = index
                super().__init__()

        selected_index: reactive[int] = reactive(-1)

        def __init__(
            self,
            state: ProtocolState,
            *,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state

        def compose(self) -> ComposeResult:
            yield DataTable(id="stage-table")

        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.cursor_type = "row"
            # Seq = Sequence position (order within a numbered sequence like prod_001, prod_002)
            table.add_columns("Stage Name", "Role", "Files", "Seq #")
            self.refresh_stages()

        def refresh_stages(self) -> None:
            """Refresh the stage list display."""
            table = self.query_one(DataTable)
            table.clear()

            for idx, stage in enumerate(self.state.stages):
                files_count = len(stage.files)
                seq_info = f"{stage.sequence_index+1}" if stage.sequence_index is not None else "-"

                table.add_row(
                    stage.name[:30],
                    stage.role[:12] if stage.role else "-",
                    str(files_count),
                    seq_info,
                    key=str(idx),
                )

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            """Handle row selection."""
            if event.row_key is not None:
                index = int(str(event.row_key.value))
                if 0 <= index < len(self.state.stages):
                    self.selected_index = index
                    self.post_message(self.StageSelected(index, self.state.stages[index]))


    class StageEditor(Widget):
        """Widget for editing a single stage."""

        class StageUpdated(Message):
            """Sent when a stage is updated."""
            def __init__(self, stage: Stage) -> None:
                self.stage = stage
                super().__init__()

        def __init__(
            self,
            stage: Optional[Stage] = None,
            *,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.stage = stage

        def compose(self) -> ComposeResult:
            with Vertical(id="stage-editor-content"):
                yield Label("Stage Editor", id="editor-title")
                yield Rule()

                with Horizontal(classes="editor-row"):
                    yield Label("Name:", classes="label")
                    yield Input(id="stage-name", placeholder="Stage name")

                with Horizontal(classes="editor-row"):
                    yield Label("Role:", classes="label")
                    yield Select(
                        [(r, r) for r in [""] + STAGE_ROLES],
                        id="stage-role",
                        allow_blank=True,
                    )

                yield Label("Files:", classes="section-label")

                for file_type in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]:
                    with Horizontal(classes="editor-row"):
                        yield Label(f"  {file_type}:", classes="label file-label")
                        yield Input(id=f"file-{file_type}", placeholder=f"{file_type} path")

                yield Rule()

                with Horizontal(classes="editor-row"):
                    yield Label("Expected Gap (ps):", classes="label")
                    yield Input(id="expected-gap", placeholder="0.0")

                with Horizontal(classes="editor-row"):
                    yield Label("Tolerance (ps):", classes="label")
                    yield Input(id="gap-tolerance", placeholder="0.1")

                with Horizontal(classes="editor-row"):
                    yield Label("Notes:", classes="label")
                    yield Input(id="stage-notes", placeholder="Optional notes")

                yield Rule()
                yield Label("Sequence Info:", classes="section-label")
                yield Static(
                    "[dim]Sequence tracks order within numbered file sets (e.g., prod_001, prod_002). "
                    "This is auto-detected but can be manually adjusted.[/]",
                    classes="help-text-small",
                )

                with Horizontal(classes="editor-row"):
                    yield Label("Seq Base:", classes="label")
                    yield Input(id="seq-base", placeholder="Sequence pattern (e.g., 'prod')")

                with Horizontal(classes="editor-row"):
                    yield Label("Seq Position:", classes="label")
                    yield Input(id="seq-index", placeholder="Position in sequence (1, 2, 3...)")

                yield Rule()

                with Horizontal(classes="button-row"):
                    yield Button("Apply", id="apply-stage", variant="primary")
                    yield Button("Clear", id="clear-stage", variant="default")

        def on_mount(self) -> None:
            self.load_stage(self.stage)

        def load_stage(self, stage: Optional[Stage]) -> None:
            """Load a stage into the editor."""
            self.stage = stage

            name_input = self.query_one("#stage-name", Input)
            role_select = self.query_one("#stage-role", Select)

            name_input.value = stage.name if stage else ""

            if stage and stage.role:
                role_select.value = stage.role
            else:
                role_select.value = Select.BLANK

            for file_type in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]:
                file_input = self.query_one(f"#file-{file_type}", Input)
                file_input.value = stage.files.get(file_type, "") if stage else ""

            gap_input = self.query_one("#expected-gap", Input)
            tolerance_input = self.query_one("#gap-tolerance", Input)
            notes_input = self.query_one("#stage-notes", Input)
            seq_base_input = self.query_one("#seq-base", Input)
            seq_index_input = self.query_one("#seq-index", Input)

            gap_input.value = str(stage.expected_gap_ps) if stage and stage.expected_gap_ps is not None else ""
            tolerance_input.value = str(stage.gap_tolerance_ps) if stage and stage.gap_tolerance_ps is not None else ""
            notes_input.value = "; ".join(stage.notes) if stage and stage.notes else ""
            seq_base_input.value = stage.sequence_base if stage and stage.sequence_base else ""
            seq_index_input.value = str(stage.sequence_index + 1) if stage and stage.sequence_index is not None else ""

        def get_stage(self) -> Optional[Stage]:
            """Get the stage from the editor fields."""
            name_input = self.query_one("#stage-name", Input)
            if not name_input.value.strip():
                return None

            role_select = self.query_one("#stage-role", Select)

            files = {}
            for file_type in ["prmtop", "mdin", "mdout", "mdcrd", "inpcrd"]:
                file_input = self.query_one(f"#file-{file_type}", Input)
                if file_input.value.strip():
                    files[file_type] = file_input.value.strip()

            gap_input = self.query_one("#expected-gap", Input)
            tolerance_input = self.query_one("#gap-tolerance", Input)
            notes_input = self.query_one("#stage-notes", Input)

            expected_gap = None
            if gap_input.value.strip():
                try:
                    expected_gap = float(gap_input.value.strip())
                except ValueError:
                    pass

            tolerance = None
            if tolerance_input.value.strip():
                try:
                    tolerance = float(tolerance_input.value.strip())
                except ValueError:
                    pass

            notes = []
            if notes_input.value.strip():
                notes = [n.strip() for n in notes_input.value.split(";") if n.strip()]

            # Get sequence info from inputs
            seq_base_input = self.query_one("#seq-base", Input)
            seq_index_input = self.query_one("#seq-index", Input)

            seq_base = seq_base_input.value.strip() or None
            seq_index = None
            if seq_index_input.value.strip():
                try:
                    # User enters 1-based, we store 0-based
                    seq_index = int(seq_index_input.value.strip()) - 1
                    if seq_index < 0:
                        seq_index = None
                except ValueError:
                    pass

            return Stage(
                name=name_input.value.strip(),
                role=role_select.value if role_select.value != Select.BLANK else "",
                files=files,
                expected_gap_ps=expected_gap,
                gap_tolerance_ps=tolerance,
                notes=notes,
                sequence_base=seq_base,
                sequence_index=seq_index,
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            """Handle button presses."""
            if event.button.id == "apply-stage":
                stage = self.get_stage()
                if stage:
                    self.post_message(self.StageUpdated(stage))
            elif event.button.id == "clear-stage":
                self.load_stage(None)


    class ExportModal(ModalScreen[Optional[str]]):
        """Modal for exporting the manifest."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state

        def compose(self) -> ComposeResult:
            with Container(id="export-modal"):
                yield Label("Export Protocol Manifest", id="export-title")
                yield Rule()

                yield Label("Export Format:", classes="input-label")
                yield Select(
                    [("YAML (.yaml)", "yaml"), ("JSON (.json)", "json"),
                     ("TOML (.toml)", "toml"), ("CSV (.csv)", "csv")],
                    id="export-format",
                    value="yaml",
                )

                yield Label("Filename:", classes="input-label")
                yield Input(id="export-filename", placeholder="manifest.yaml", value="manifest.yaml")

                yield Rule()
                yield Label("Path Format:", classes="section-label")
                with Horizontal(classes="path-options"):
                    yield RadioSet(
                        RadioButton("Use absolute paths (full file paths)", id="abs-paths", value=True),
                        RadioButton("Use relative paths (relative to base directory)", id="rel-paths"),
                        id="path-type",
                    )

                yield Rule()
                yield Label("Preview (first 3 stages):", id="preview-label")
                yield ScrollableContainer(
                    Static(id="export-preview"),
                    id="preview-container",
                )

                yield Rule()
                with Horizontal(classes="button-row"):
                    yield Button("Export", id="do-export", variant="primary")
                    yield Button("Cancel", id="cancel-export", variant="default")

        def on_mount(self) -> None:
            self.update_preview()
            # Focus the filename input
            self.query_one("#export-filename", Input).focus()

        def on_select_changed(self, event: Select.Changed) -> None:
            """Update filename extension when format changes."""
            if event.select.id == "export-format":
                filename_input = self.query_one("#export-filename", Input)
                current = filename_input.value
                base = current.rsplit(".", 1)[0] if "." in current else current
                filename_input.value = f"{base}.{event.value}"
            self.update_preview()

        def update_preview(self) -> None:
            """Update the export preview."""
            format_select = self.query_one("#export-format", Select)
            path_type = self.query_one("#path-type", RadioSet)
            use_absolute = path_type.pressed_index == 0

            manifest = self.state.to_manifest(use_absolute_paths=use_absolute)

            preview = self.query_one("#export-preview", Static)

            fmt = format_select.value
            if fmt == "yaml" and YAML_AVAILABLE:
                preview.update(yaml.safe_dump({"stages": manifest}, sort_keys=False))
            elif fmt == "json":
                preview.update(json.dumps(manifest, indent=2))
            elif fmt == "toml":
                lines = []
                for stage in manifest[:3]:  # Show first 3 stages
                    lines.append("[[stages]]")
                    for k, v in list(stage.items())[:5]:
                        lines.append(f'{k} = {json.dumps(v)}')
                    lines.append("")
                if len(manifest) > 3:
                    lines.append(f"# ... and {len(manifest) - 3} more stages")
                preview.update("\n".join(lines))
            elif fmt == "csv":
                preview.update("name,stage_role,prmtop,mdin,mdout,mdcrd,inpcrd\n...")
            else:
                preview.update(json.dumps(manifest, indent=2))

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "do-export":
                format_select = self.query_one("#export-format", Select)
                filename_input = self.query_one("#export-filename", Input)
                path_type = self.query_one("#path-type", RadioSet)
                use_absolute = path_type.pressed_index == 0

                filename = filename_input.value.strip()
                if not filename:
                    filename = f"manifest.{format_select.value}"

                filepath = os.path.join(self.state.base_directory, filename)

                try:
                    fmt = format_select.value
                    if fmt == "yaml":
                        self.state.export_yaml(filepath, use_absolute)
                    elif fmt == "json":
                        self.state.export_json(filepath, use_absolute)
                    elif fmt == "toml":
                        self.state.export_toml(filepath, use_absolute)
                    elif fmt == "csv":
                        self.state.export_csv(filepath, use_absolute)

                    self.dismiss(filepath)
                except Exception as e:
                    self.notify(f"Export failed: {e}", severity="error")

            elif event.button.id == "cancel-export":
                self.dismiss(None)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class GlobalSettingsModal(ModalScreen[None]):
        """Modal for configuring global protocol settings."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state

        def compose(self) -> ComposeResult:
            with Container(id="settings-modal"):
                yield Label("Global Protocol Settings", id="settings-title")
                yield Rule()

                yield Label("Global Topology (prmtop):", classes="input-label")
                yield Input(
                    id="global-prmtop",
                    placeholder="Path to global topology file (used by all stages without their own)",
                    value=self.state.global_prmtop or "",
                )

                yield Label("HMR Topology (optional):", classes="input-label")
                yield Input(
                    id="hmr-prmtop",
                    placeholder="Path to Hydrogen Mass Repartitioning topology file",
                    value=self.state.hmr_prmtop or "",
                )

                yield Rule()
                yield Label("Options:", classes="section-label")

                with Horizontal(classes="checkbox-row"):
                    yield RadioButton(
                        "Auto-link restart files between consecutive stages",
                        id="auto-restart",
                        value=self.state.auto_link_restarts,
                    )

                yield Rule()

                yield Static(
                    "[dim]Tip: Select a .prmtop file from the file tree to quickly assign it here.[/]",
                    classes="help-text",
                )

                yield Rule()
                with Horizontal(classes="button-row"):
                    yield Button("Apply", id="apply-settings", variant="primary")
                    yield Button("Cancel", id="cancel-settings", variant="default")

        def on_mount(self) -> None:
            """Focus the first input on mount."""
            self.query_one("#global-prmtop", Input).focus()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "apply-settings":
                prmtop_input = self.query_one("#global-prmtop", Input)
                hmr_input = self.query_one("#hmr-prmtop", Input)
                auto_restart = self.query_one("#auto-restart", RadioButton)

                self.state.global_prmtop = prmtop_input.value.strip() or None
                self.state.hmr_prmtop = hmr_input.value.strip() or None
                self.state.auto_link_restarts = auto_restart.value

                self.dismiss(None)

            elif event.button.id == "cancel-settings":
                self.dismiss(None)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class SequenceModal(ModalScreen[Optional[List[Stage]]]):
        """Modal for creating stages from a sequence."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            sequence_base: str,
            stems: List[str],
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state
            self.sequence_base = sequence_base
            self.stems = stems

        def compose(self) -> ComposeResult:
            with Container(id="sequence-modal"):
                yield Label(f"Create Stages from Sequence: {self.sequence_base}", id="seq-title")
                yield Rule()

                yield Label(f"Found {len(self.stems)} files in sequence:")

                with ScrollableContainer(id="seq-list-container"):
                    for stem in self.stems[:10]:
                        yield Label(f"  - {stem}")
                    if len(self.stems) > 10:
                        yield Label(f"  ... and {len(self.stems) - 10} more")

                yield Rule()

                with Horizontal(classes="seq-row"):
                    yield Label("Stage Role:", classes="label")
                    yield Select(
                        [(r, r) for r in [""] + STAGE_ROLES],
                        id="seq-role",
                        allow_blank=True,
                    )

                yield Rule()
                with Horizontal(classes="button-row"):
                    yield Button("Create All", id="create-all", variant="primary")
                    yield Button("Cancel", id="cancel-seq", variant="default")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "create-all":
                role_select = self.query_one("#seq-role", Select)
                role = role_select.value if role_select.value != Select.BLANK else ""
                stages = self.state.create_stages_from_sequence(self.sequence_base, role)
                self.dismiss(stages)
            elif event.button.id == "cancel-seq":
                self.dismiss(None)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class AutoGenerateModal(ModalScreen[Optional[int]]):
        """Modal for auto-generating stages from discovered file groups."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
            ("a", "select_all", "Select All"),
            ("n", "select_none", "Select None"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            folder_path: Optional[str] = None,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state
            self.folder_path = folder_path
            self.selected_stems: Set[str] = set()
            self._stem_info: List[Tuple[str, Dict[str, str], str]] = []

        def compose(self) -> ComposeResult:
            with Container(id="folder-modal"):
                title = "Auto-Generate Stages"
                if self.folder_path:
                    title += f" from {Path(self.folder_path).name}"
                yield Label(title, id="folder-title")
                yield Rule()

                yield Label("Select file groups to create stages from:", classes="section-label")
                yield Static(
                    "[dim]Each group contains related files (mdin, mdout, mdcrd, etc.) with the same base name.[/]",
                    classes="help-text",
                )

                yield ScrollableContainer(
                    Vertical(id="stem-list"),
                    id="stem-list-container",
                )

                yield Rule()

                with Horizontal(classes="folder-stats"):
                    yield Static(id="selection-count")
                    yield Static(id="role-breakdown")

                yield Rule()

                yield Label("Default role for stages without inferred role:", classes="input-label")
                yield Select(
                    [("Auto-detect", ""), ("Minimization", "minimization"),
                     ("Heating", "heating"), ("Equilibration", "equilibration"),
                     ("Production", "production")],
                    id="default-role",
                    value="",
                )

                yield Rule()
                with Horizontal(classes="button-row"):
                    yield Button("Select All", id="select-all", variant="default")
                    yield Button("Select None", id="select-none", variant="default")
                    yield Button("Generate Stages", id="generate", variant="primary")
                    yield Button("Cancel", id="cancel-folder", variant="error")

        def on_mount(self) -> None:
            self._populate_stems()
            self._update_stats()

        def _populate_stems(self) -> None:
            """Populate the stem list with discovered file groups."""
            container = self.query_one("#stem-list", Vertical)

            discovered = self.state.get_discovered_files()
            existing_names = {s.name for s in self.state.stages}

            self._stem_info = []

            for stem, files in sorted(discovered.items()):
                # Filter by folder if specified
                if self.folder_path:
                    sample_path = next(
                        (v for k, v in files.items() if not k.startswith("_")), ""
                    )
                    if not sample_path.startswith(
                        os.path.relpath(self.folder_path, self.state.base_directory)
                    ):
                        continue

                # Skip already created stages
                if stem in existing_names:
                    continue

                # Get file types in this group
                file_types = [k for k in files.keys() if not k.startswith("_")]
                inferred_role = infer_stage_role_from_path(stem) or ""

                self._stem_info.append((stem, files, inferred_role))

                # Create checkbox row
                files_str = ", ".join(sorted(file_types))
                role_str = f"[{inferred_role}]" if inferred_role else "[dim]no role[/]"

                checkbox = RadioButton(
                    f"{stem[:40]} ({files_str}) {role_str}",
                    id=f"stem-{stem.replace('/', '_').replace('.', '_')}",
                    value=False,
                )
                container.mount(checkbox)

            if not self._stem_info:
                container.mount(
                    Static("[dim]No new file groups found. All discovered groups are already stages.[/]")
                )

        def _update_stats(self) -> None:
            """Update selection statistics."""
            count = len(self.selected_stems)
            total = len(self._stem_info)
            self.query_one("#selection-count", Static).update(
                f"Selected: {count}/{total} groups"
            )

            # Count by role
            role_counts: Dict[str, int] = {}
            for stem, _, role in self._stem_info:
                if stem in self.selected_stems:
                    r = role or "unknown"
                    role_counts[r] = role_counts.get(r, 0) + 1

            if role_counts:
                breakdown = ", ".join(f"{r}: {c}" for r, c in sorted(role_counts.items()))
                self.query_one("#role-breakdown", Static).update(f"Roles: {breakdown}")
            else:
                self.query_one("#role-breakdown", Static).update("")

        def on_radio_button_changed(self, event: RadioButton.Changed) -> None:
            """Handle checkbox changes."""
            if event.radio_button.id and event.radio_button.id.startswith("stem-"):
                stem_key = event.radio_button.id[5:].replace("_", "/").replace("_", ".")
                # Find the actual stem
                for stem, _, _ in self._stem_info:
                    if stem.replace("/", "_").replace(".", "_") == event.radio_button.id[5:]:
                        if event.value:
                            self.selected_stems.add(stem)
                        else:
                            self.selected_stems.discard(stem)
                        break
                self._update_stats()

        def action_select_all(self) -> None:
            """Select all stems."""
            for stem, _, _ in self._stem_info:
                self.selected_stems.add(stem)
            self._refresh_checkboxes()
            self._update_stats()

        def action_select_none(self) -> None:
            """Deselect all stems."""
            self.selected_stems.clear()
            self._refresh_checkboxes()
            self._update_stats()

        def _refresh_checkboxes(self) -> None:
            """Refresh checkbox states."""
            for stem, _, _ in self._stem_info:
                checkbox_id = f"stem-{stem.replace('/', '_').replace('.', '_')}"
                try:
                    checkbox = self.query_one(f"#{checkbox_id}", RadioButton)
                    checkbox.value = stem in self.selected_stems
                except Exception:
                    pass

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "select-all":
                self.action_select_all()
            elif event.button.id == "select-none":
                self.action_select_none()
            elif event.button.id == "generate":
                self._generate_stages()
            elif event.button.id == "cancel-folder":
                self.dismiss(None)

        def _generate_stages(self) -> None:
            """Generate stages from selected stems."""
            if not self.selected_stems:
                self.notify("No groups selected", severity="warning")
                return

            default_role_select = self.query_one("#default-role", Select)
            default_role = default_role_select.value if default_role_select.value != Select.BLANK else ""

            count = 0
            for stem, files, inferred_role in self._stem_info:
                if stem not in self.selected_stems:
                    continue

                role = inferred_role or default_role
                stage = self.state.create_stage_from_stem(stem, role)
                if stage:
                    count += 1

            self.dismiss(count)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class PrmtopAssignmentModal(ModalScreen[Optional[str]]):
        """Modal for assigning prmtop files to global settings or a stage."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            prmtop_path: str,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state
            self.prmtop_path = prmtop_path

        def compose(self) -> ComposeResult:
            rel_path = os.path.relpath(self.prmtop_path, self.state.base_directory)
            with Container(id="prmtop-modal"):
                yield Label("Assign Topology File", id="prmtop-title")
                yield Rule()

                yield Label(f"Selected: [bold]{Path(self.prmtop_path).name}[/]")
                yield Label(f"Path: {rel_path}", classes="prmtop-path")

                yield Rule()
                yield Label("Assign this topology file as:", classes="section-label")

                with Vertical(id="prmtop-options"):
                    yield Button(
                        "Global Prmtop (default for all stages)",
                        id="assign-global",
                        variant="primary",
                    )
                    yield Button(
                        "HMR Prmtop (Hydrogen Mass Repartitioning)",
                        id="assign-hmr",
                        variant="primary",
                    )
                    yield Button(
                        "Stage Prmtop (set in stage editor)",
                        id="assign-stage",
                        variant="default",
                    )

                yield Rule()
                yield Button("Cancel", id="cancel-prmtop", variant="error")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            rel_path = os.path.relpath(self.prmtop_path, self.state.base_directory)
            if event.button.id == "assign-global":
                self.state.global_prmtop = rel_path
                self.dismiss("global")
            elif event.button.id == "assign-hmr":
                self.state.hmr_prmtop = rel_path
                self.dismiss("hmr")
            elif event.button.id == "assign-stage":
                self.dismiss("stage")
            elif event.button.id == "cancel-prmtop":
                self.dismiss(None)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class SearchModal(ModalScreen[Optional[str]]):
        """Modal for searching/filtering files."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
        ]

        def __init__(
            self,
            state: ProtocolState,
            name: Optional[str] = None,
            id: Optional[str] = None,
            classes: Optional[str] = None,
        ):
            super().__init__(name=name, id=id, classes=classes)
            self.state = state
            self.results: List[str] = []

        def compose(self) -> ComposeResult:
            with Container(id="search-modal"):
                yield Label("Search Files", id="search-title")
                yield Rule()

                with Horizontal(classes="search-row"):
                    yield Label("Filter:", classes="label")
                    yield Input(id="search-input", placeholder="Enter search pattern...")

                with Horizontal(classes="search-row"):
                    yield Label("File type:", classes="label")
                    yield Select(
                        [("All", "all")] + [(t, t) for t in FILE_EXTENSIONS.keys()],
                        id="type-filter",
                        value="all",
                    )

                yield Rule()
                yield Label("Results:", id="results-label")
                yield ScrollableContainer(
                    OptionList(id="search-results"),
                    id="results-container",
                )

                yield Rule()
                with Horizontal(classes="button-row"):
                    yield Button("Select", id="select-result", variant="primary")
                    yield Button("Close", id="close-search", variant="default")

        def on_mount(self) -> None:
            self.update_results()

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "search-input":
                self.update_results()

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id == "type-filter":
                self.update_results()

        def update_results(self) -> None:
            """Update search results based on filter."""
            search_input = self.query_one("#search-input", Input)
            type_filter = self.query_one("#type-filter", Select)
            results_list = self.query_one("#search-results", OptionList)

            pattern = search_input.value.lower()
            file_type = type_filter.value

            results_list.clear_options()
            self.results = []

            for stem, files in self.state.get_discovered_files().items():
                if pattern and pattern not in stem.lower():
                    continue

                for ftype, path in files.items():
                    if ftype.startswith("_"):
                        continue
                    if file_type != "all" and ftype != file_type:
                        continue

                    display = f"[{ftype}] {stem}"
                    results_list.add_option(Option(display, id=path))
                    self.results.append(path)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "select-result":
                results_list = self.query_one("#search-results", OptionList)
                if results_list.highlighted is not None:
                    option = results_list.get_option_at_index(results_list.highlighted)
                    self.dismiss(option.id)
                else:
                    self.dismiss(None)
            elif event.button.id == "close-search":
                self.dismiss(None)

        def action_cancel(self) -> None:
            self.dismiss(None)


    class AmberMetaTUI(App[None]):
        """Main TUI application for building simulation protocol manifests."""

        TITLE = "AmberMeta Protocol Builder"
        SUB_TITLE = "Interactive Manifest Creator"

        CSS = """
        Screen {
            layout: grid;
            grid-size: 2 1;
            grid-columns: 1fr 2fr;
        }

        #left-panel {
            width: 100%;
            height: 100%;
            min-width: 30;
            border: solid green;
        }

        #right-panel {
            width: 100%;
            height: 100%;
            min-width: 50;
            layout: vertical;
        }

        #file-tree {
            height: 100%;
            min-width: 25;
        }

        #stage-panel {
            height: 50%;
            min-height: 10;
            border: solid blue;
        }

        #stage-header {
            text-align: center;
            text-style: bold;
            background: $primary-darken-2;
            padding: 0 1;
        }

        #editor-panel {
            height: 50%;
            min-height: 15;
            border: solid cyan;
            overflow-y: auto;
        }

        #stage-table {
            height: 100%;
            min-width: 40;
        }

        .editor-row {
            height: 3;
            margin: 0 1;
        }

        .editor-row Label {
            width: 18;
            min-width: 15;
        }

        .editor-row Input {
            width: 1fr;
            min-width: 20;
        }

        .editor-row Select {
            width: 1fr;
            min-width: 20;
        }

        .section-label {
            margin-top: 1;
            text-style: bold;
        }

        .file-label {
            width: 15;
        }

        .button-row {
            height: 3;
            margin-top: 1;
            align: center middle;
        }

        .button-row Button {
            margin: 0 1;
        }

        #editor-title {
            text-align: center;
            text-style: bold;
        }

        /* Modal styles */
        ModalScreen {
            align: center middle;
        }

        #export-modal, #settings-modal, #sequence-modal, #search-modal, #prmtop-modal, #folder-modal {
            width: 80%;
            height: auto;
            max-height: 90%;
            min-width: 60;
            border: thick $primary;
            background: $surface;
            padding: 1 2;
        }

        #export-title, #settings-title, #seq-title, #search-title, #prmtop-title, #folder-title {
            text-align: center;
            text-style: bold;
            margin-bottom: 1;
        }

        .export-row, .settings-row, .seq-row, .search-row {
            height: 3;
            margin: 0 1;
        }

        .export-row Label, .settings-row Label, .seq-row Label, .search-row Label {
            width: auto;
            min-width: 25;
        }

        .export-row Input, .settings-row Input {
            width: 1fr;
        }

        /* Prmtop assignment modal */
        #prmtop-options {
            margin: 1 0;
        }

        #prmtop-options Button {
            width: 100%;
            margin: 1 0;
        }

        .prmtop-path {
            color: $text-muted;
            margin-bottom: 1;
        }

        /* RadioSet and RadioButton fixes */
        RadioSet {
            width: 100%;
            height: auto;
            layout: vertical;
        }

        RadioButton {
            width: 100%;
            min-width: 40;
            padding: 0 1;
        }

        .path-options {
            height: auto;
            margin: 1 0;
        }

        .path-options RadioSet {
            width: 100%;
        }

        /* Input labels that appear above inputs */
        .input-label {
            margin-top: 1;
            text-style: bold;
            width: 100%;
        }

        .help-text {
            margin: 1 0;
        }

        .checkbox-row {
            height: auto;
            margin: 1 0;
        }

        /* Improve Select width in modals */
        #export-modal Select, #settings-modal Select, #folder-modal Select {
            width: 100%;
        }

        #export-modal Input, #settings-modal Input, #folder-modal Input {
            width: 100%;
        }

        /* Auto-generate modal */
        #stem-list-container {
            height: 20;
            border: solid $primary-darken-2;
            margin: 1 0;
        }

        #stem-list {
            padding: 1;
        }

        #stem-list RadioButton {
            width: 100%;
            height: auto;
            margin: 0;
        }

        .folder-stats {
            height: 2;
            margin: 1 0;
        }

        .folder-stats Static {
            width: 50%;
        }

        /* Help text */
        .help-text-small {
            color: $text-muted;
            margin: 0 1;
            height: 2;
        }

        #preview-container, #seq-list-container, #results-container {
            height: 15;
            border: solid $primary-darken-2;
            margin: 1 0;
        }

        #export-preview {
            padding: 1;
        }

        /* Status bar */
        #status-bar {
            dock: bottom;
            height: 1;
            background: $primary-darken-2;
        }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit"),
            Binding("ctrl+s", "save_session", "Save Session"),
            Binding("ctrl+o", "load_session", "Load Session"),
            Binding("ctrl+e", "export", "Export"),
            Binding("ctrl+g", "global_settings", "Settings"),
            Binding("ctrl+f", "search", "Search"),
            Binding("ctrl+a", "auto_generate", "Auto-Gen"),
            Binding("ctrl+z", "undo", "Undo"),
            Binding("ctrl+y", "redo", "Redo"),
            Binding("ctrl+n", "new_stage", "New Stage"),
            Binding("delete", "delete_stage", "Delete Stage"),
            Binding("ctrl+up", "move_up", "Move Up"),
            Binding("ctrl+down", "move_down", "Move Down"),
        ]

        def __init__(
            self,
            directory: str,
            name: Optional[str] = None,
        ):
            super().__init__()
            self.state = ProtocolState(directory)
            self.current_stage_index: int = -1
            self._pending_prmtop_path: Optional[str] = None  # For stage prmtop assignment

        def compose(self) -> ComposeResult:
            yield Header()

            with Container(id="left-panel"):
                yield FilteredFileTree(self.state.base_directory, id="file-tree")

            with Container(id="right-panel"):
                with Container(id="stage-panel"):
                    yield Label("Stages", id="stage-header")
                    yield StageList(self.state, id="stage-list")

                with Container(id="editor-panel"):
                    yield StageEditor(id="stage-editor")

            yield Footer()

        async def on_mount(self) -> None:
            """Initialize the application."""
            self.notify("Discovering simulation files...")
            self.state.discover_files(recursive=True)

            files_count = len(self.state.get_discovered_files())
            seq_count = len(self.state.get_sequences())

            self.notify(f"Found {files_count} file groups, {seq_count} sequences")

        def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
            """Handle file tree selection."""
            if event.node.data:
                path = Path(event.node.data)

                # Folder selection - offer auto-generate
                if path.is_dir():
                    self.push_screen(
                        AutoGenerateModal(self.state, str(path)),
                        self.on_auto_generate_complete
                    )
                    return

                if path.is_file():
                    file_type = get_file_type(str(path))

                    # Special handling for prmtop files - offer global assignment
                    if file_type == "prmtop":
                        self._pending_prmtop_path = str(path)
                        self.push_screen(
                            PrmtopAssignmentModal(self.state, str(path)),
                            self.on_prmtop_assigned
                        )
                        return

                    # Check if this is part of a sequence
                    stem = path.stem
                    for base, stems in self.state.get_sequences().items():
                        if any(stem.startswith(s.rsplit("/", 1)[-1].rsplit(".", 1)[0]) for s in stems):
                            self.push_screen(
                                SequenceModal(self.state, base, stems),
                                self.on_sequence_created
                            )
                            return

                    # Create single stage
                    rel_path = os.path.relpath(str(path), self.state.base_directory)
                    stem_path = str(Path(rel_path).with_suffix(""))

                    if stem_path in self.state.get_discovered_files():
                        stage = self.state.create_stage_from_stem(stem_path)
                        if stage:
                            self.refresh_stages()
                            self.notify(f"Created stage: {stage.name}")
                    else:
                        # Manual file assignment
                        if file_type:
                            editor = self.query_one("#stage-editor", StageEditor)
                            file_input = editor.query_one(f"#file-{file_type}", Input)
                            file_input.value = rel_path
                            self.notify(f"Set {file_type}: {rel_path}")

        def on_sequence_created(self, stages: Optional[List[Stage]]) -> None:
            """Handle sequence creation result."""
            if stages:
                self.refresh_stages()
                self.notify(f"Created {len(stages)} stages from sequence")

        def on_prmtop_assigned(self, result: Optional[str]) -> None:
            """Handle prmtop assignment result."""
            if result == "global":
                self.notify(f"Set global prmtop: {self.state.global_prmtop}")
            elif result == "hmr":
                self.notify(f"Set HMR prmtop: {self.state.hmr_prmtop}")
            elif result == "stage":
                # Set in stage editor
                if self._pending_prmtop_path:
                    rel_path = os.path.relpath(
                        self._pending_prmtop_path, self.state.base_directory
                    )
                    editor = self.query_one("#stage-editor", StageEditor)
                    file_input = editor.query_one("#file-prmtop", Input)
                    file_input.value = rel_path
                    self.notify(f"Set stage prmtop: {rel_path}")
            self._pending_prmtop_path = None

        def on_stage_list_stage_selected(self, message: StageList.StageSelected) -> None:
            """Handle stage selection."""
            self.current_stage_index = message.index
            editor = self.query_one("#stage-editor", StageEditor)
            editor.load_stage(message.stage)

        def on_stage_editor_stage_updated(self, message: StageEditor.StageUpdated) -> None:
            """Handle stage update from editor."""
            if self.current_stage_index >= 0:
                self.state.update_stage(self.current_stage_index, message.stage)
                self.refresh_stages()
                self.notify(f"Updated stage: {message.stage.name}")
            else:
                self.state.add_stage(message.stage)
                self.refresh_stages()
                self.notify(f"Added stage: {message.stage.name}")

        def refresh_stages(self) -> None:
            """Refresh the stage list display."""
            stage_list = self.query_one("#stage-list", StageList)
            stage_list.refresh_stages()

        def action_quit(self) -> None:
            """Quit the application."""
            self.exit()

        def action_export(self) -> None:
            """Open export modal."""
            if not self.state.stages:
                self.notify("No stages to export", severity="warning")
                return
            self.push_screen(ExportModal(self.state), self.on_export_complete)

        def on_export_complete(self, result: Optional[str]) -> None:
            """Handle export completion."""
            if result:
                self.notify(f"Exported to: {result}")

        def action_global_settings(self) -> None:
            """Open global settings modal."""
            self.push_screen(GlobalSettingsModal(self.state))

        def action_search(self) -> None:
            """Open search modal."""
            self.push_screen(SearchModal(self.state), self.on_search_result)

        def action_auto_generate(self) -> None:
            """Open auto-generate stages modal."""
            self.push_screen(AutoGenerateModal(self.state), self.on_auto_generate_complete)

        def on_auto_generate_complete(self, result: Optional[int]) -> None:
            """Handle auto-generate completion."""
            if result is not None and result > 0:
                self.refresh_stages()
                self.notify(f"Created {result} stages automatically")

        def on_search_result(self, result: Optional[str]) -> None:
            """Handle search result selection."""
            if result:
                rel_path = os.path.relpath(result, self.state.base_directory)
                file_type = get_file_type(result)
                if file_type:
                    editor = self.query_one("#stage-editor", StageEditor)
                    file_input = editor.query_one(f"#file-{file_type}", Input)
                    file_input.value = rel_path
                    self.notify(f"Selected {file_type}: {rel_path}")

        def action_undo(self) -> None:
            """Undo the last action."""
            description = self.state.undo()
            if description:
                self.refresh_stages()
                self.notify(f"Undid: {description}")
            else:
                self.notify("Nothing to undo", severity="warning")

        def action_redo(self) -> None:
            """Redo the last undone action."""
            description = self.state.redo()
            if description:
                self.refresh_stages()
                self.notify(f"Redid: {description}")
            else:
                self.notify("Nothing to redo", severity="warning")

        def action_new_stage(self) -> None:
            """Create a new empty stage."""
            self.current_stage_index = -1
            editor = self.query_one("#stage-editor", StageEditor)
            editor.load_stage(None)
            self.query_one("#stage-name", Input).focus()

        def action_delete_stage(self) -> None:
            """Delete the currently selected stage."""
            if self.current_stage_index >= 0:
                stage_name = self.state.stages[self.current_stage_index].name
                self.state.remove_stage(self.current_stage_index)
                self.current_stage_index = -1
                self.refresh_stages()
                editor = self.query_one("#stage-editor", StageEditor)
                editor.load_stage(None)
                self.notify(f"Deleted stage: {stage_name}")
            else:
                self.notify("No stage selected", severity="warning")

        def action_move_up(self) -> None:
            """Move the selected stage up."""
            if self.current_stage_index > 0:
                self.state.move_stage(self.current_stage_index, self.current_stage_index - 1)
                self.current_stage_index -= 1
                self.refresh_stages()

        def action_move_down(self) -> None:
            """Move the selected stage down."""
            if 0 <= self.current_stage_index < len(self.state.stages) - 1:
                self.state.move_stage(self.current_stage_index, self.current_stage_index + 1)
                self.current_stage_index += 1
                self.refresh_stages()

        def action_save_session(self) -> None:
            """Save the current session."""
            path = os.path.join(self.state.base_directory, ".ambermeta_session.json")
            self.state.save_session(path)
            self.notify(f"Session saved to: {path}")

        def action_load_session(self) -> None:
            """Load a saved session."""
            path = os.path.join(self.state.base_directory, ".ambermeta_session.json")
            if os.path.exists(path):
                try:
                    self.state = ProtocolState.load_session(path)
                    self.state.discover_files(recursive=True)
                    self.refresh_stages()
                    self.notify("Session loaded")
                except Exception as e:
                    self.notify(f"Failed to load session: {e}", severity="error")
            else:
                self.notify("No saved session found", severity="warning")


def run_tui(directory: str) -> None:
    """Run the TUI application.

    Parameters
    ----------
    directory:
        Base directory for the simulation files.
    """
    if not TEXTUAL_AVAILABLE:
        raise ImportError(
            "Textual is required for the TUI. Install with: pip install ambermeta[tui]"
        )

    app = AmberMetaTUI(directory)
    app.run()


__all__ = [
    "run_tui",
    "ProtocolState",
    "Stage",
    "TEXTUAL_AVAILABLE",
]
