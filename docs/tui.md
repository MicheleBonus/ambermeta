# Terminal User Interface (TUI) Guide

AmberMeta includes an interactive Terminal User Interface (TUI) for building protocol manifests. The TUI provides a visual way to browse simulation files, create stages, and export manifests without writing code.

## Table of Contents

- [Installation](#installation)
- [Launching the TUI](#launching-the-tui)
- [Interface Overview](#interface-overview)
- [File Browser](#file-browser)
- [Stage List](#stage-list)
- [Stage Editor](#stage-editor)
- [Modals and Dialogs](#modals-and-dialogs)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Export Options](#export-options)
- [Session Management](#session-management)
- [Tips and Best Practices](#tips-and-best-practices)

---

## Installation

The TUI requires the `textual` library. Install with the TUI extra:

```bash
pip install -e ".[tui]"
```

Or install textual directly:

```bash
pip install textual>=0.40.0
```

---

## Launching the TUI

### Basic Launch

```bash
# Launch in the current directory
ambermeta tui

# Launch in a specific directory
ambermeta tui /path/to/simulations
```

### Options

```bash
ambermeta tui [directory] [options]

Options:
  --recursive    Enable recursive file discovery in subdirectories
  --show-all     Show all files, not just simulation-related files
```

### Examples

```bash
# Browse simulations recursively
ambermeta tui --recursive /path/to/project

# Show all files including non-simulation files
ambermeta tui --show-all /path/to/project
```

---

## Interface Overview

The TUI is divided into three main panels:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AmberMeta Protocol Builder                        │
├───────────────────┬──────────────────────────┬──────────────────────────┤
│                   │                          │                          │
│   File Browser    │      Stage List          │     Stage Editor         │
│                   │                          │                          │
│  [P] system.top   │  Name    Role    Files   │  Name: ____________      │
│  [I] min.in       │  ─────────────────────   │  Role: [production ▼]    │
│  [O] min.out      │  min     minim    3      │                          │
│  [R] min.rst      │  heat    heat     4      │  Files:                  │
│  📁 production/   │  equil   equil    5      │    prmtop: __________    │
│    [I] prod_001   │  prod    prod     5      │    mdin: ____________    │
│    [O] prod_001   │                          │    mdout: ___________    │
│    [T] prod_001   │                          │    mdcrd: ___________    │
│                   │                          │    inpcrd: __________    │
│                   │                          │                          │
│                   │                          │  Gaps:                   │
│                   │                          │    Expected: ______ ps   │
│                   │                          │    Tolerance: _____ ps   │
│                   │                          │                          │
│                   │                          │  [Apply]  [Clear]        │
├───────────────────┴──────────────────────────┴──────────────────────────┤
│ Ctrl+A: Auto-generate | Ctrl+G: Settings | Ctrl+E: Export | Q: Quit    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## File Browser

The left panel shows a directory tree of simulation files.

### File Type Icons

Files are displayed with color-coded icons indicating their type:

| Icon | Color | File Type | Description |
|------|-------|-----------|-------------|
| `[P]` | Green | prmtop | Topology/parameter files (.prmtop, .parm7, .top) |
| `[I]` | Yellow | mdin | Input control files (.mdin, .in) |
| `[O]` | Cyan | mdout | Output log files (.mdout, .out) |
| `[T]` | Magenta | mdcrd | Trajectory files (.nc, .mdcrd, .crd, .x) |
| `[R]` | Blue | inpcrd | Restart/coordinate files (.rst, .rst7, .ncrst, .inpcrd) |

### Navigation

- **Click** on a directory to expand/collapse it
- **Click** on a file to select it for actions
- **Arrow keys** to navigate the tree
- **Enter** to expand/collapse directories

### Quick Actions

**Clicking a `.prmtop` file** opens the Prmtop Assignment Modal with options:
- Set as Global Prmtop (applies to all stages)
- Set as HMR Prmtop (for hydrogen mass repartitioning)
- Add to Stage Editor (current stage being edited)

**Clicking a directory** opens the Auto-Generate Modal to create stages from files in that folder.

---

## Stage List

The center panel displays all configured stages.

### Columns

| Column | Description |
|--------|-------------|
| **Stage Name** | Unique identifier for the stage |
| **Role** | Stage type (minimization, heating, equilibration, production) |
| **Files** | Number of files assigned to this stage |
| **Order** | Global protocol order (1-based position in the workflow) |

### Interactions

- **Click** a row to select a stage for editing
- **Double-click** to edit the stage in the Stage Editor
- Selected stage is highlighted

### Stage Ordering

The "Order" column shows the global position of each stage in the simulation protocol:
- Order 1 is the first stage (typically minimization)
- The order continues sequentially through all stages
- Use Ctrl+Up/Ctrl+Down to reorder stages
- Equilibration stages should come before production stages

---

## Stage Editor

The right panel allows editing stage properties.

### Fields

| Field | Description |
|-------|-------------|
| **Name** | Unique identifier (required) |
| **Role** | Dropdown: minimization, heating, equilibration, production |
| **Files** | File paths for each type (prmtop, mdin, mdout, mdcrd, inpcrd) |
| **Expected Gap** | Expected time gap from previous stage (in picoseconds) |
| **Tolerance** | Acceptable deviation from expected gap (in picoseconds) |
| **Notes** | Documentation notes (semicolon-separated for multiple) |
| **Seq Base** | Base pattern for sequence (e.g., "prod" for prod_001) |
| **Seq Position** | 1-based position in sequence |

### Buttons

- **Apply**: Save changes to the stage (creates new or updates existing)
- **Clear**: Reset all fields to empty

### Usage

1. Enter a unique name for the stage
2. Select the appropriate role
3. Fill in file paths (can be relative or absolute)
4. Optionally configure gap expectations
5. Click "Apply" to save

---

## Modals and Dialogs

### Global Settings Modal

**Keyboard shortcut:** `Ctrl+G`

Configure protocol-wide settings:

| Setting | Description |
|---------|-------------|
| **Global Topology** | Default prmtop file for stages without their own |
| **HMR Topology** | Hydrogen Mass Repartitioning topology (optional) |
| **Auto-link Restarts** | Automatically link restart files between consecutive stages |

### Export Modal

**Keyboard shortcut:** `Ctrl+E`

Export the manifest to a file:

| Option | Description |
|--------|-------------|
| **Format** | YAML, JSON, TOML, or CSV |
| **Filename** | Output filename (auto-updates extension) |
| **Path Format** | Absolute or relative paths |
| **Preview** | Shows first 3 stages in selected format |

### Auto-Generate Modal

**Keyboard shortcut:** `Ctrl+A` or click a directory

Automatically create stages from discovered file groups:

1. **File Groups**: Shows all detected file groups (files with same base name)
2. **Selection**: Check groups to include
3. **Default Role**: Role for stages without inferred role
4. **Select All/None**: Bulk selection buttons
5. **Generate Stages**: Create stages from selected groups

Features:
- Skips groups that already have stages
- Shows inferred role for each group
- Displays file types in each group

### Prmtop Assignment Modal

**Triggered by:** Clicking a `.prmtop` file

Quickly assign topology files:

| Option | Description |
|--------|-------------|
| **Set as Global Prmtop** | Use for all stages without their own |
| **Set as HMR Prmtop** | Mark as hydrogen mass repartitioning topology |
| **Add to Stage Editor** | Add to the prmtop field of current stage |

### File Load Choice Modal

**Triggered by:** Selecting a file that's part of a detected sequence

When you click on a file that belongs to a numeric sequence (e.g., `prod_001.mdin`), you'll be asked how to proceed:

| Option | Description |
|--------|-------------|
| **Load Single File** | Create a stage for just this one file |
| **Load Entire Sequence** | Open the Sequence Modal to load all files in the sequence |

This gives you flexibility to:
- Add individual files without loading the whole sequence
- Work incrementally on large simulation sets
- Fix or modify individual stages

### Sequence Modal

**Triggered by:** Choosing "Load Entire Sequence" from File Load Choice, or via context menu

Create multiple stages from a detected sequence:

- Shows all files in the sequence
- Choose role for all stages
- Creates stages maintaining sequence order

---

## Keyboard Shortcuts

### Global Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+A` | Open Auto-Generate modal |
| `Ctrl+G` | Open Global Settings modal |
| `Ctrl+E` | Open Export modal |
| `Ctrl+S` | Save session to file |
| `Ctrl+Z` | Undo last action |
| `Ctrl+Y` | Redo last undone action |
| `Q` | Quit the TUI |
| `?` | Show help |

### Modal Shortcuts

| Key | Action |
|-----|--------|
| `Escape` | Close modal/cancel |
| `Enter` | Confirm/apply |
| `Tab` | Move to next field |
| `Shift+Tab` | Move to previous field |

### Auto-Generate Modal

| Key | Action |
|-----|--------|
| `A` | Select all groups |
| `N` | Select no groups |

---

## Export Options

### Supported Formats

| Format | Extension | Requirements |
|--------|-----------|--------------|
| YAML | `.yaml`, `.yml` | PyYAML package |
| JSON | `.json` | Built-in |
| TOML | `.toml` | None |
| CSV | `.csv` | Built-in |

### Path Options

- **Absolute Paths**: Full system paths (e.g., `/home/user/simulations/system.prmtop`)
- **Relative Paths**: Relative to base directory (e.g., `system.prmtop`)

### Export Process

1. Press `Ctrl+E` to open Export modal
2. Select format from dropdown
3. Enter filename (extension auto-updates)
4. Choose path format
5. Review preview
6. Click "Export"

File is saved to the base directory.

---

## Session Management

### Save Session

Press `Ctrl+S` to save your current work to a JSON file. This preserves:
- All configured stages
- Global prmtop settings
- HMR prmtop settings
- Auto-link preferences

### Load Session

Load a previous session using Python:

```python
from ambermeta import ProtocolState

state = ProtocolState.load_session("my_session.json")
```

Or create a new TUI session programmatically:

```python
from ambermeta import run_tui

run_tui("/path/to/simulations", recursive=True)
```

### Undo/Redo

The TUI maintains an undo history (up to 50 actions):

- `Ctrl+Z`: Undo last action
- `Ctrl+Y`: Redo last undone action

Actions tracked:
- Adding stages
- Removing stages
- Updating stages
- Moving stages
- Changing global prmtop
- Creating stages from sequences

---

## Tips and Best Practices

### Efficient Workflow

1. **Start with Global Settings**: Set the global prmtop first if using the same topology throughout
2. **Use Auto-Generate**: For large projects, auto-generate stages from folders
3. **Verify Sequences**: Check that numeric sequences are detected correctly
4. **Configure Gaps**: Set expected gaps for stages that have known timing gaps
5. **Export and Validate**: Export manifest and run `ambermeta plan` to validate

### Handling Large Projects

- Use `--recursive` to discover files in subdirectories
- Auto-generate stages by folder to organize logically
- Use pattern filtering in the CLI for subset analysis

### Common Patterns

**Single System, Multiple Production Runs:**
1. Set global prmtop
2. Navigate to production folder
3. Click folder to auto-generate
4. Set role to "production"

**Multiple Systems:**
1. Create stages manually for each system
2. Set prmtop per-stage
3. Use different names/prefixes per system

**Debugging Validation Issues:**
1. Export manifest
2. Run `ambermeta plan --manifest manifest.yaml -v`
3. Review validation notes
4. Update stages as needed

### Terminal Requirements

The TUI works best in terminals that support:
- 256 colors
- Unicode characters
- Minimum 80 columns width
- Mouse input (optional but helpful)

Recommended terminals:
- iTerm2 (macOS)
- Windows Terminal
- GNOME Terminal
- Alacritty
- Kitty

---

## Troubleshooting

### TUI Won't Start

```
ImportError: textual not found
```

Install the TUI dependency:
```bash
pip install textual>=0.40.0
```

### Display Issues

**Characters not rendering correctly:**
- Ensure terminal supports Unicode
- Try a different terminal emulator
- Set `TERM=xterm-256color`

**Layout broken on narrow terminal:**
- Increase terminal width to at least 80 columns
- The TUI has responsive breakpoints for different widths

### File Discovery Issues

**Files not appearing:**
- Check file extensions match supported types
- Try `--show-all` to see all files
- Verify file permissions

**Sequences not detected:**
- Ensure files follow pattern: `name_001.ext`, `name_002.ext`
- Other patterns supported: `name.001`, `name001`, `name-001`

### Export Issues

**YAML export fails:**
```
ImportError: pyyaml not installed
```

Install PyYAML:
```bash
pip install pyyaml
```

---

## API Reference

For programmatic access to TUI components:

```python
from ambermeta import (
    run_tui,           # Launch TUI
    ProtocolState,     # State management class
    Stage,             # Stage data class
    TEXTUAL_AVAILABLE, # Check if TUI is available
)

# Check TUI availability
if TEXTUAL_AVAILABLE:
    run_tui("/path/to/simulations", recursive=True)
else:
    print("TUI not available. Install with: pip install ambermeta[tui]")
```

### ProtocolState Class

```python
state = ProtocolState("/path/to/simulations")

# Discover files
state.discover_files(recursive=True)

# Get discovered data
files = state.get_discovered_files()
sequences = state.get_sequences()

# Manage stages
state.add_stage(Stage(name="prod", role="production", files={"mdin": "prod.in"}))
state.remove_stage(0)
state.move_stage(0, 1)

# Undo/redo
state.undo()
state.redo()

# Export
state.export_yaml("manifest.yaml")
state.export_json("manifest.json")
state.export_csv("manifest.csv")

# Session management
state.save_session("session.json")
loaded = ProtocolState.load_session("session.json")
```
