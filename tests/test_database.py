import unittest
from contextlib import contextmanager

from db import Database


class FakeCursor:
    def __init__(self, *, result=None, error: Exception | None = None):
        self.result = {"1": 1} if result is None else result
        self.error = error
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql):
        self.executed.append(sql)
        if self.error is not None:
            raise self.error

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class DatabasePingTests(unittest.TestCase):
    @staticmethod
    def make_database(cursor: FakeCursor) -> Database:
        database = Database.__new__(Database)

        @contextmanager
        def connection(*, with_db=True):
            del with_db
            yield FakeConnection(cursor)

        database._connection = connection
        return database

    def test_ping_executes_select_one(self):
        cursor = FakeCursor()
        database = self.make_database(cursor)

        self.assertTrue(database.ping())
        self.assertEqual(cursor.executed, ["SELECT 1"])

    def test_ping_propagates_query_failure(self):
        cursor = FakeCursor(error=RuntimeError("connection lost"))
        database = self.make_database(cursor)

        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            database.ping()


if __name__ == "__main__":
    unittest.main()
