# Electrode design map implementation plan

**Goal:** Export FBC6-3 design geometry and a user-confirmed 1–420 ID inspection view independently of runtime control.

**Architecture:** One standalone offline script, importing existing pure layout/polygon helpers. Fail-closed source profile and one-to-one binding; exact Gerber vertices retained. SVG and PNG are engineering inspection artifacts, not new manuscript figures.

**Tech stack:** Python standard library, installed Shapely and Pillow; unittest. Inline execution, no commits/push/worktree reset.

## Steps

- [x] Add `tests/test_electrode_design_map.py` with synthetic fixtures for mm parsing, unsupported arcs/units/clear polarity/transforms, invalid polygons, explicit user confirmation, complete bijection, record-order independence, missing/duplicate candidates and exports refusing overwrite.
- [x] Run `python -m unittest tests.test_electrode_design_map -v`; observe missing module RED.
- [x] Implement `scripts/build_electrode_design_map.py`: `parse_regions`, `bind_regions`, `build`, and engineering SVG/PNG export. Reuse `dmf.layout` and pure `_grid_polygon`/`polygon_centroid` for reference matching/comparison, never create fake image calibration.
- [x] Add frozen `configs/electrode_design_fbc6_3.json` with source SHA, user-confirmed orientation/evidence, raw top-left core center and matching tolerances.
- [x] Run 8 new tests GREEN, build into a new chapter directory, inspect the full view and peripheral details; validate all420 IDs/15287 vertices/areas against source and template code.
- [x] Run compileall, complete unittest (574:573pass/1optional skip,125.275s) and seven independent chain checks; original174 hashes unchanged.
- [x] Deliver source/units/coordinates/version/provenance JSON/CSV/SVG/PNG with clear user-confirmed vs physically verified status. No change to configs/electrode_map.yaml or Fig.2-4; no commit/push.
