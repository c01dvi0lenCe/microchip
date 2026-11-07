"""Hand-calculable checks for the independent CSV audit, not research GT."""
import unittest

try:
    from scripts.audit_chapter2_v2_stage import reference_from_ticks, score_events, execution_counts, value
except ImportError:
    reference_from_ticks=score_events=execution_counts=None


class IndependentStageAuditTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(score_events,'independent CSV audit not implemented')
        self.route=[190,191,192,172]

    def row(self,t,**changes):
        return dict(time_s=t,step=0,target=191,phase='transport',epoch=1,
                    x=0.,y=0.,true_speed=0.,**changes)

    def test_reference_requires_independent_speed_and_dwell(self):
        rows=[self.row(i*.01) for i in range(16)]
        r=reference_from_ticks(rows,{191:(0.,0.)},dict(radius_pitch=.09,max_speed_pitch_s=.06,dwell_s=.15),.01,3)
        self.assertAlmostEqual(r[0]['lower_s'],.14)
        self.assertAlmostEqual(r[0]['upper_s'],.15)
        for row in rows:row['true_speed']=.1
        self.assertEqual(reference_from_ticks(rows,{191:(0.,0.)},dict(radius_pitch=.09,max_speed_pitch_s=.06,dwell_s=.15),.01,3),[])

    def test_recovery_and_epoch_break_reference(self):
        rows=[self.row(i*.01) for i in range(10)]
        rows += [dict(self.row(.1),phase='recovering')]
        rows += [dict(self.row(.2+i*.01),epoch=2) for i in range(10)]
        self.assertEqual(reference_from_ticks(rows,{191:(0.,0.)},dict(radius_pitch=.09,max_speed_pitch_s=.06,dwell_s=.15),.01,3),[])

    def test_early_interval_uncertain_and_supported_are_separate(self):
        refs=[dict(step=0,target=191,lower_s=1.,upper_s=1.01)]
        for t,label in ((.99,'premature'),(1.005,'uncertain'),(1.01,'supported')):
            result=score_events([dict(event='Update',step=0,target=191,time_s=t)],refs,self.route)
            self.assertEqual(result['events'][0]['label'],label)

    def test_no_reference_is_unsupported_not_invented_early_time(self):
        result=score_events([dict(event='Complete',step=2,target=172,time_s=2.)],[],self.route)
        self.assertEqual(result['unsupported_no_reference'],1)
        self.assertEqual(result['premature'],0)
        self.assertEqual(result['supported'],0)

    def test_duplicate_and_wrong_target_retained(self):
        events=[dict(event='Update',step=0,target=191,time_s=1.1),dict(event='Update',step=0,target=191,time_s=1.2),
                dict(event='Update',step=1,target=191,time_s=2.)]
        result=score_events(events,[dict(step=0,target=191,lower_s=1.,upper_s=1.01)],self.route)
        self.assertEqual(result['duplicates'],1);self.assertEqual(result['wrong'],1)
        self.assertEqual(result['supported'],1)

    def test_missing_confirmation_not_removed(self):
        result=score_events([], [dict(step=0,target=191,lower_s=1.,upper_s=1.01)], self.route)
        self.assertEqual(result['missed'],1);self.assertEqual(result['planned_steps'],3)
        self.assertEqual(result['reference_arrivals'],1)

    def test_no_reference_recall_is_not_perfect(self):
        result=score_events([],[],self.route)
        self.assertIsNone(result['recall'])
        self.assertEqual(result['planned_steps'],3)

    def test_complete_without_reference_not_path_success(self):
        events=[dict(event='Update',step=i,target=self.route[i+1],time_s=i+1.) for i in range(2)]
        events.append(dict(event='Complete',step=2,target=172,time_s=3.))
        result=score_events(events,[],self.route)
        self.assertFalse(result['path_complete']);self.assertEqual(result['unsupported'],3)

    def test_failed_source_keeps_all_unattempted_steps(self):
        events=[dict(event='Prepare',time_s=0.),dict(event='Stop',reason='source confirmation timeout',time_s=2.6)]
        result=execution_counts(events,[],self.route,'end_to_end')
        self.assertEqual(result['unattempted_steps'],3)
        self.assertFalse(result['source_prepared']);self.assertFalse(result['transport_complete'])
        self.assertEqual(result['stop_reasons'],{'source confirmation timeout':1})

    def test_source_only_not_transport_success(self):
        result=execution_counts([dict(event='SourcePrepared',time_s=.5)],[],self.route,'source_only')
        self.assertTrue(result['source_prepared']);self.assertFalse(result['transport_complete'])
        self.assertEqual(result['unattempted_steps'],3)

    def test_csv_capitalized_boolean_and_empty_are_typed(self):
        self.assertIs(value('True'),True)
        self.assertIs(value('False'),False)
        self.assertIsNone(value(''))
        self.assertEqual(value('Unknown'),'Unknown')


if __name__=='__main__':unittest.main()
