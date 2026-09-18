"""Local support queue. Python 3.11+, standard library only."""

import argparse
import heapq
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Ticket:
    id: int
    title: str
    priority: int  # 1 = high, 2 = normal, 3 = low
    status: str
    created_at: str


class TicketQueue:
    """Heap selects priority then arrival ID; dictionary retrieves full records."""

    def __init__(self, tickets):
        self._tickets = {}
        self._heap = []
        for ticket in tickets:
            if ticket.status != "waiting":
                continue
            if ticket.id in self._tickets:
                raise ValueError("Duplicate ticket ID")
            self._tickets[ticket.id] = ticket
            self._heap.append((ticket.priority, ticket.id))
        heapq.heapify(self._heap)

    def pop_next(self):
        if not self._heap:
            return None
        _, ticket_id = heapq.heappop(self._heap)
        return self._tickets.pop(ticket_id)


class TicketStore:
    """SQLite is the persistent source of truth. No network service is needed."""

    def __init__(self, path):
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
                priority INTEGER NOT NULL CHECK(priority IN (1, 2, 3)),
                status TEXT NOT NULL DEFAULT 'waiting'
                    CHECK(status IN ('waiting', 'active', 'resolved')),
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        self.connection.commit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def get(self, ticket_id):
        row = self.connection.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Ticket {ticket_id} does not exist")
        return Ticket(**dict(row))

    def create(self, title, priority):
        title = title.strip()
        if not 1 <= len(title) <= 160 or any(ord(c) < 32 for c in title):
            raise ValueError("Title must be 1 to 160 characters on one line")
        if type(priority) is not int or priority not in (1, 2, 3):
            raise ValueError("Priority must be 1, 2, or 3")
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO tickets (title, priority) VALUES (?, ?)",
                (title, priority),
            )
        return self.get(cursor.lastrowid)

    def list_tickets(self, status=None):
        if status is not None and status not in ("waiting", "active", "resolved"):
            raise ValueError("Unknown status")
        if status is None:
            rows = self.connection.execute("SELECT * FROM tickets ORDER BY id")
        else:
            rows = self.connection.execute(
                "SELECT * FROM tickets WHERE status = ? ORDER BY id", (status,)
            )
        return [Ticket(**dict(row)) for row in rows]

    def start_next(self):
        # Acquire the write lock before selecting so two callers cannot claim
        # the same waiting ticket. The context commits or rolls back as a unit.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            queue = TicketQueue(self.list_tickets("waiting"))
            ticket = queue.pop_next()
            if ticket is None:
                return None
            self.connection.execute(
                "UPDATE tickets SET status = 'active' WHERE id = ?", (ticket.id,)
            )
            return replace(ticket, status="active")

    def resolve(self, ticket_id):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            ticket = self.get(ticket_id)
            if ticket.status != "active":
                raise ValueError("Only an active ticket can be resolved")
            self.connection.execute(
                "UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,)
            )
            return replace(ticket, status="resolved")

    def stats(self):
        counts = {"waiting": 0, "active": 0, "resolved": 0}
        for row in self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM tickets GROUP BY status"
        ):
            counts[row["status"]] = row["count"]
        return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local lab support ticket queue")
    parser.add_argument("--db", default="tickets.sqlite3", help="SQLite file path")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="Add a waiting ticket")
    add.add_argument("title")
    add.add_argument("--priority", type=int, choices=(1, 2, 3), default=2)
    show = commands.add_parser("list", help="List tickets in arrival order")
    show.add_argument("--status", choices=("waiting", "active", "resolved"))
    commands.add_parser("start-next", help="Claim highest priority waiting ticket")
    resolve = commands.add_parser("resolve", help="Resolve an active ticket")
    resolve.add_argument("id", type=int)
    commands.add_parser("stats", help="Show counts by status")
    args = parser.parse_args(argv)
    try:
        with TicketStore(args.db) as store:
            if args.command == "add":
                output = asdict(store.create(args.title, args.priority))
            elif args.command == "list":
                output = [asdict(t) for t in store.list_tickets(args.status)]
            elif args.command == "start-next":
                ticket = store.start_next()
                output = asdict(ticket) if ticket else {"message": "No waiting tickets"}
            elif args.command == "resolve":
                output = asdict(store.resolve(args.id))
            else:
                output = store.stats()
        print(json.dumps(output, indent=2))
        return 0
    except (ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
