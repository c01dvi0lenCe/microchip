# Modular DMF core with a compatibility facade

The DMF topology, planning, motion, and vision implementations are separated into focused modules, while `dmf_simulation.py` remains as a compatibility facade. This keeps existing upper-computer imports stable while improving locality and allowing later firmware and camera adapters to reuse the same core.

