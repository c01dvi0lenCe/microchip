import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from controllers.open_loop_journal import OpenLoopJournal
from controllers.open_loop_sequence import compile_routes
from dmf.recording import ElectrodeEventStream


class OpenLoopJournalTests(unittest.TestCase):
    def test_manifest_failure_unsubscribes_and_closes_writer(self):
        stream=ElectrodeEventStream();instances=[]
        from dmf.recording import AsyncCsvLog
        def writer(*args,**kwargs):
            log=AsyncCsvLog(*args,**kwargs);instances.append(log);return log
        with tempfile.TemporaryDirectory() as folder:
            with patch('controllers.open_loop_journal.AsyncCsvLog',side_effect=writer), \
                    patch.object(OpenLoopJournal,'_write_manifest',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    OpenLoopJournal(folder,compile_routes({'g':(190,191)}),{},simulation=True,stream=stream)
            self.assertEqual(stream.listeners,[])
            self.assertFalse(instances[0].worker.is_alive())

    def test_finish_retains_error_and_writes_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=OpenLoopJournal(folder,compile_routes({'g':(190,191)}),{},
                                    simulation=True,stream=ElectrodeEventStream())
            journal.step('request',0,{190},{'g':190})
            journal.finish('stopped',{190})
            data=json.loads((journal.output/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(data['written_rows']['steps'],1)
            self.assertEqual(data['written_rows']['events'],1)
            self.assertIn('open_loop_controller.py',data['source_sha256'])


if __name__=='__main__':unittest.main()
