# Geometry Single-Step Implementation Plan

User approved implementation inline; no delegation, commit, push or hardware operations.

1. Protect existing workspace and chapter assets with content hashes/metadata.
2. Write failing tests in tests/test_geometry_single_step.py for template area/identity, delayed overlap world, camera features, causal shadow gates, reference and persisted-run contracts.
3. Add footprint.py, single_world.py, observation.py, shadow.py, single_step.py to the independent geometry namespace; do not modify the existing circular prototype.
4. Add CLI/config, run one declarednormal264900 trial once into a new directory. All model-independent validation fixtures stay in temporary test directories and are not research trials.
5. Add read-only audit and rendering/replay modules with tests. Plot from saved CSV/Mask/polygons only; export SVG/PDF/600dpi PNG, H.264 MP4 and interactive static frame replay. Refuse final-file overwrite.
6. Run local regressions, compileall, independent software chain, PDF/layout QA and source/old-data protection checks. Report exact events and limitations; stop after this one mechanism example.
