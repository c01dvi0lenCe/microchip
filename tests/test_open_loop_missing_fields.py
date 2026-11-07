"""Incomplete operator four-cell edits are reported without guessing points."""
import unittest

import controllers.open_loop_sequence as sequence


class FourCellMissingFieldsTests(unittest.TestCase):
    def missing_fields(self, tasks):
        helper = getattr(sequence, 'four_cell_missing_fields', None)
        self.assertTrue(callable(helper), 'export four_cell_missing_fields')
        return helper(tasks)

    def task(self, group='a', start=1, ring=(1, 2, 22, 21), target=1):
        return sequence.FourCellTask(group, start, ring, target)

    def test_reports_all_incomplete_groups_and_fields_in_input_order(self):
        tasks = [self.task('z', None, (1, 2), None), self.task('complete'),
                 self.task('b', 65, (), None)]
        result = self.missing_fields(tasks)
        self.assertEqual(list(result), ['z', 'b'])
        self.assertEqual(result, {
            'z': ('起点', '终点', '四点（已选2/4）'),
            'b': ('终点', '四点（已选0/4）'),
        })

    def test_individual_unset_ring_entries_are_not_counted_or_filled(self):
        task = self.task(ring=(1, None, 22, None))
        self.assertEqual(self.missing_fields([task]), {'a': ('四点（已选2/4）',)})
        self.assertEqual(task.ring, (1, None, 22, None))
        with self.assertRaisesRegex(ValueError, '组a.*四点（已选2/4）'):
            sequence.compile_four_cell_tasks([task], 1)

    def test_complete_and_empty_tasks_have_no_missing_fields(self):
        self.assertEqual(self.missing_fields([self.task()]), {})
        self.assertEqual(self.missing_fields([]), {})

    def test_each_unset_endpoint_is_named(self):
        for start, target, label in ((None, 1, '起点'), (1, None, '终点')):
            with self.subTest(label=label):
                task = self.task(start=start, target=target)
                self.assertEqual(self.missing_fields([task]), {'a': (label,)})
                with self.assertRaisesRegex(ValueError, f'组a.*{label}'):
                    sequence.compile_four_cell_tasks([task], 1)

    def test_compilation_reports_every_incomplete_group_before_core_validation(self):
        tasks = [self.task('first', None, (1, None), None),
                 self.task('second', None, (), 65)]
        with self.assertRaises(ValueError) as caught:
            sequence.compile_four_cell_tasks(tasks, 1)
        message = str(caught.exception)
        self.assertIn('组first', message)
        self.assertIn('起点、终点、四点（已选1/4）', message)
        self.assertIn('组second', message)
        self.assertIn('四点（已选0/4）', message)
        self.assertLess(message.index('组first'), message.index('组second'))
        self.assertNotIn('核心电极', message)

    def test_generator_input_is_not_exhausted_by_missing_field_preflight(self):
        plan = sequence.compile_four_cell_tasks((task for task in [self.task()]), 1)
        self.assertEqual(plan.routes['a'], (1, 2, 22, 21, 1))
        self.assertEqual(self.missing_fields(task for task in [self.task(start=None)]),
                         {'a': ('起点',)})

    def test_invalid_present_ids_remain_id_errors_not_missing_fields(self):
        for bad in (0, 401, True, 1.0, '', '1'):
            for field in ('start', 'target', 'ring'):
                values = {field: (1, bad, 22, 21) if field == 'ring' else bad}
                task = self.task(**values)
                with self.subTest(field=field, bad=bad):
                    self.assertEqual(self.missing_fields([task]), {})
                    with self.assertRaisesRegex(ValueError, '核心电极'):
                        sequence.compile_four_cell_tasks([task], 1)

    def test_invalid_rings_membership_and_conflicts_still_rejected(self):
        cases = [[self.task(ring=(1, 2, 21, 22))],
                 [self.task(ring=(1, 2, 22, 1))],
                 [self.task(ring=(1, 2, 22, 21, 41))],
                 [self.task(target=3)],
                 [self.task('a'), self.task('b')]]
        for tasks in cases:
            with self.subTest(tasks=tasks):
                self.assertEqual(self.missing_fields(tasks), {})
                with self.assertRaises(ValueError):
                    sequence.compile_four_cell_tasks(tasks, 1)

    def test_empty_compile_keeps_existing_meaningful_error(self):
        with self.assertRaisesRegex(ValueError, '至少需要一组路径'):
            sequence.compile_four_cell_tasks([], 1)

    def test_bad_task_types_and_group_ids_remain_rejected(self):
        cases = [[object()], [self.task(group='')], [self.task(group=3)],
                 [self.task('a', start=None), self.task('a', target=None)]]
        for tasks in cases:
            with self.subTest(tasks=tasks):
                with self.assertRaises(ValueError):
                    self.missing_fields(tasks)
                with self.assertRaises(ValueError):
                    sequence.compile_four_cell_tasks(tasks, 1)


if __name__ == '__main__':
    unittest.main()
