# Web-Based GUI Guide

AmberMeta includes a modern web-based Graphical User Interface (GUI) for building protocol manifests. The GUI provides an intuitive, drag-and-drop interface for browsing simulation files, creating stages, and exporting manifests.

## Table of Contents

- [Installation](#installation)
- [Launching the GUI](#launching-the-gui)
- [Interface Overview](#interface-overview)
- [File Browser](#file-browser)
- [Stage Builder](#stage-builder)
- [Properties Panel](#properties-panel)
- [Auto-Discovery](#auto-discovery)
- [Drag and Drop](#drag-and-drop)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Session Management](#session-management)
- [Export Options](#export-options)
- [Tips and Best Practices](#tips-and-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Installation

The GUI requires additional dependencies. Install with the GUI extra:

```bash
pip install -e ".[gui]"
```

Or install dependencies directly:

```bash
pip install fastapi uvicorn aiofiles
```

The GUI frontend is pre-built and bundled with AmberMeta. No additional Node.js installation is required.

---

## Launching the GUI

### Basic Launch

```bash
# Launch in the current directory
ambermeta gui

# Launch in a specific directory
ambermeta gui /path/to/simulations
```

### Options

```bash
ambermeta gui [directory] [options]

Options:
  --port PORT     Port to run the server on (default: 8000)
  --host HOST     Host to bind to (default: 127.0.0.1)
  --no-browser    Don't automatically open browser
```

### Examples

```bash
# Launch on a different port
ambermeta gui --port 3000 /path/to/project

# Allow network access (use with caution)
ambermeta gui --host 0.0.0.0 /path/to/project

# Don't auto-open browser
ambermeta gui --no-browser /path/to/project
```

Once launched, the GUI opens automatically in your default web browser at `http://localhost:8000`.

---

## Interface Overview

The GUI is divided into three main panels:

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       AmberMeta Protocol Builder                           │
│  [Undo] [Redo]   [Save] [Load]   [Auto-Discover]   [Export]               │
├──────────────────┬────────────────────────────────┬────────────────────────┤
│                  │                                │                        │
│   File Browser   │        Stage Builder           │    Properties Panel    │
│                  │                                │                        │
│  📁 simulations/ │  ┌────────────────────────┐   │   Global Settings      │
│    📄 system.top │  │ min        Minimization │   │   ──────────────────   │
│    📄 min.mdin   │  │ 3/5 files  ✓           │   │   Global Prmtop:       │
│    📄 heat.mdin  │  └────────────────────────┘   │   [____________]       │
│  📁 production/  │         │                     │                        │
│    📄 prod_001   │         ▼                     │   HMR Prmtop:          │
│    📄 prod_002   │  ┌────────────────────────┐   │   [____________]       │
│                  │  │ heat       Heating     │   │                        │
│ [Search...]      │  │ 4/5 files  ✓           │   │   ☑ Auto-link restarts │
│                  │  └────────────────────────┘   │   ☑ Validate on export │
│                  │         │                     │   ☐ Use relative paths │
│                  │    [+ Add Stage]              │                        │
├──────────────────┴────────────────────────────────┴────────────────────────┤
│                           3 files found                                     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## File Browser

The left panel shows a directory tree of simulation files.

### File Type Icons

Files are displayed with color-coded icons indicating their type:

| Icon Color | File Type | Description |
|------------|-----------|-------------|
| Green | prmtop | Topology/parameter files (.prmtop, .parm7, .top) |
| Yellow | mdin | Input control files (.mdin, .in) |
| Cyan | mdout | Output log files (.mdout, .out) |
| Purple | mdcrd | Trajectory files (.nc, .mdcrd, .crd, .trj) |
| Blue | inpcrd | Restart/coordinate files (.rst, .rst7, .ncrst, .inpcrd) |

### Navigation

- **Click** on a directory to expand/collapse it
- **Click** on a file to drag it to a stage
- Use the **Search** box to filter files by name

### Context Menu (Right-Click)

Right-clicking on a file opens a context menu with options:

| Option | Description | Availability |
|--------|-------------|--------------|
| **Set as Global Prmtop** | Set this topology as the global default | prmtop files only |
| **Set as Global HMR Prmtop** | Set as Hydrogen Mass Repartitioning topology | prmtop files only |
| **Create Stage from This File** | Create a new stage with this file | Non-prmtop files only |
| **Auto-Discover Stages...** | Open auto-discovery for this folder | Folders only |

**Note:** Topology files (prmtop) cannot be used to create stages directly. They should be assigned as global topology or HMR topology, or assigned per-stage in the Properties Panel.

---

## Stage Builder

The center panel displays all configured stages in a vertical list.

### Header Controls

The Stage Builder header includes:

| Control | Description |
|---------|-------------|
| **Expand All / Collapse All** | Toggle button to expand or collapse all stage cards at once |
| **Add Stage** | Button to create a new empty stage |

### Stage Cards

Each stage is displayed as a card showing:

| Element | Description |
|---------|-------------|
| **Drag Handle** | Grip icon on the left for reordering |
| **Name** | Stage identifier |
| **Role Badge** | Color-coded role (Minimization, Heating, etc.) |
| **File Count** | Number of assigned files (e.g., "3/5 files") |
| **Validation Status** | ✓ (valid), ✗ (error), or ⚠ (warning) |
| **Expand Button** | Click to show file drop zones |
| **Delete Button** | Remove the stage |

### Expanded View

Click the expand button (▶) on a stage card to reveal file drop zones:

```
┌────────────────────────────────────────────────┐
│  prod_001                    Production   ✓    │
│  5/5 files                              ▼  🗑  │
├────────────────────────────────────────────────┤
│  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐  │
│  │prmtop │ │ mdin  │ │ mdout │ │ mdcrd │ │inpcrd │  │
│  │system │ │prod.. │ │prod.. │ │prod.. │ │       │  │
│  └───────┘ └───────┘ └───────┘ └───────┘ └───────┘  │
└────────────────────────────────────────────────┘
```

Drag files from the File Browser directly onto these drop zones.

### Creating Stages

**Method 1: Add Stage Button**
1. Click the "+ Add Stage" button
2. Enter a name in the dialog
3. Click "Add"

**Method 2: Drag File to Stage Builder**
1. Drag a file from the File Browser
2. Drop it in the Stage Builder area
3. A new stage is created with the filename as the stage name
4. **Auto-Grouping**: Related files with the same stem (e.g., `prod_001.mdin`, `prod_001.mdout`, `prod_001.nc`) are automatically included in the stage

**Method 3: Context Menu**
1. Right-click a file in the File Browser
2. Select "Create Stage from This File"

**Method 4: Auto-Discovery**
1. Click the "Auto-Discover" button in the toolbar
2. Select file groups to create as stages
3. Click "Create Stages"

### Reordering Stages

Drag stages by their grip handle (⋮⋮) to reorder them:
1. Click and hold the grip icon
2. Drag the stage to its new position
3. Release to drop

---

## Properties Panel

The right panel shows properties for the selected stage or global settings.

### Global Settings (No Stage Selected)

When no stage is selected, the Properties Panel shows global settings:

| Setting | Description |
|---------|-------------|
| **Global Prmtop** | Default topology for stages without their own |
| **HMR Prmtop** | Hydrogen Mass Repartitioning topology (optional) |
| **Auto-link Restarts** | Automatically link restart files between consecutive stages |
| **Validate on Export** | Run validation before exporting |
| **Use Relative Paths** | Export with relative paths instead of absolute |

### Stage Properties (Stage Selected)

When a stage is selected, edit its properties:

| Field | Description |
|-------|-------------|
| **Name** | Unique identifier (required) |
| **Role** | Dropdown: Unknown, Minimization, Heating, Equilibration, Production |
| **Topology Selection** | Choose between Normal and HMR topology (when both are set) |
| **Files** | File paths for each type (shows "(using global)" if inheriting) |
| **Expected Gap (ps)** | Expected time gap from previous stage |
| **Tolerance (ps)** | Acceptable deviation from expected gap |
| **Notes** | Documentation notes (one per line) |

### Topology Selection

When both a global prmtop and an HMR prmtop are set, stages show a topology selection option:

| Option | Description |
|--------|-------------|
| **Normal (Global)** | Use the standard global topology file |
| **HMR** | Use the Hydrogen Mass Repartitioning topology |

**Tip:** Use HMR topology for stages with timestep (dt) ≥ 0.004 ps. The GUI will show a warning if a large timestep is detected but the HMR topology is not being used.

### File Fields

Each file field shows:
- The current file path (editable)
- A clear button (✗) to remove the file
- "(using global)" indicator if using the global prmtop

### Apply/Reset

- **Apply**: Save changes to the stage
- **Reset**: Discard changes and revert to saved values

Changes are highlighted until applied.

---

## Auto-Discovery

The Auto-Discovery feature scans the file tree and groups files by their base name (filename without extension).

### Using Auto-Discovery

1. Click the **"Auto-Discover"** button in the toolbar (or press `Ctrl+A`)
2. The modal shows all discovered file groups
3. Check/uncheck groups to include
4. Click **"Create Stages"** to generate stages

### File Groups

Files are grouped by stem (base name). For example:
- `prod_001.mdin`, `prod_001.mdout`, `prod_001.nc` → **prod_001** group

Each group shows which file types are present:

```
☑ prod_001          [mdin] [mdout] [mdcrd]
☑ prod_002          [mdin] [mdout] [mdcrd]
☐ test_run          [mdin]
```

### Select All/None

Use the checkbox at the top to select or deselect all groups at once.

---

## Drag and Drop

The GUI supports intuitive drag-and-drop interactions.

### Dragging Files

1. Click and hold any file in the File Browser
2. A visual indicator shows what you're dragging
3. Drag to a drop target:
   - **Stage Builder area**: Creates a new stage with auto-grouping of related files
   - **File Drop Zone**: Assigns file to that slot

**Note:** Topology files (prmtop) cannot be dragged to create new stages. Use the context menu to set them as global or HMR topology.

### Auto-Grouping

When you drag a file to create a new stage, the GUI automatically discovers and includes related files:

- Files with the same stem (basename without extension) are grouped together
- For example, dragging `01_min.mdin` will also include `01_min.mdout`, `01_min.rst`, `01_min.nc` if they exist
- Topology files (prmtop) are excluded from auto-grouping (use global settings instead)
- You can remove unwanted files from the stage after creation

### File Type Matching

When you drag a file to a stage's drop zone:
- The file is assigned to the matching type slot (prmtop, mdin, etc.)
- Existing files in other slots are **preserved** (not overwritten)
- Only the specific slot you drop on is updated

### Visual Feedback

- **Blue highlight**: Valid drop target
- **Semi-transparent dragged item**: Shows what's being dragged
- **Drag overlay**: Shows filename during drag

---

## Keyboard Shortcuts

### Global Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+Z` | Undo last action |
| `Ctrl+Y` | Redo last undone action |
| `Ctrl+Shift+Z` | Redo (alternative) |
| `Ctrl+S` | Open Save Session dialog |
| `Ctrl+O` | Open Load Session dialog |
| `Ctrl+A` | Open Auto-Discovery modal (when not in input field) |
| `Ctrl+E` | Open Export modal |

### Modal Shortcuts

| Key | Action |
|-----|--------|
| `Escape` | Close modal/cancel |
| `Enter` | Confirm/submit (in input fields) |

---

## Session Management

### Save Session

1. Click the **"Save"** button or press `Ctrl+S`
2. Enter a filename (without extension)
3. Click **"Save"**

Sessions are saved as JSON files in the base directory.

### Load Session

1. Click the **"Load"** button or press `Ctrl+O`
2. Enter the session filename (including `.json` extension)
3. Click **"Load"**

### What's Saved

Sessions preserve:
- All configured stages with their files
- Global settings (prmtop, HMR prmtop, options)
- The base directory

### Undo/Redo

The GUI maintains an undo history:
- `Ctrl+Z`: Undo last action
- `Ctrl+Y`: Redo last undone action

Actions tracked:
- Adding stages
- Deleting stages
- Updating stage properties
- Reordering stages

---

## Export Options

### Supported Formats

| Format | Extension | Description |
|--------|-----------|-------------|
| YAML | `.yaml` | Human-readable, recommended |
| JSON | `.json` | Machine-readable, widely supported |
| TOML | `.toml` | Configuration-friendly format |
| CSV | `.csv` | Spreadsheet-compatible |

### Export Process

1. Click the **"Export"** button or press `Ctrl+E`
2. Select a format from the list
3. The file downloads automatically as `protocol.[format]`

### Path Options

Configure "Use relative paths" in Global Settings to export with:
- **Relative paths**: `production/prod_001.mdin`
- **Absolute paths**: `/home/user/simulations/production/prod_001.mdin`

---

## Tips and Best Practices

### Efficient Workflow

1. **Start with Global Settings**: Set the global prmtop first if using the same topology
2. **Use Auto-Discovery**: For large projects, auto-discover stages instead of creating manually
3. **Drag and Drop**: Faster than typing paths - drag files directly to stages
4. **Expand Stages**: Use the expand button to see all file slots at once
5. **Save Sessions**: Save your work frequently with `Ctrl+S`

### Handling Large Projects

- Use Auto-Discovery to create many stages at once
- Filter files using the search box
- Collapse directories you're not using
- Use relative paths for portability

### Common Patterns

**Single System, Multiple Production Runs:**
1. Set global prmtop
2. Click Auto-Discover
3. Select all production file groups
4. Create stages

**Manually Assigning Files:**
1. Create a new stage
2. Expand the stage card
3. Drag files from File Browser to each slot
4. Select the stage and set the role in Properties Panel

**Fixing Validation Issues:**
1. Look for ✗ or ⚠ icons on stages
2. Select the stage to see validation messages
3. Assign missing files or fix issues
4. Click Apply to save changes

---

## Troubleshooting

### GUI Won't Start

```
ImportError: fastapi not found
```

Install the GUI dependencies:
```bash
pip install ambermeta[gui]
```

### Browser Doesn't Open

Use the `--no-browser` flag and manually navigate to `http://localhost:8000`:
```bash
ambermeta gui --no-browser
```

### Port Already in Use

```
Address already in use
```

Use a different port:
```bash
ambermeta gui --port 3001
```

### Files Not Appearing

- Check that files have supported extensions (.prmtop, .mdin, .mdout, .nc, .rst7, etc.)
- Ensure file permissions allow reading
- Hidden files (starting with `.`) are not shown

### Changes Not Persisting

- Click "Apply" in the Properties Panel to save changes
- Use `Ctrl+S` to save the session
- Export the manifest before closing

### Drag and Drop Not Working

- Ensure you're dragging from a file (not a folder)
- Make sure the target stage is expanded to show drop zones
- Check that you're dropping on a valid target

---

## Comparison with TUI

| Feature | GUI | TUI |
|---------|-----|-----|
| **Interface** | Web browser | Terminal |
| **Drag and Drop** | Yes | No |
| **File Browser** | Visual tree | Text-based tree |
| **Auto-Discovery** | Modal with checkboxes | Modal with checkboxes |
| **Session Save/Load** | Built-in UI | Keyboard shortcuts |
| **Mobile Support** | Yes (responsive) | No |
| **Requirements** | Modern browser | Terminal with Unicode support |
| **Network Access** | Optional (can expose port) | Local only |

Both interfaces export the same manifest formats and produce identical output.

---

## API Endpoints

The GUI backend provides a REST API that can be used programmatically:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/files` | GET | List discovered files |
| `/api/files/metadata` | GET | Get file metadata |
| `/api/files/related/{stem}` | GET | Get related files by stem (for auto-grouping) |
| `/api/stages` | GET | List all stages |
| `/api/stages` | POST | Create a new stage |
| `/api/stages/{id}` | PUT | Update a stage |
| `/api/stages/{id}` | DELETE | Delete a stage |
| `/api/stages/reorder` | POST | Reorder stages |
| `/api/settings` | GET/PUT | Get/update global settings |
| `/api/export` | POST | Export protocol |
| `/api/validate` | POST | Validate protocol |
| `/api/session/save` | POST | Save session |
| `/api/session/load` | POST | Load session |
| `/api/sequences` | GET | Get detected sequences |

Example using curl:

```bash
# List stages
curl http://localhost:8000/api/stages

# Create a stage
curl -X POST http://localhost:8000/api/stages \
  -H "Content-Type: application/json" \
  -d '{"name": "prod_001", "role": "production"}'

# Export as YAML
curl -X POST http://localhost:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{"format": "yaml"}'
```
