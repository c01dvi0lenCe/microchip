import unittest

from scripts.evaluate_real_segmentation_g4 import summarize, decode_baseline_row


class G4EvaluationTests(unittest.TestCase):
    def test_NA_keeps_planned_denominator_without_zero_score(self):
        unavailable = dict(eligible=False, positive_gt=True, error=False, dice=None,
                           iou=None, precision=None, recall=None, fp=None, valid_pixels=10)
        good = dict(eligible=True, positive_gt=True, error=False, dice=.8, iou=.7,
                    precision=.9, recall=.8, fp=1, valid_pixels=10, image_level_miss=False)
        result = summarize([unavailable, good], 'background')
        self.assertEqual(result['planned'], 2)
        self.assertEqual(result['eligible'], 1)
        self.assertEqual(result['dice_mean'], .8)
        self.assertEqual(result['availability'], .5)

    def test_emptyGT_FP_is_not_instance_miss(self):
        row = dict(eligible=True, positive_gt=False, error=False, dice=0, iou=0,
                   precision=0, recall=1, fp=4, valid_pixels=100, image_level_miss=False)
        result = summarize([row], 'unet')
        self.assertEqual(result['empty_GT_false_positive_images'], 1)
        self.assertEqual(result['false_positive_area_fraction_mean'], .04)

    def test_csv_booleans_and_blanks(self):
        row = decode_baseline_row(dict(eligible='False', positive_gt='True', error='False',
                                      dice='', iou='', precision='', recall='', fp='', valid_pixels='10'))
        self.assertIs(row['eligible'], False)
        self.assertIsNone(row['dice'])


if __name__ == '__main__':
    unittest.main()
