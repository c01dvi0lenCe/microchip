import tkinter as tk
import unittest
from unittest.mock import patch
from main import STM32MatrixController


class OperatorGuiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.app=STM32MatrixController(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.app.on_close()

    def test_default_gui_has_no_research_config_or_experiment_tab(self):
        names=[self.app.main_notebook.tab(t,'text') for t in self.app.main_notebook.tabs()]
        self.assertEqual(names,['手动电极','自动化路径规划'])
        self.assertFalse(hasattr(self.app,'experiment_config_entry'))
        self.assertFalse(hasattr(self.app,'experiment_page'))

    def test_hidden_research_entry_cannot_start_from_operator_gui(self):
        with patch.object(self.app.experiment_session,'start') as start:
            self.assertFalse(self.app.start_experiment())
            start.assert_not_called()
        self.assertFalse(self.app._experiment_active)
        self.assertIn('命令行',self.app.experiment_status_var.get())


if __name__=='__main__':unittest.main()
