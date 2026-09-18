"""Run a deterministic demonstration using a disposable database."""

from pathlib import Path
from tempfile import TemporaryDirectory

from app import TicketStore


def main():
    with TemporaryDirectory(prefix="lab-queue-demo-") as folder:
        with TicketStore(Path(folder) / "demo.sqlite3") as store:
            for title, priority in [
                ("Demo: printer needs paper", 3),
                ("Demo: lab login service unavailable", 1),
                ("Demo: application will not launch", 2),
                ("Demo: second urgent login issue", 1),
            ]:
                ticket = store.create(title, priority)
                print(f"Added #{ticket.id}: {ticket.title} (priority {priority})")
            print("\nService order: priority first, then oldest within each priority")
            while (ticket := store.start_next()) is not None:
                print(f"Working on #{ticket.id}: {ticket.title}")
                store.resolve(ticket.id)
            print("\nFinal counts:", store.stats())
            print("Demo data is temporary; your own tickets are unchanged.")


if __name__ == "__main__":
    main()
