# Real-map Geometry Simulation Implementation Plan

> **For agentic workers:** Execute inline with test-first checkpoints; no delegation or commits in this task.

**Goal:** Build an independent 420-electrode geometry-constrained demonstration using diameter3.6–4.0mm and spacer0.8mm.

**Architecture:** Reuse read-only design-map validation and EvidenceWindow. Separate map/footprint/world, observable camera/features, demo orchestration and static export/replay. Preserve existing simulation and physical-control modules.

**Tech Stack:** Python, NumPy, OpenCV, Shapely, Matplotlib, standalone HTML/SVG replay of persisted data.

### 1. Protect inputs and test the missing contract
- [ ] Snapshot existing code/config hashes and chapter-result file metadata before changes.
- [ ] Create tests/test_chapter2_geometry_sim.py. Test real-map identity, diameter semantics, zero-overlap blocking, finite-speed delay, duplicate activation, pending rejection, observational features and runner persistence.
- [ ] Run `python -m unittest tests.test_chapter2_geometry_sim -v`; expect missing module before implementation.

### 2. Implement independent geometry/world
- [ ] Create dmf/chapter2_geometry_sim/model.py and __init__.py with strict config, exact Gerber polygons, circular footprint, intersection and delayed finite-speed world.
- [ ] New world must never import controllers/hardware or modify existing map. Errors reject nonfinite/out-of-range settings.
- [ ] Validate zero overlap and response timing against deterministic fixtures.

### 3. Implement observed camera and demonstration
- [ ] Create observation.py and runner.py. Rasterize actual footprint at exposure into persisted Mask; calculate centroid and eta/rho from Mask only.
- [ ] Demo controller is separately named, uses position+dwell EvidenceWindow; log oldG eligibility as diagnostic, not F.
- [ ] Save world.csv, observations.csv, events.csv, all observed PNG masks, manifest and replay payload. Refuse pre-existing output directory.

### 4. Draw map and provide replay
- [ ] Create export.py; draw all420 actual polygons in mm, essential corner/perimeter/route IDs. Export vector SVG/PDF and600dpi PNG using established Python plotting backend.
- [ ] Create offline player from persisted payload: full map, local view, internal contour vs actual camera Mask, task/action/timing and common timeline controls.
- [ ] Create run_chapter2_geometry_sim.py and configs/chapter2_geometry_sim.json. Record all assumed timing and shapes as uncalibrated demonstration settings.
- [ ] Generate one deterministic demonstration with a new development seed, not old formal seeds. Inspect rendered map/player and persisted values.

### 5. Verify and hand off
- [ ] Run new tests and old geometry/design/evidence regressions; compile and independent software chain.
- [ ] Run PDF text/collision checks and visually inspect map export at readable size.
- [ ] Recheck baseline hashes/metadata, write checks.json and implementation/limitations report. No new formal performance batch.
