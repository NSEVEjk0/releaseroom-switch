import sqlite3
import tempfile
import unittest
from pathlib import Path
from releaseroom.store import Store


class StorageLifetimeTests(unittest.TestCase):
    def test_transaction_commits_and_connection_closes_on_success(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder),{'human'})
            with store.connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('UPDATE head SET revision=7 WHERE id=1')
            with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
            with store.connect() as fresh:
                self.assertEqual(fresh.execute('SELECT revision FROM head WHERE id=1').fetchone()[0],7)

    def test_failed_transaction_rolls_back_and_does_not_leave_the_database_locked(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder),{'human'})
            with self.assertRaisesRegex(RuntimeError,'failed'):
                with store.connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    connection.execute('UPDATE head SET revision=7 WHERE id=1')
                    raise RuntimeError('failed')
            with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
            with store.connect() as fresh:
                fresh.execute('BEGIN IMMEDIATE')
                self.assertEqual(fresh.execute('SELECT revision FROM head WHERE id=1').fetchone()[0],0)


if __name__=='__main__':unittest.main()
