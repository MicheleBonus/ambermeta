# GUI pass

This pass needs the Playwright plugin's MCP tools (`browser_navigate`, `browser_snapshot` and the rest). If they are not available in this session, write "GUI not audited: Playwright tools unavailable" in the report and stop this pass. Reading the React source is not a substitute for driving the app.

## Start the server

Start it in the background from the fixture directory, then wait until it answers:

```bash
sh am gui run --no-browser --port 8799                       # run_in_background
until curl -sf http://127.0.0.1:8799/api/document >/dev/null; do sleep 1; done
```

To audit `hole/` or `replicas/`, stop the server and start it again on that directory. Stop it when the pass is done.

## Drive it

- `browser_navigate` to `http://127.0.0.1:8799`.
- Find elements with `browser_snapshot` (the accessibility tree), and act with `browser_click`, `browser_type`, `browser_drag` and `browser_press_key`.
- After every action, check `browser_console_messages` for errors and `browser_network_requests` for any 4xx or 5xx response.
- Take a `browser_take_screenshot` of each state you report on. Save them next to the report and name them in its `observed:` line.
- Use `browser_resize` at 1440×900 and 1024×768. The app is desktop-only by design, so don't report layouts narrower than that.

## Workflows

Walk these in order on `run/`, following the descriptions in `docs/gui.md`:
1. Discover. Read the suggestions tray: is each item explained, and can it be undone?
2. Select a step, then a phase. Read the inspector's peek and details tabs.
3. Assign a file by dragging it from the file panel onto a step slot.
4. Rename a step and change a phase's role.
5. Validate. Does each finding say what to do, and does clicking it jump to the step?
6. Undo and Redo, by button and by keyboard shortcut.
7. Save, then Open the saved file. Is the document the same?
8. Plan.
9. Open `bad/v1.yaml`, `bad/broken.yaml` and `bad/missing.yaml`. Is each error readable, and does the app recover without a reload?

Then discover `hole/` (the missing-run ghost card and its suggestion) and `replicas/` (the lineage proposal strip, Accept, and Define replicas…).

Finish with one keyboard-only pass of workflows 1 to 7 using Tab, Enter, Space and Escape. Can each one be completed, and is focus always visible?

Report GUI findings with `area: gui`. In `repro:`, write the steps a person would take, then the tool calls that reproduced them.
