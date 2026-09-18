import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import Ticket, TicketQueue, TicketStore, main


def sample(ticket_id, priority, status="waiting"):
    return Ticket(ticket_id, "Example", priority, status, "2026-09-17T00:00:00Z")


class QueueTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(TicketQueue([]).pop_next())

    def test_priority_before_arrival(self):
        queue = TicketQueue([sample(1, 3), sample(2, 1), sample(3, 2)])
        self.assertEqual([queue.pop_next().id for _ in range(3)], [2, 3, 1])

    def test_fifo_ties_even_if_input_is_unsorted(self):
        queue = TicketQueue([sample(8, 2), sample(2, 2), sample(4, 2)])
        self.assertEqual([queue.pop_next().id for _ in range(3)], [2, 4, 8])

    def test_skips_nonwaiting(self):
        queue = TicketQueue([sample(1, 1, "active"), sample(2, 1, "resolved")])
        self.assertIsNone(queue.pop_next())

    def test_ticket_is_returned_once(self):
        queue = TicketQueue([sample(1, 2)])
        self.assertEqual(queue.pop_next().id, 1)
        self.assertIsNone(queue.pop_next())

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            TicketQueue([sample(1, 2), sample(1, 1)])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = TicketStore(":memory:")
        self.addCleanup(self.store.connection.close)

    def test_create_trims_title(self):
        ticket = self.store.create("  Printer broken  ", 2)
        self.assertEqual(ticket.title, "Printer broken")
        self.assertEqual(ticket.status, "waiting")
        self.assertTrue(ticket.created_at.endswith("Z"))

    def test_bad_titles(self):
        for title in (" ", "x" * 161, "one\ntwo", "one\ttwo"):
            with self.subTest(title=repr(title)), self.assertRaises(ValueError):
                self.store.create(title, 2)

    def test_bad_priorities(self):
        for priority in (0, 4, True, "1", 1.0):
            with self.subTest(priority=priority), self.assertRaises(ValueError):
                self.store.create("Issue", priority)

    def test_missing_ticket(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.get(99)

    def test_full_lifecycle_and_counts(self):
        self.store.create("Minor", 3)
        urgent = self.store.create("Urgent", 1)
        claimed = self.store.start_next()
        self.assertEqual(claimed.id, urgent.id)
        self.assertEqual(claimed.status, "active")
        self.assertEqual(self.store.resolve(claimed.id).status, "resolved")
        self.assertEqual(self.store.stats(), {"waiting": 1, "active": 0, "resolved": 1})

    def test_cannot_resolve_waiting(self):
        ticket = self.store.create("Issue", 2)
        with self.assertRaisesRegex(ValueError, "Only an active"):
            self.store.resolve(ticket.id)
        self.assertEqual(self.store.get(ticket.id).status, "waiting")
        self.assertEqual(self.store.start_next().id, ticket.id)

    def test_cannot_resolve_twice(self):
        ticket = self.store.create("Issue", 2)
        self.store.start_next()
        self.store.resolve(ticket.id)
        with self.assertRaises(ValueError):
            self.store.resolve(ticket.id)

    def test_empty_claim_releases_transaction(self):
        self.assertIsNone(self.store.start_next())
        self.assertFalse(self.store.connection.in_transaction)
        self.store.create("Issue", 2)
        self.assertIsNotNone(self.store.start_next())

    def test_status_filter(self):
        self.store.create("First", 1)
        self.store.create("Second", 2)
        self.store.start_next()
        self.assertEqual(len(self.store.list_tickets("waiting")), 1)
        self.assertEqual(len(self.store.list_tickets("active")), 1)
        with self.assertRaises(ValueError):
            self.store.list_tickets("unknown")

    def test_sql_in_title_is_just_text(self):
        text = "Printer'); DROP TABLE tickets; --"
        ticket = self.store.create(text, 2)
        self.assertEqual(self.store.get(ticket.id).title, text)
        self.assertEqual(len(self.store.list_tickets()), 1)

    def test_database_constraints(self):
        with self.assertRaises(sqlite3.IntegrityError), self.store.connection:
            self.store.connection.execute(
                "INSERT INTO tickets (title, priority) VALUES (?, ?)", ("Issue", 99)
            )


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lab-queue-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tickets.sqlite3"

    def test_persists_after_reopening(self):
        with TicketStore(self.path) as store:
            ticket = store.create("Persist me", 2)
            store.start_next()
        with TicketStore(self.path) as store:
            self.assertEqual(store.get(ticket.id).status, "active")
            self.assertEqual(store.get(ticket.id).title, "Persist me")

    def test_concurrent_claims_are_distinct(self):
        with TicketStore(self.path) as store:
            for index in range(4):
                store.create(f"Issue {index}", 2)

        def claim(_):
            with TicketStore(self.path) as store:
                ticket = store.start_next()
                return ticket.id if ticket else None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(6)))
        claimed = [value for value in results if value is not None]
        self.assertEqual(sorted(claimed), [1, 2, 3, 4])
        self.assertEqual(results.count(None), 2)

    def test_cli_lifecycle_across_processes(self):
        script = Path(__file__).resolve().parents[1] / "app.py"

        def run(*args):
            result = subprocess.run(
                [sys.executable, str(script), "--db", str(self.path), *args],
                capture_output=True, text=True, check=True,
            )
            return json.loads(result.stdout)

        ticket = run("add", "Printer issue", "--priority", "1")
        self.assertEqual(run("start-next")["id"], ticket["id"])
        self.assertEqual(run("resolve", str(ticket["id"]))["status"], "resolved")
        self.assertEqual(run("stats")["resolved"], 1)
        self.assertEqual(run("list", "--status", "waiting"), [])
        self.assertIn("message", run("start-next"))

    def test_cli_error_has_no_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = main(["--db", str(self.path), "resolve", "404"])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_failed_database_path(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(["--db", str(self.path / "missing.db"), "stats"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
