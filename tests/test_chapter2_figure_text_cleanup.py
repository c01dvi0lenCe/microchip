import unittest
try:
    from scripts import chapter2_figure_text_cleanup_v4 as r
except ImportError:
    r=None

class FigureTextCleanupTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(r,'text-only cleanup module missing')
    def test_explanatory_notes_are_selected(self):
        self.assertIn('参考区间 [1.45, 1.46] s',r.REMOVE['S1-A'])
        self.assertIn('任务阶段按日志模拟Applied划分；观测量按处理时刻显示。',r.REMOVE['S1-B'])
    def test_data_labels_and_legends_are_not_selected(self):
        all_removed=set().union(*r.REMOVE.values())
        for label in ('SIMULATION','1.92 s','Moving / Start','Arrived / Update','190','191','目标距离','方向进展','η_source（源区残留）'):
            self.assertNotIn(label,all_removed)
    def test_removed_text_span_preserves_graphics_state(self):
        stream=b'q 0.95 w BT (note) Tj ET 1 2 m 3 4 l S Q'
        start=stream.index(b'BT');end=stream.index(b'ET')+2
        self.assertEqual(r.remove_ranges(stream,[(start,end)]),b'q 0.95 w  1 2 m 3 4 l S Q')
    def test_non_text_geometry_digest_ignores_only_text(self):
        a='<svg xmlns="http://www.w3.org/2000/svg"><path d="M 1 2"/><text>note</text></svg>'
        b='<svg xmlns="http://www.w3.org/2000/svg"><path d="M 1 2"/></svg>'
        c='<svg xmlns="http://www.w3.org/2000/svg"><path d="M 2 2"/></svg>'
        self.assertEqual(r.svg_geometry(a),r.svg_geometry(b))
        self.assertNotEqual(r.svg_geometry(a),r.svg_geometry(c))

if __name__=='__main__':unittest.main()
