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

What the harness does not do for you, learned the hard way:
- `browser_drag` (Playwright's `dragTo`) does not start a dnd-kit drag. In `browser_run_code_unsafe`, press on the source, move a few pixels, then `page.mouse.move(x, y, { steps: 25 })` to the target and release.
- Give every action in a `browser_run_code_unsafe` script a short timeout (`{ timeout: 5000 }`). The default is 30 s per action, so a loop over a few covered buttons runs past the tool's two-minute limit.
- Stopping a backgrounded `browser_run_code_unsafe` with TaskStop does not stop the script. It keeps driving the page and can leave the document in a state that looks like an app bug. Keep scripts short instead of relying on stopping them.
- A `page.once('dialog')` handler left by an earlier script fires later, for example on a `beforeunload`. Call `page.removeAllListeners('dialog')` before navigating.
- Wait for state, not for time: after Discover, poll `GET /api/document` until it has phases. A cold parse cache can take longer than a fixed wait.
- On Windows, stopping the background `sh am gui …` task leaves Python listening on the port. Find it with `Get-NetTCPConnection -LocalPort <port>`, check its command line, and stop that process.

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
