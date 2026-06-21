import unittest

from dmf_simulation import (
    AStarPlanner,
    GRID_COLS,
    GRID_ROWS,
    RESERVOIR_CELLS,
    RESERVOIR_CONNECTIONS,
    LAYOUT_CELLS,
    DropletDetector,
    MotionProfile,
    OperationMetrics,
    SimulatedCamera,
    SimulatedDroplet,
    StepEvent,
    VisionNoiseProfile,
    build_multi_droplet_assignments,
    cell_from_electrode_id,
    detection_in_cell,
    electrode_id,
    grid_polyline_cells,
    is_reservoir_cell,
    schedule_multi_paths,
    target_merge_region_map,
)


class DmfSimulationTests(unittest.TestCase):
    def test_electrode_id_mapping_is_row_major(self):
        self.assertEqual(electrode_id(0, 0), 1)
        self.assertEqual(electrode_id(0, 19), 20)
        self.assertEqual(electrode_id(1, 0), 21)
        self.assertEqual(electrode_id(19, 19), 400)
        self.assertEqual(cell_from_electrode_id(400), (19, 19))
        reservoir = sorted(RESERVOIR_CELLS)[0]
        self.assertGreaterEqual(electrode_id(*reservoir), 401)
        self.assertIn(cell_from_electrode_id(420), RESERVOIR_CELLS)

    def test_reservoir_cells_are_twenty_edge_electrodes(self):
        self.assertEqual(len(RESERVOIR_CELLS), 20)
        for row, col in RESERVOIR_CELLS:
            self.assertTrue(row < 0 or row >= GRID_ROWS or col < 0 or col >= GRID_COLS)
            self.assertTrue(is_reservoir_cell((row, col)))

    def test_reservoir_electrode_ids_follow_pcb_cn_labels(self):
        expected = {
            (-1, 6): 401,
            (-3, 6): 402,
            (-1, 13): 403,
            (-3, 13): 404,
            (6, GRID_COLS): 405,
            (6, GRID_COLS + 2): 406,
            (13, GRID_COLS): 407,
            (13, GRID_COLS + 2): 408,
            (GRID_ROWS, 13): 409,
            (GRID_ROWS + 2, 13): 410,
            (GRID_ROWS, 6): 411,
            (GRID_ROWS + 2, 6): 412,
            (13, -1): 413,
            (13, -3): 414,
            (6, -1): 415,
            (6, -3): 416,
            (-1, -1): 417,
            (-1, GRID_COLS): 418,
            (GRID_ROWS, GRID_COLS): 419,
            (GRID_ROWS, -1): 420,
        }

        self.assertEqual({cell: electrode_id(*cell) for cell in expected}, expected)
        for cell, eid in expected.items():
            self.assertEqual(cell_from_electrode_id(eid), cell)

    def test_astar_returns_straight_path(self):
        path = AStarPlanner(rows=20, cols=20).plan((0, 0), (0, 3))
        self.assertEqual(path, [(0, 0), (0, 1), (0, 2), (0, 3)])

    def test_astar_routes_around_obstacle(self):
        path = AStarPlanner(rows=5, cols=5).plan((0, 0), (0, 2), obstacles={(0, 1)})
        self.assertTrue(path)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (0, 2))
        self.assertNotIn((0, 1), path)
        self.assertGreater(len(path), 3)

    def test_layout_planner_connects_reservoir_to_core(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        path = planner.plan((-3, 6), (2, 6))
        self.assertEqual(path[0], (-3, 6))
        self.assertIn((-1, 6), path)
        self.assertIn((0, 6), path)
        self.assertEqual(path[-1], (2, 6))

    def test_camera_does_not_draw_extra_reservoir_connector_regions(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        self.assertIsNone(camera._reservoir_connector_bbox_px((-3, 6)))
        self.assertIsNone(camera._reservoir_connector_bbox_px((-1, 6)))

    def test_camera_corner_reservoir_uses_three_l_shape_cells(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))

        rects = camera._corner_reservoir_rects_px((-1, -1))

        self.assertEqual(len(rects), 3)

    def test_camera_base_reservoirs_render_as_red_electrodes(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        frame = camera.render((5.0, 5.0), hide_droplet=True)
        bbox = camera._cell_bbox_px((-3, 6))
        self.assertIsNotNone(bbox)
        assert bbox is not None
        x0, y0, x1, y1 = bbox
        x = (x0 + x1) // 2
        y = (y0 + y1) // 2

        self.assertEqual(tuple(int(channel) for channel in frame[y, x]), (182, 91, 77))

    def test_astar_returns_empty_when_no_path_exists(self):
        planner = AStarPlanner(rows=3, cols=3)
        obstacles = {(0, 1), (1, 0), (1, 2), (2, 1)}
        self.assertEqual(planner.plan((1, 1), (0, 0), obstacles), [])

    def test_detector_maps_camera_frame_to_grid_position(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        frame = camera.render((5.0, 7.0))
        detection = detector.detect(frame)
        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertEqual(detection.cell, (5, 7))
        self.assertTrue(detection_in_cell(detection, (5, 7), tolerance_cells=0.1))

    def test_detector_returns_multiple_separated_droplets(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        frame = camera.render((0.0, 0.0), droplet_positions=[(4.0, 4.0), (12.0, 12.0)])
        detections = detector.detect_all(frame)
        cells = {detection.cell for detection in detections}
        self.assertEqual(cells, {(4, 4), (12, 12)})

    def test_detector_returns_blue_and_magenta_droplets(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        frame = camera.render(
            (0.0, 0.0),
            droplet_positions=[(4.0, 4.0), (12.0, 12.0)],
            droplet_colors=[(24, 82, 194), (178, 58, 72)],
        )
        detections = detector.detect_all(frame)
        cells = {detection.cell for detection in detections}
        self.assertEqual(cells, {(4, 4), (12, 12)})

    def test_detector_returns_droplet_on_active_electrode(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        frame = camera.render(
            (5.0, 7.0),
            active_cells={(5, 7)},
            path={(5, 7), (5, 8)},
            target_cells={(5, 9)},
            obstacles={(8, 8)},
        )

        detections = detector.detect_all(frame)
        cells = {detection.cell for detection in detections}

        self.assertEqual(cells, {(5, 7)})

    def test_detector_accepts_horizontal_ellipse_droplet(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        frame = camera.render(
            (5.0, 7.0),
            active_cells={(5, 7)},
            droplet_shapes=["horizontal_ellipse"],
        )

        detections = detector.detect_all(frame)
        cells = {detection.cell for detection in detections}

        self.assertEqual(cells, {(5, 7)})

    def test_detector_returns_all_multi_droplet_palette_colors(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)
        positions = [(3.0, 3.0), (3.0, 10.0), (8.0, 4.0), (8.0, 14.0), (14.0, 6.0), (14.0, 15.0)]
        colors = [
            (24, 82, 194),
            (178, 58, 72),
            (155, 77, 202),
            (0, 123, 131),
            (199, 125, 0),
            (78, 122, 46),
        ]
        frame = camera.render((0.0, 0.0), droplet_positions=positions, droplet_colors=colors)

        detections = detector.detect_all(frame)
        cells = {detection.cell for detection in detections}

        self.assertEqual(cells, {(3, 3), (3, 10), (8, 4), (8, 14), (14, 6), (14, 15)})

    def test_motion_profile_can_delay_or_stall_droplet_motion(self):
        droplet = SimulatedDroplet((3, 3), speed_cells_per_sec=4.0)
        delayed = MotionProfile(name="test", response_delay_s=0.2)

        droplet.update_towards((3, 4), 0.1, motion_profile=delayed)
        self.assertEqual(droplet.position, (3.0, 3.0))

        droplet.update_towards((3, 4), 0.4, motion_profile=MotionProfile(name="stuck", stuck_probability=1.0))
        self.assertEqual(droplet.position, (3.0, 3.0))

    def test_vision_noise_profile_can_hide_or_jitter_detections(self):
        camera = SimulatedCamera(rows=20, cols=20, frame_size=(640, 640))
        detector = DropletDetector(camera)

        hidden = camera.render((5.0, 7.0), noise_profile=VisionNoiseProfile(name="hidden", drop_frame_rate=1.0))
        self.assertEqual(detector.detect_all(hidden), [])

        jittered = camera.render((5.0, 7.0), noise_profile=VisionNoiseProfile(name="jitter", jitter_cells=0.25))
        detection = detector.detect(jittered)
        self.assertIsNotNone(detection)
        assert detection is not None
        self.assertGreater(abs(detection.grid_position[0] - 5.0) + abs(detection.grid_position[1] - 7.0), 0.05)

    def test_operation_metrics_records_step_events_and_csv_row(self):
        metrics = OperationMetrics(operation="move")
        metrics.record_event(
            StepEvent(
                stage="DRIVE_TARGET",
                target_cell=(3, 4),
                detected_cell=(3, 3),
                on_cells=((3, 4),),
                off_cells=((3, 3),),
                duration_s=0.4,
                action="advance",
            )
        )
        metrics.record_replan()
        metrics.record_dropout()
        metrics.record_stall()

        row = metrics.to_csv_row()

        self.assertEqual(row["operation"], "move")
        self.assertEqual(row["total_steps"], 1)
        self.assertEqual(row["replan_count"], 1)
        self.assertEqual(row["dropout_count"], 1)
        self.assertEqual(row["stall_count"], 1)
        self.assertEqual(row["electrode_switch_count"], 2)

    def test_target_polyline_cells_are_rectilinear_and_ordered(self):
        cells = grid_polyline_cells([(2, 2), (2, 5), (4, 5)])
        self.assertEqual(cells, [(2, 2), (2, 3), (2, 4), (2, 5), (3, 5), (4, 5)])

    def test_multi_assignments_fill_every_target_shape_cell(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        shape = grid_polyline_cells([(10, 8), (10, 12)])
        assignments = build_multi_droplet_assignments([(-3, 6)], shape, planner)
        self.assertEqual(len(assignments), len(shape))
        self.assertEqual({assignment.target for assignment in assignments}, set(shape))
        self.assertTrue(all(assignment.source == (-3, 6) for assignment in assignments))

    def test_single_reservoir_is_limited_to_five_generated_droplets(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        five_targets = grid_polyline_cells([(10, 8), (10, 12)])
        six_targets = grid_polyline_cells([(10, 8), (10, 13)])

        self.assertEqual(len(build_multi_droplet_assignments([(-3, 6)], five_targets, planner)), 5)
        self.assertEqual(build_multi_droplet_assignments([(-3, 6)], six_targets, planner), [])

    def test_higher_capacity_reservoir_is_selected_before_lower_capacity_one(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        low_capacity_neck = (-1, 6)
        high_capacity_pool = (-3, 6)

        assignments = build_multi_droplet_assignments(
            [low_capacity_neck, high_capacity_pool],
            [(0, 6)],
            planner,
            source_capacity={low_capacity_neck: 1, high_capacity_pool: 5},
        )

        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].source, high_capacity_pool)

    def test_single_reservoir_emits_next_droplet_after_previous_leaves(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        assignments = build_multi_droplet_assignments([(-3, 6)], [(4, 6), (5, 6), (6, 6)], planner)
        starts = [assignment.scheduled_path.index((-3, 6)) for assignment in assignments]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), len(starts))

    def test_multi_droplet_assignments_have_safe_schedules(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        sources = [(-3, 6), (GRID_ROWS + 2, 13), (6, -3), (13, GRID_COLS + 2)]
        shape = [(6, 6), (6, 13), (13, 13), (13, 6)]
        assignments = build_multi_droplet_assignments(sources, shape, planner)
        self.assertEqual(len(assignments), 4)
        schedules = [assignment.scheduled_path for assignment in assignments]
        max_len = max(len(schedule) for schedule in schedules)
        for step in range(max_len):
            current = [schedule[step] if step < len(schedule) else schedule[-1] for schedule in schedules]
            previous = [schedule[step - 1] if 0 <= step - 1 < len(schedule) else schedule[0] for schedule in schedules]
            for i, first in enumerate(current):
                for j, second in enumerate(current[i + 1 :], start=i + 1):
                    if first is None or second is None:
                        continue
                    self.assertNotEqual(first, second)
                    self.assertFalse(previous[i] == second and first == previous[j])

    def test_multi_scheduler_avoids_diagonal_risk_during_transport(self):
        paths = [
            [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)],
            [(2, 2), (1, 2), (1, 3), (2, 3)],
        ]

        schedules = schedule_multi_paths(paths)

        self.assertEqual(len(schedules), 2)
        max_len = max(len(schedule) for schedule in schedules)
        for step in range(max_len):
            first = schedules[0][step] if step < len(schedules[0]) else schedules[0][-1]
            second = schedules[1][step] if step < len(schedules[1]) else schedules[1][-1]
            if first is None or second is None:
                continue
            both_at_goals = first == paths[0][-1] and second == paths[1][-1]
            if not both_at_goals:
                self.assertGreater(max(abs(first[0] - second[0]), abs(first[1] - second[1])), 1)

    def test_dense_letter_targets_are_split_into_parallel_rounds(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        sources = [(-3, 6), (-3, 13), (6, -3), (13, -3)]
        dense_targets = [
            (3, 3), (3, 4), (3, 5), (4, 3), (5, 3), (6, 3), (6, 4), (6, 5),
            (3, 8), (3, 9), (4, 8), (5, 8), (5, 9), (6, 9), (6, 8),
        ]

        assignments = build_multi_droplet_assignments(sources, dense_targets, planner)

        self.assertEqual(len(assignments), len(dense_targets))
        self.assertEqual({assignment.target for assignment in assignments}, set(dense_targets))
        schedules = [assignment.scheduled_path for assignment in assignments]
        regions = target_merge_region_map(dense_targets)
        max_len = max(len(schedule) for schedule in schedules)
        max_moving_by_region = {}
        for step in range(max_len):
            moving_by_region = {}
            for schedule in schedules:
                current = schedule[step] if step < len(schedule) else schedule[-1]
                if step == 0:
                    previous = None
                elif step - 1 < len(schedule):
                    previous = schedule[step - 1]
                else:
                    previous = schedule[-1]
                if current is not None and current != previous:
                    region = regions.get(current)
                    if region is None:
                        continue
                    moving_by_region[region] = moving_by_region.get(region, 0) + 1
            for region, count in moving_by_region.items():
                max_moving_by_region[region] = max(max_moving_by_region.get(region, 0), count)
        self.assertTrue(max_moving_by_region)
        self.assertLessEqual(max(max_moving_by_region.values()), 4)

    def test_non_contaminating_multi_paths_run_in_same_parallel_round(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        sources = [(0, 0), (0, 5), (5, 0), (5, 5), (10, 0), (10, 5)]
        targets = [(0, 2), (0, 7), (5, 2), (5, 7), (10, 2), (10, 7)]

        assignments = build_multi_droplet_assignments(sources, targets, planner)

        self.assertEqual(len(assignments), len(targets))
        self.assertEqual({assignment.round_index for assignment in assignments}, {1})
        schedules = [assignment.scheduled_path for assignment in assignments]
        moving_at_first_step = 0
        for schedule in schedules:
            if len(schedule) > 1 and schedule[0] is not None and schedule[1] != schedule[0]:
                moving_at_first_step += 1
        self.assertEqual(moving_at_first_step, len(targets))

    def test_sparse_letter_shape_targets_are_planned_with_staggered_source_emission(self):
        planner = AStarPlanner(rows=20, cols=20, valid_cells=LAYOUT_CELLS, extra_edges=RESERVOIR_CONNECTIONS)
        sources = [(-3, 6), (-3, 13), (6, -3), (13, -3), (6, 22), (13, 22), (22, 6), (22, 13)]
        c_shape = [(6, col) for col in (2, 4, 6)] + [(14, col) for col in (2, 4, 6)] + [(row, 2) for row in (8, 10, 12)]
        s_shape = (
            [(6, col) for col in (8, 10, 12)]
            + [(10, col) for col in (8, 10, 12)]
            + [(14, col) for col in (8, 10, 12)]
            + [(8, 8), (12, 12)]
        )
        e_shape = (
            [(6, col) for col in (14, 16, 18)]
            + [(10, col) for col in (14, 16, 18)]
            + [(14, col) for col in (14, 16, 18)]
            + [(8, 14), (12, 14)]
        )
        targets = c_shape + s_shape + e_shape

        assignments = build_multi_droplet_assignments(sources, targets, planner)

        self.assertEqual(len(assignments), len(set(targets)))
        self.assertEqual({assignment.target for assignment in assignments}, set(targets))
        starts_by_source = {}
        for assignment in assignments:
            start_step = next(step for step, cell in enumerate(assignment.scheduled_path) if cell is not None)
            starts_by_source.setdefault(assignment.source, []).append(start_step)
        self.assertTrue(any(start > 0 for starts in starts_by_source.values() for start in starts))
        for starts in starts_by_source.values():
            self.assertEqual(len(starts), len(set(starts)))

    def test_multi_scheduler_allows_same_cell_at_different_times(self):
        paths = [
            [(0, 0), (0, 1), (0, 2), (0, 3)],
            [(2, 1), (1, 1), (0, 1), (0, 0)],
        ]

        schedules = schedule_multi_paths(paths)

        self.assertEqual(len(schedules), 2)
        visits = [
            step
            for step in range(max(len(schedule) for schedule in schedules))
            if all(step < len(schedule) and schedule[step] == (0, 1) for schedule in schedules)
        ]
        self.assertEqual(visits, [])
        self.assertIn((0, 1), schedules[0])
        self.assertIn((0, 1), schedules[1])


if __name__ == "__main__":
    unittest.main()
