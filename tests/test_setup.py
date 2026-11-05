import tempfile
import unittest
from pathlib import Path
from releaseroom.setup import resolve_profiles,validate_profiles,operator_lock

class SetupTests(unittest.TestCase):
    def profiles(self):return {r:{'id':r+'-server','name':r,'api_key':'fixture-only'} for r in ('builder','tester','release')}
    def participants(self):return [{'id':'opaque-'+r,'name':r,'type':'agent'} for r in ('builder','tester','release')]+[{'id':'opaque-human','name':'Reviewer','type':'user'}]
    def test_names_resolve_only_to_exact_distinct_agent_records(self):
        profiles,humans=resolve_profiles(self.profiles(),self.participants())
        self.assertEqual(profiles['builder']['participant_id'],'opaque-builder');self.assertTrue(validate_profiles(profiles,{'opaque-human'}))
        with self.assertRaises(ValueError):validate_profiles(profiles,{'opaque-builder'})
        with self.assertRaises(ValueError):resolve_profiles(self.profiles(),self.participants()+[{'id':'other','name':'builder','type':'agent'}])
        self.assertEqual(humans,[{'id':'opaque-human','name':'Reviewer'}])
    def test_mutating_operator_commands_cannot_run_beside_workers(self):
        with tempfile.TemporaryDirectory() as folder:
            with operator_lock(Path(folder)):
                with self.assertRaises(ValueError):
                    with operator_lock(Path(folder)):pass
