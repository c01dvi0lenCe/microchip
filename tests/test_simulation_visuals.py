import unittest
from types import SimpleNamespace

from controllers.canvas_controller import CanvasControllerMixin
from controllers.simulation_controller import SimulationControllerMixin
from dmf import MultiDropletAssignment, SimulatedCamera, DropletDetector, SimulatedDroplet
from dmf.layout import SIDE_RESERVOIR_LARGE, SIDE_RESERVOIR_SMALL


PALETTE = ["#1852C2", "#B23A48", "#7651A8", "#007B83", "#B87412", "#4E7A2E", "#2F5F9A", "#7D4F2A"]


class RecordingCanvas:
    def __init__(self):
        self.lines = []
        self.texts = []
        self.ovals = []

    def create_line(self, *coordinates, **options):
        self.lines.append((coordinates, options))

    def create_text(self, *coordinates, **options):
        self.texts.append((coordinates, options))

    def create_oval(self, *coordinates, **options):
        self.ovals.append((coordinates, options))


class VisualHarness(CanvasControllerMixin, SimulationControllerMixin):
    OP_MULTI = "multi"

    def __init__(self, assignments):
        self.multi_assignments = assignments
        self.loaded_reservoirs = {a.source for a in assignments}
        self.initial_droplet_cells = set()
        self.multi_droplet_colors = PALETTE
        self.multi_source_colors = {}
        self.multi_droplet_source_colors = {}
        self.multi_droplet_visible = [True] * len(assignments)
        self.operation_var = SimpleNamespace(get=lambda: self.OP_MULTI)
        self.multi_step_index = 0
        self.sim_droplets = [SimulatedDroplet(a.path[0]) for a in assignments]
        self.matrix_canvas = RecordingCanvas()

    def _grid_geometry(self):
        return 10, 10, 400, 400, 20

    @staticmethod
    def _scheduled_cell_at(path, step):
        return path[min(step, len(path) - 1)]


class SimulationVisualTests(unittest.TestCase):
    def test_camera_perimeter_pads_fit_inside_board_and_touch_the_outlet(self):
        camera = SimulatedCamera(frame_size=(520, 520), margin_px=6, layout_padding_cells=2.2)
        left, top = camera.grid_origin_px
        pitch = camera.cell_size_px
        for cell in SIDE_RESERVOIR_LARGE | SIDE_RESERVOIR_SMALL:
            x0, y0, x1, y1 = camera._cell_bbox_px(cell)
            self.assertGreaterEqual(x0, left - 2.2 * pitch - 1)
            self.assertGreaterEqual(y0, top - 2.2 * pitch - 1)
            self.assertLessEqual(x1, left + 22.2 * pitch + 1)
            self.assertLessEqual(y1, top + 22.2 * pitch + 1)
            expected = pitch * (1.15 if cell in SIDE_RESERVOIR_LARGE else 0.85)
            self.assertAlmostEqual(x1 - x0, expected, delta=1)
        large = camera._cell_bbox_px((-3, 6))
        small = camera._cell_bbox_px((-1, 6))
        self.assertEqual(large[3], small[1])

    def test_source_color_survives_visibility_filter_reordering_and_replan(self):
        a = (-3, 6)
        b = (-3, 13)
        assignments = [
            MultiDropletAssignment(1, a, (3, 3), [(2, 3), (3, 3)], [(2, 3), (3, 3)]),
            MultiDropletAssignment(2, b, (3, 9), [(2, 9), (3, 9)], [(2, 9), (3, 9)]),
            MultiDropletAssignment(3, a, (3, 5), [(2, 5), (3, 5)], [(2, 5), (3, 5)]),
        ]
        app = VisualHarness(assignments)
        app._capture_multi_source_colors()
        colors = [app._multi_assignment_color(i) for i in range(3)]
        self.assertEqual(colors[0], colors[2])
        self.assertNotEqual(colors[0], colors[1])
        app.multi_droplet_visible = [False, True, True]
        self.assertEqual(app._camera_droplet_colors(), [app._hex_to_rgb(c) for c in colors[1:]])
        assignments[2].source = (8, 8)
        app.multi_assignments = [assignments[2], assignments[1], assignments[0]]
        self.assertEqual(app._multi_assignment_color(0), colors[2])

    def test_current_schedule_controls_one_move_arrow_or_wait(self):
        moving = [(3, 3), (3, 4), (3, 4), (4, 4)]
        queued = [None, None, (10, 10), (10, 11)]
        app = VisualHarness([
            MultiDropletAssignment(1, (3, 3), (4, 4), [(3, 3), (3, 4), (4, 4)], moving),
            MultiDropletAssignment(2, (10, 10), (10, 11), [(10, 10), (10, 11)], queued),
        ])
        app.multi_droplet_visible[1] = False
        app._draw_multi_action_arrows()
        self.assertEqual(len(app.matrix_canvas.lines), 1)
        coords, options = app.matrix_canvas.lines[0]
        self.assertGreater(coords[2], coords[0])
        self.assertEqual(coords[3], coords[1])
        self.assertEqual(options["fill"], app._multi_assignment_color(0))
        app.multi_step_index = 1
        app.sim_droplets[0].reset((3, 4))
        app.matrix_canvas = RecordingCanvas()
        app._draw_multi_action_arrows()
        self.assertEqual(app.matrix_canvas.lines, [])
        self.assertEqual([o["text"] for _, o in app.matrix_canvas.texts], ["W"])
        app._draw_position_marker((3, 4), PALETTE[0])
        app._draw_position_text((3, 4), "1")
        oval = app.matrix_canvas.ovals[-1][0]
        text = app.matrix_canvas.texts[-1][0]
        self.assertEqual(text, ((oval[0] + oval[2]) / 2, (oval[1] + oval[3]) / 2))

    def test_paper_camera_detects_all_source_colors_without_background_false_positives(self):
        camera = SimulatedCamera(frame_size=(520, 520), margin_px=6, layout_padding_cells=2.2)
        detector = DropletDetector(camera)
        plain = camera.render((0, 0), hide_droplet=True, path=[(5, 5)], paper_style=True)
        x, y = camera.grid_position_to_pixel((5, 5))
        self.assertEqual(tuple(plain[y, x]), (255, 255, 255))
        positions = [(2, 2), (2, 5), (2, 8), (2, 11), (8, 2), (8, 5), (8, 8), (8, 11)]
        context = dict(
            loaded_reservoirs=SIDE_RESERVOIR_LARGE, path=positions,
            active_cells=positions, target_shape_cells=positions, paper_style=True,
        )
        frame = camera.render((0, 0), hide_droplet=True, **context)
        self.assertEqual(detector.detect_all(frame), [])
        rgb = [tuple(bytes.fromhex(color[1:])) for color in PALETTE]
        frame = camera.render((0, 0), droplet_positions=positions, droplet_colors=rgb, **context)
        self.assertEqual({d.cell for d in detector.detect_all(frame)}, set(positions))


if __name__ == "__main__":
    unittest.main()
