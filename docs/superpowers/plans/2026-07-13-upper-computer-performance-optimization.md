# Upper-Computer Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove simulation and planning UI stalls while preserving all visual-arrival, scheduling-safety, and hardware-protocol behavior.

**Architecture:** Keep the existing controller mixins and DMF planning modules. Reduce simulation-only pixel work, coalesce UI rendering, bound the Tk log, move only multi-droplet planning computation to a single background job, and precompute pull-risk neighborhoods used by the scheduler.

**Tech Stack:** Python 3, Tkinter, NumPy, OpenCV, Pillow, `threading`, `unittest`.

---

### Task 1: Reduce simulated vision cost without changing detection semantics

**Files:**
- Modify: `tests/test_dmf_simulation.py`
- Modify: `tests/test_main_controller.py`
- Modify: `dmf/vision.py`
- Modify: `app_controller.py`

- [x] **Step 1: Write failing detector-equivalence and controller-resolution tests**

Add tests that assert the color mask includes a boundary color whose squared RGB distance equals the tolerance squared, excludes the next color outside the boundary, and that `STM32MatrixController.sim_camera.frame_size == (520, 520)`.

```python
def test_color_mask_uses_exact_squared_euclidean_boundary(self):
    color = np.array(DROPLET_DETECTION_RGB[0], dtype=np.uint8)
    frame = np.array([[color, color]], dtype=np.uint8)
    frame[0, 0, 0] = min(255, int(color[0]) + DROPLET_DETECTION_TOLERANCE)
    frame[0, 1, 0] = min(255, int(color[0]) + DROPLET_DETECTION_TOLERANCE + 1)
    mask = DropletDetector._droplet_color_mask(frame)
    self.assertTrue(mask[0, 0])
    self.assertFalse(mask[0, 1])

def test_controller_uses_preview_sized_simulation_frame(self):
    self.assertEqual(self.app.sim_camera.frame_size, (520, 520))
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_dmf_simulation.DmfSimulationTests.test_color_mask_uses_exact_squared_euclidean_boundary tests.test_main_controller.MainControllerLayoutTests.test_controller_uses_preview_sized_simulation_frame -v`

Expected: the resolution assertion fails with `(720, 720)`; the mask test exercises the current square-root implementation before replacement.

- [x] **Step 3: Implement exact squared-distance masking and 520 px simulation**

In `DropletDetector._droplet_color_mask`, replace `sqrt(sum(diff * diff)) <= tolerance` with `sum(diff * diff) <= tolerance**2`, retaining `int32`. Construct `SimulatedCamera` with `(520, 520)` in `app_controller.py`.

- [x] **Step 4: Run focused tests and the timing harness**

Run the two focused tests and a 50-iteration render/detect timing harness. Expected: tests PASS and mean render/detect time below 70 ms.

- [ ] **Step 5: Commit (waiting for user confirmation)**

```powershell
git add app_controller.py dmf/vision.py tests/test_dmf_simulation.py tests/test_main_controller.py
git commit -m "perf: reduce simulated vision frame cost"
```

### Task 2: Coalesce redraws, bound logs, and hide irrelevant controls

**Files:**
- Modify: `tests/test_main_controller.py`
- Modify: `controllers/ui_controller.py`
- Modify: `controllers/hardware_runtime.py`
- Modify: `controllers/simulation_controller.py`
- Modify: `controllers/common.py`

- [x] **Step 1: Write failing UI behavior tests**

Add tests for: hardware mode hides `sim_param_row`; simulation mode restores it; the manual page has no obstacle tool; hardware automatic mode labels the obstacle tool `屏蔽故障电极`; one moving manual tick calls `_draw_matrix_canvas` only through the rate-limited camera path; and inserting more than the configured log limit trims old lines.

```python
def test_hardware_mode_hides_simulation_parameter_row(self):
    self.app.mode_var.set("实物")
    self.app._update_mode_ui()
    self.root.update_idletasks()
    self.assertFalse(self.app.sim_param_row.winfo_ismapped())

def test_manual_motion_tick_does_not_redraw_before_camera_render(self):
    self.app._update_manual_droplet_motion = lambda _dt: True
    calls = []
    self.app._draw_matrix_canvas = lambda: calls.append("draw")
    self.app._render_sim_camera_frame = lambda force_display=False: None
    self.app._manual_simulation_loop()
    self.assertEqual(calls, [])
```

- [x] **Step 2: Run focused UI tests and verify RED**

Run the new `MainControllerLayoutTests` methods. Expected: missing `sim_param_row` attribute or still-mapped row, duplicate redraw, unbounded log, and unchanged hardware label failures.

- [x] **Step 3: Implement the minimal UI changes**

- Store the row as `self.sim_param_row`.
- Add `_update_simulation_control_visibility()` and invoke it from `_update_mode_ui()`.
- Keep the debug row collapsed when changing modes.
- In hardware automatic mode expose the obstacle entry as `屏蔽故障电极`; the manual page remains unchanged and has no automatic tools.
- Remove the explicit `_draw_matrix_canvas()` call from `_manual_simulation_loop()` before `_render_sim_camera_frame()`.
- Add `MAX_LOG_LINES` and `LOG_TRIM_BATCH`; trim the oldest batch only when the limit is exceeded.

- [x] **Step 4: Run focused and controller tests**

Run: `python -m unittest tests.test_main_controller -v`

Expected: all controller tests PASS.

- [ ] **Step 5: Commit (waiting for user confirmation)**

```powershell
git add controllers/common.py controllers/ui_controller.py controllers/hardware_runtime.py controllers/simulation_controller.py tests/test_main_controller.py
git commit -m "perf: coalesce UI updates and hide simulation controls"
```

### Task 3: Dispatch multi-droplet planning without blocking Tk

**Files:**
- Create: `controllers/planning_job.py`
- Modify: `controllers/operation_planning.py`
- Modify: `controllers/ui_controller.py`
- Modify: `controllers/task_control.py`
- Modify: `app_controller.py`
- Create: `tests/test_planning_job.py`
- Modify: `tests/test_main_controller.py`

- [x] **Step 1: Write failing planning-job tests**

Define the desired `PlanningJobRunner` API in tests. Verify that `submit()` returns immediately, rejects a second active job, posts success/error through the provided UI scheduler, and ignores a stale generation.

```python
runner = PlanningJobRunner(post_to_ui=lambda callback: callbacks.append(callback))
accepted = runner.submit(generation=3, work=lambda: result, on_success=success.append, on_error=errors.append)
self.assertTrue(accepted)
self.assertFalse(runner.submit(generation=3, work=lambda: result, on_success=success.append, on_error=errors.append))
runner.join_for_test(timeout=1.0)
callbacks.pop()()
self.assertEqual(success, [result])
```

- [x] **Step 2: Run planning-job tests and verify RED**

Run: `python -m unittest tests.test_planning_job -v`

Expected: import failure because `controllers.planning_job` does not exist.

- [x] **Step 3: Implement the single-worker runner**

Create a focused class using one daemon `threading.Thread`, a lock-protected active flag, monotonically increasing generation, `post_to_ui`, and a test-only join method. The worker must never access Tk.

- [x] **Step 4: Refactor multi planning into snapshot, compute, and apply seams**

- `_capture_multi_plan_request()` validates UI state and returns immutable sources, targets, obstacles, capacities, and generation.
- `_compute_multi_plan(request)` calls `build_multi_droplet_assignments` without touching UI state.
- `_apply_multi_plan(request, assignments)` installs results only when the generation still matches, then updates status, logs, canvas, and camera.
- `request_plan_path()` dispatches multi planning and calls existing synchronous `plan_path()` for other operations.
- Bind the `规划路径` button to `request_plan_path`.
- When `开始闭环` needs an unplanned multi task, request planning and start only from the successful UI callback.
- Restore button state after success, error, or stale discard.

- [x] **Step 5: Add controller integration tests and verify RED/GREEN**

Test that the planning button dispatch returns in under 100 ms with a blocking fake computation, duplicate clicks are ignored, stale results do not replace assignments, and successful completion updates the controller on the queued UI callback.

Run: `python -m unittest tests.test_planning_job tests.test_main_controller -v`

Expected after implementation: PASS.

- [ ] **Step 6: Commit (waiting for user confirmation)**

```powershell
git add controllers/planning_job.py controllers/operation_planning.py controllers/ui_controller.py controllers/task_control.py app_controller.py tests/test_planning_job.py tests/test_main_controller.py
git commit -m "perf: run multi-droplet planning off the UI thread"
```

### Task 4: Reduce repeated scheduler pull-risk work

**Files:**
- Modify: `tests/test_dmf_simulation.py`
- Modify: `dmf/planning/geometry.py`
- Modify: `dmf/planning/scheduler.py`

- [x] **Step 1: Write a failing pull-risk lookup test**

Expose `pull_risk_neighbors(cell)` from `geometry.py`. Test core, edge, reservoir, symmetry, and exact equivalence with `in_pull_risk_zone` across every pair in `LAYOUT_CELLS`.

```python
for left in LAYOUT_CELLS:
    neighbors = pull_risk_neighbors(left)
    for right in LAYOUT_CELLS:
        self.assertEqual(right in neighbors, in_pull_risk_zone(left, right))
```

- [x] **Step 2: Run the new test and verify RED**

Expected: import failure because `pull_risk_neighbors` is missing.

- [x] **Step 3: Implement immutable precomputed neighborhoods**

Build a module-level mapping from every layout cell to a `frozenset` of valid cells in its 3 x 3 pull-risk region. Replace repeated scheduler `in_pull_risk_zone(a, b)` calls with `b in pull_risk_neighbors(a)` only where both values are known cells.

- [x] **Step 4: Run safety tests and compare representative planning**

Run: `python -m unittest tests.test_dmf_simulation tests.test_closed_loop_chain -v`.

Then time cold CSE, ZJU, and CSC planning five times. Expected: every schedule remains valid and mean planning time does not regress; retain the optimization only if it produces a measurable improvement.

- [ ] **Step 5: Commit (waiting for user confirmation)**

```powershell
git add dmf/planning/geometry.py dmf/planning/scheduler.py tests/test_dmf_simulation.py
git commit -m "perf: precompute scheduler pull-risk neighborhoods"
```

### Task 5: Final verification and status documentation

**Files:**
- Modify: `docs/implementation-status.md`
- Modify: `docs/superpowers/plans/2026-07-13-upper-computer-performance-optimization.md`

- [x] **Step 1: Record measured before/after results**

Add a concise performance section with simulated frame processing, UI planning dispatch latency, and total representative planning times. State that these are software measurements on the current PC and not physical droplet timing.

- [x] **Step 2: Run all required verification**

```powershell
python -m compileall -q main.py app_controller.py controllers dmf simulation validation
python -m unittest discover -s tests -v
python -m validation.closed_loop_chain.run_validation
```

Expected: compile exit 0, all unit tests PASS, and move/mix/split/loop/CSE/ZJU/CSC PASS.

- [x] **Step 3: Run the performance harness again**

Expected: 520 x 520 simulated render/detect mean below 70 ms and multi-plan dispatch under 100 ms. Report total planning time separately from UI responsiveness.

- [ ] **Step 4: Commit documentation (waiting for user confirmation)**

```powershell
git add docs/implementation-status.md docs/superpowers/plans/2026-07-13-upper-computer-performance-optimization.md
git commit -m "docs: record upper-computer performance results"
```
