# AmberMeta GUI Implementation Plan

**Version**: 1.0
**Date**: 2026-01-30
**Status**: Planning Phase

## Executive Summary

This document outlines a comprehensive implementation plan for a modern graphical user interface (GUI) to complement the existing Terminal User Interface (TUI). The GUI will be a web-based application providing intuitive drag-and-drop functionality, visual sequence management, and seamless file linking for building simulation protocol manifests.

---

## Technology Recommendation

### Recommended Stack: Web-Based with Python Backend

**Frontend:**
- **Framework**: React 18+ with TypeScript
- **UI Library**: Tailwind CSS + Headless UI (or shadcn/ui)
- **Drag-and-Drop**: dnd-kit or react-beautiful-dnd
- **State Management**: Zustand or React Query
- **Build Tool**: Vite

**Backend:**
- **Framework**: FastAPI (Python)
- **Communication**: REST API + WebSocket for real-time updates
- **Bundling**: PyInstaller or similar for standalone distribution

**Alternative Options:**

| Option | Pros | Cons |
|--------|------|------|
| **Electron + React** | Desktop app, offline | Large bundle size (~150MB) |
| **Tauri + React** | Smaller bundles, Rust backend | Less mature ecosystem |
| **PyQt6/PySide6** | Native look, Python-only | Steeper learning curve, dated UX |
| **Streamlit** | Rapid prototyping | Limited customization |
| **Web-only (Flask/FastAPI)** | Universal access, lightweight | Requires browser |

**Recommended**: Web-based with FastAPI backend, launchable via `ambermeta gui` command that starts a local server and opens the browser.

---

## Core Features

### 1. File Browser Panel (Left Side)

**Layout:**
```
┌─────────────────────────────┐
│ 📁 Simulation Files         │
├─────────────────────────────┤
│ 🔍 [Search files...]        │
│ ─────────────────────────── │
│ 📁 simulations/             │
│   📁 equilibration/         │
│     📄 equil_001.mdin       │
│     📄 equil_001.mdout      │
│     📄 equil_001.nc         │
│   📁 production/            │
│     📄 prod_001.mdin        │
│     📄 prod_002.mdin        │
│   📄 system.prmtop          │
└─────────────────────────────┘
```

**Features:**
- Tree view with expandable directories
- Color-coded file type icons
- Search/filter by filename or type
- Right-click context menu:
  - "Set as Global Prmtop"
  - "Set as HMR Prmtop"
  - "Add to Current Stage"
  - "Create Stage from This File"
- Drag files directly onto stages
- Multi-select for batch operations
- Keyboard navigation (arrow keys, Enter to expand)

**File Type Visual Indicators:**

| Type | Icon | Color | Description |
|------|------|-------|-------------|
| prmtop | 🧬 | Green | Topology files |
| mdin | ⚙️ | Yellow | Input control |
| mdout | 📊 | Cyan | Output logs |
| mdcrd | 🎬 | Magenta | Trajectories |
| inpcrd | 🔄 | Blue | Restart/coords |
| folder | 📁 | Gray | Directories |

---

### 2. Stage Builder Panel (Center)

**Layout:**
```
┌─────────────────────────────────────────────────────┐
│ 🏗️ Protocol Stages                    [+ Add Stage] │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ 1️⃣ minimize                         [≡] [×]    │ │
│ │    Role: minimization                           │ │
│ │    ┌─────┬─────┬─────┬─────┬─────┐             │ │
│ │    │ 🧬  │ ⚙️  │ 📊  │ 🎬  │ 🔄  │             │ │
│ │    │prmtop│mdin │mdout│mdcrd│inpcrd             │ │
│ │    │  ✓  │  ✓  │  ✓  │  -  │  ✓  │             │ │
│ │    └─────┴─────┴─────┴─────┴─────┘             │ │
│ └─────────────────────────────────────────────────┘ │
│           ↓ (drag to reorder)                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 2️⃣ heat                             [≡] [×]    │ │
│ │    Role: heating                                │ │
│ │    Files: 4/5 assigned                          │ │
│ └─────────────────────────────────────────────────┘ │
│           ↓                                         │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 3️⃣ equil                            [≡] [×]    │ │
│ │    Role: equilibration                          │ │
│ │    Files: 5/5 assigned ✓                        │ │
│ └─────────────────────────────────────────────────┘ │
│           ↓                                         │
│ ┌─ SEQUENCE: production (3 stages) ───────────────┐ │
│ │ ┌───────────┐ ┌───────────┐ ┌───────────┐      │ │
│ │ │ prod_001  │→│ prod_002  │→│ prod_003  │      │ │
│ │ │   5/5 ✓   │ │   5/5 ✓   │ │   4/5 ⚠   │      │ │
│ │ └───────────┘ └───────────┘ └───────────┘      │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Features:**

#### Stage Cards
- Drag-and-drop reordering
- Visual indicators for file assignment status
- Expandable to show file details
- Inline role editing (dropdown)
- Delete button with confirmation
- Collapse/expand toggle

#### Sequence Grouping
- Auto-detect numeric sequences (prod_001, prod_002)
- Visual grouping with connecting arrows
- Expand/collapse sequence view
- Batch operations on sequences
- Sequence reordering as a unit

#### Drop Zones
- Highlight valid drop targets when dragging
- Visual feedback for file type compatibility
- Multi-file drop support
- Undo/redo for all operations

#### Stage Status Indicators
- ✓ Green: All required files assigned
- ⚠ Yellow: Missing optional files
- ✗ Red: Missing required files
- 🔄 Blue: Pending validation

---

### 3. Properties Panel (Right Side)

**Layout:**
```
┌─────────────────────────────┐
│ ⚙️ Stage Properties         │
├─────────────────────────────┤
│ Name: [prod_001          ]  │
│ Role: [production      ▼]   │
│ ─────────────────────────── │
│ 📁 Files                    │
│ ┌───────────────────────┐   │
│ │ 🧬 prmtop:            │   │
│ │ [system.prmtop     ] [×]│ │
│ │ 🔗 Using global        │   │
│ └───────────────────────┘   │
│ ┌───────────────────────┐   │
│ │ ⚙️ mdin:              │   │
│ │ [prod_001.in       ] [×]│ │
│ └───────────────────────┘   │
│ ... (other file types)      │
│ ─────────────────────────── │
│ 📐 Gap Settings             │
│ Expected: [0.0     ] ps     │
│ Tolerance: [0.1   ] ps      │
│ ─────────────────────────── │
│ 📝 Notes                    │
│ [                        ]  │
│ [                        ]  │
│ ─────────────────────────── │
│ [💾 Apply] [↩️ Reset]       │
└─────────────────────────────┘
```

**Features:**
- Context-sensitive (shows global settings when no stage selected)
- File input fields with:
  - Clear button
  - Browse button (opens file picker)
  - Drag-and-drop from file browser
  - Visual link indicator when using global prmtop
- Real-time validation feedback
- Auto-save with debounce
- Keyboard shortcuts for common actions

---

### 4. Global Settings Panel

**Accessible via toolbar button or menu:**

```
┌─────────────────────────────────────┐
│ 🌐 Global Protocol Settings         │
├─────────────────────────────────────┤
│ Topology Files                      │
│ ┌─────────────────────────────────┐ │
│ │ 🧬 Global Prmtop:               │ │
│ │ [system.prmtop            ] [📁]│ │
│ │ (Used by stages without own)    │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 🧬 HMR Prmtop (optional):       │ │
│ │ [system_hmr.prmtop        ] [📁]│ │
│ │ (For hydrogen mass repartition) │ │
│ └─────────────────────────────────┘ │
│ ─────────────────────────────────── │
│ Options                             │
│ [✓] Auto-link restart files         │
│ [✓] Validate on export              │
│ [ ] Use relative paths              │
│ ─────────────────────────────────── │
│ [💾 Save Settings]                  │
└─────────────────────────────────────┘
```

---

### 5. Toolbar and Actions

**Top Toolbar:**
```
┌─────────────────────────────────────────────────────────────────┐
│ AmberMeta Protocol Builder                                      │
├─────────────────────────────────────────────────────────────────┤
│ [📂 Open] [💾 Save] [📤 Export ▼] │ [↩️ Undo] [↪️ Redo] │ [⚙️]  │
└─────────────────────────────────────────────────────────────────┘
```

**Export Dropdown:**
- YAML (.yaml)
- JSON (.json)
- TOML (.toml)
- CSV (.csv)

**Keyboard Shortcuts:**

| Shortcut | Action |
|----------|--------|
| Ctrl+O | Open session |
| Ctrl+S | Save session |
| Ctrl+E | Export manifest |
| Ctrl+Z | Undo |
| Ctrl+Shift+Z | Redo |
| Delete | Delete selected stage |
| Ctrl+N | New stage |
| Ctrl+G | Global settings |

---

## Visual Design Guidelines

### Color Palette

```
Primary:     #3B82F6 (Blue-500)
Secondary:   #10B981 (Emerald-500)
Warning:     #F59E0B (Amber-500)
Error:       #EF4444 (Red-500)
Success:     #22C55E (Green-500)
Background:  #F9FAFB (Gray-50)
Surface:     #FFFFFF (White)
Text:        #111827 (Gray-900)
Muted:       #6B7280 (Gray-500)
```

### Typography

- **Headings**: Inter or system-ui
- **Body**: Inter or system-ui
- **Monospace**: JetBrains Mono or Fira Code (for file paths)

### Responsive Design

- **Desktop** (>1200px): Three-panel layout
- **Tablet** (768-1200px): Collapsible panels
- **Mobile** (<768px): Single-panel with navigation

---

## Data Model

### Stage Object

```typescript
interface Stage {
  id: string;
  name: string;
  role: 'minimization' | 'heating' | 'equilibration' | 'production' | '';
  files: {
    prmtop?: string;
    mdin?: string;
    mdout?: string;
    mdcrd?: string;
    inpcrd?: string;
  };
  expectedGapPs?: number;
  gapTolerancePs?: number;
  notes: string[];
  sequenceBase?: string;
  sequenceIndex?: number;
}
```

### Protocol State

```typescript
interface ProtocolState {
  baseDirectory: string;
  globalPrmtop?: string;
  hmrPrmtop?: string;
  autoLinkRestarts: boolean;
  stages: Stage[];
  discoveredFiles: Map<string, FileGroup>;
  sequences: Map<string, string[]>;
}
```

---

## API Endpoints

### REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/files` | List discovered files |
| GET | `/api/files/{path}` | Get file metadata |
| GET | `/api/sequences` | List detected sequences |
| GET | `/api/stages` | Get all stages |
| POST | `/api/stages` | Create stage |
| PUT | `/api/stages/{id}` | Update stage |
| DELETE | `/api/stages/{id}` | Delete stage |
| POST | `/api/stages/reorder` | Reorder stages |
| GET | `/api/protocol` | Get full protocol state |
| POST | `/api/export` | Export manifest |
| GET | `/api/settings` | Get global settings |
| PUT | `/api/settings` | Update global settings |
| POST | `/api/session/save` | Save session |
| POST | `/api/session/load` | Load session |
| POST | `/api/validate` | Validate protocol |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `file:discovered` | Server→Client | New file found |
| `stage:updated` | Server→Client | Stage changed |
| `validation:result` | Server→Client | Validation complete |
| `progress:update` | Server→Client | Long operation progress |

---

## Implementation Phases

### Phase 1: Core Infrastructure (2-3 weeks)

- [ ] Set up FastAPI backend with basic endpoints
- [ ] Create React project with Vite
- [ ] Implement basic file browser (read-only)
- [ ] Implement stage list (no drag-drop)
- [ ] Basic properties panel
- [ ] Export functionality

### Phase 2: Drag-and-Drop (1-2 weeks)

- [ ] File drag to stages
- [ ] Stage reordering
- [ ] Drop zone highlighting
- [ ] Undo/redo system

### Phase 3: Visual Enhancements (1-2 weeks)

- [ ] Sequence grouping visualization
- [ ] File type icons and colors
- [ ] Status indicators
- [ ] Responsive layout

### Phase 4: Advanced Features (2-3 weeks)

- [ ] Real-time validation
- [ ] WebSocket updates
- [ ] Keyboard shortcuts
- [ ] Session management
- [ ] Bulk operations

### Phase 5: Packaging (1 week)

- [ ] CLI integration (`ambermeta gui`)
- [ ] Auto-open browser
- [ ] Desktop packaging (optional)
- [ ] Documentation

---

## File Structure

```
ambermeta/
├── gui/
│   ├── __init__.py
│   ├── server.py           # FastAPI application
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py       # API routes
│   │   ├── websocket.py    # WebSocket handlers
│   │   └── schemas.py      # Pydantic models
│   ├── frontend/
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── main.tsx
│   │   │   ├── components/
│   │   │   │   ├── FileBrowser/
│   │   │   │   ├── StageBuilder/
│   │   │   │   ├── PropertiesPanel/
│   │   │   │   └── common/
│   │   │   ├── hooks/
│   │   │   ├── stores/
│   │   │   ├── api/
│   │   │   └── types/
│   │   └── public/
│   └── static/             # Built frontend (for distribution)
```

---

## Dependencies

### Backend (Python)

```toml
# pyproject.toml additions
[project.optional-dependencies]
gui = [
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
    "websockets>=11.0",
    "python-multipart>=0.0.6",
]
```

### Frontend (Node.js)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "@tanstack/react-query": "^5.0.0",
    "@dnd-kit/core": "^6.0.0",
    "@dnd-kit/sortable": "^7.0.0",
    "zustand": "^4.4.0",
    "lucide-react": "^0.300.0"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "@types/react": "^18.2.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

## Launch Integration

### CLI Command

```python
# cli.py addition
@cli.command()
@click.argument("directory", default=".", type=click.Path(exists=True))
@click.option("--port", default=8765, help="Server port")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
def gui(directory: str, port: int, no_browser: bool):
    """Launch the graphical user interface."""
    from ambermeta.gui import run_gui
    run_gui(directory, port=port, open_browser=not no_browser)
```

### Server Startup

```python
# gui/server.py
import webbrowser
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

def run_gui(directory: str, port: int = 8765, open_browser: bool = True):
    app = create_app(directory)

    if open_browser:
        import threading
        def open_after_delay():
            import time
            time.sleep(1)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=open_after_delay).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

---

## Testing Strategy

### Unit Tests
- Component tests with React Testing Library
- API endpoint tests with pytest

### Integration Tests
- Full workflow tests (create stages, export)
- Drag-and-drop interaction tests

### E2E Tests
- Playwright or Cypress for browser testing
- Cross-browser compatibility

---

## Future Enhancements

1. **Visualization**: Timeline view of simulation protocol
2. **Analysis Integration**: Show parsed metadata inline
3. **Templates**: Save/load protocol templates
4. **Collaboration**: Share protocol links
5. **Cloud Sync**: Sync sessions across devices
6. **Dark Mode**: Theme toggle
7. **Plugin System**: Custom validators and exporters

---

## Conclusion

This GUI implementation will provide a modern, intuitive interface for building AmberMeta simulation protocols. The web-based approach ensures cross-platform compatibility while the FastAPI backend leverages the existing Python codebase. The phased implementation allows for iterative development and user feedback.

**Next Steps:**
1. Review and approve this plan
2. Set up development environment
3. Begin Phase 1 implementation
4. Gather early user feedback
