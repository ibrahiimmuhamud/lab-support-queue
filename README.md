<div align="center">

# Lab Support Queue

**The next ticket should be the right ticket.**

A local full-stack web application and Python command-line tool for prioritizing computer lab issues,
tracking work, and keeping support requests organized.

Python 3.11+ · JavaScript · SQLite · Priority scheduling · 32 automated tests

[Quick start](#quick-start) · [Demo](#see-it-work) · [Design](#under-the-hood) · [Tests](#testing) · [Roadmap](#roadmap)

</div>

---

## Why this project

Computer lab support involves very different kinds of problems: an empty printer
tray, an application that will not open, or a login issue blocking access to a
workstation. Arrival order matters, but so does urgency.

Inspired by my experience as a computer lab assistant, Lab Support Queue explores
a practical question: **how do you choose what to work on next without losing
track of everything else?**

The tool serves high priority issues first and preserves arrival order within
each priority. SQLite keeps records between runs, while explicit state
transitions prevent tickets from being resolved before work begins.

> **Status:** Completed v1 local web application, built with AI assistance.
> Not deployed at Bellevue College; contains no institutional records.

## What it does

- Responsive dashboard with ticket totals, search, status filters, and a next-ticket preview.
- Accessible ticket creation dialog, clear validation, and one-click resolution.
- Record issues with a title and one of three priorities.
- Select the next ticket by priority, then arrival order.
- Track progress from `waiting` to `active` to `resolved`.
- Persist tickets in a local SQLite database.
- Prevent duplicate claims by selecting and updating within one transaction.
- Report counts for each status and reject invalid input with readable errors.

## Quick start

Launch the website from the project folder:

```bash
python3 server.py
```

Open **http://127.0.0.1:8000**. Press **Control+C** in the terminal to stop.
The web app and CLI use the same `tickets.sqlite3` file when launched from the same folder.
Your existing tickets remain intact. No installation, API keys, or build step is needed.
If port 8000 is occupied, use `python3 server.py --port 8002` and open that port instead.
Choose a separate database with `python3 server.py --db example.sqlite3`.

### Web application architecture

The browser loads `web/index.html`, `style.css`, and `main.js`. JavaScript sends JSON
requests to `server.py`, which uses the existing `TicketStore` and `TicketQueue`
classes in `app.py`. SQLite saves each change; reloading the page reads saved tickets.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/tickets` | List tickets and obtain a request token |
| `POST /api/tickets` | Create a ticket with title and priority |
| `POST /api/start-next` | Atomically claim the next waiting ticket |
| `POST /api/resolve` | Resolve an active ticket by ID |

Mutations require JSON and the `X-Queue-Token` returned by the same-origin read.
Host and Origin checks, bounded request bodies, parameterized SQL, and a restrictive
content security policy provide defense in depth. Ticket text is rendered using
`textContent`, not injected HTML. These safeguards are **not authentication**.

### Scope and design

Version 1 is complete for **local, single-computer use**. The server binds only to
127.0.0.1. It uses Python's development HTTP server and is not intended for public
hosting, institutional use, or sensitive data. Authentication, staff roles, pagination,
and production hosting are outside this release. Do not expose it through a public tunnel.

The interface follows Emil Kowalski's design engineering guidance: restrained button
feedback, immediate keyboard interactions, visible focus states, reduced-motion support,
and responsive layouts. It includes loading, empty, validation, and connection-error states.

### CLI and temporary demo

Requires Python 3.11 or newer. No packages, accounts, credentials, or paid services.
Open a terminal in this folder, then:

```bash
python3 demo.py
python3 -m unittest discover -s tests -v
```

The demo uses fictional tickets in a temporary database and leaves your own
tickets unchanged.

For your own sample tickets:

```bash
python3 app.py add "Printer needs paper" --priority 3
python3 app.py add "Lab login service unavailable" --priority 1
python3 app.py list
python3 app.py start-next
python3 app.py resolve 2
python3 app.py stats
```

Priority 1 is high, 2 is normal, 3 is low. New tickets default to normal.
The example assumes a new database. Use the ID returned by `start-next` when
resolving a ticket. `--db path.sqlite3` goes **before** the command to select
another database. Data persists in `tickets.sqlite3` between runs.

## See it work

| Arrival ID | Issue | Priority | Service order |
| --- | --- | --- | --- |
| 1 | Printer needs paper | Low | 4th |
| 2 | Lab login service unavailable | High | 1st |
| 3 | Application will not launch | Normal | 3rd |
| 4 | Second urgent login issue | High | 2nd |

```text
Service order: priority first, then oldest within each priority
Working on #2: Demo: lab login service unavailable
Working on #4: Demo: second urgent login issue
Working on #3: Demo: application will not launch
Working on #1: Demo: printer needs paper

Final counts: {'waiting': 0, 'active': 0, 'resolved': 4}
```

Normal commands return JSON so results are easy to inspect or use in a script.

## Commands

| Command | Purpose |
| --- | --- |
| `add "title" --priority 1` | Create a high priority ticket |
| `list` | Show all tickets in arrival order |
| `list --status waiting` | Show only waiting tickets |
| `start-next` | Mark the next eligible ticket active |
| `resolve ID` | Resolve an active ticket |
| `stats` | Show waiting, active, and resolved counts |

Titles must be 1–160 characters on one line. Resolving a waiting or already
resolved ticket returns an error without changing its state. Database files
are excluded from version control.

## Under the hood

| Component | Responsibility |
| --- | --- |
| `Ticket` | Immutable data object describing one issue |
| `TicketQueue` | Dictionary of records plus a heap of `(priority, id)` pairs |
| `TicketStore` | Parameterized SQL, persistence, validation, state transitions |
| CLI | Parses commands and prints JSON or a readable error |

The algorithm orders by priority, then by the monotonically increasing ID.
For `n` waiting tickets, creating the dictionary and heap takes O(n) time and
O(n) memory. One heap removal takes O(log n); dictionary lookup/removal is
O(1) on average. The CLI reloads the queue for each claim, so a complete
`start-next` is O(n), **not O(log n)**, excluding disk/lock overhead.

SQLite is the source of truth. `BEGIN IMMEDIATE` protects selection and update
in one transaction, preventing separate local connections from claiming the
same ticket. A failed operation rolls back; only active tickets can be resolved.

## Design tradeoffs

- The heap makes the data structure explicit for learning. A database-only
  implementation could use `ORDER BY priority, id LIMIT 1` with an index and
  avoid loading all waiting tickets. That is a sensible alternative at scale.
- Strict priority can starve low priority tickets if urgent work keeps arriving.
  Aging or a rotating service policy could address this; neither is implemented.
- Multiple tickets can be active because multiple lab assistants may be working.
  There is no staff assignment or authentication yet.
- This is a local web application, not a production or distributed system. It has no
  deployment, production users, SLA measurement, or cloud integration.
- Ticket titles should use fictional examples. Do not put student names,
  passwords, or institutional support records into this project.

## Testing

The tests exercise queue ordering, tie handling, invalid input, lifecycle rules,
SQL-like text input, disk persistence, simultaneous local claims, CLI output,
and clean error handling. They use isolated temporary or in-memory databases.

Version 1 verification: **32 tests passed** (22 core/CLI tests and 10 web/API
tests). Web tests cover the HTTP lifecycle, invalid payloads, request size limits,
host/origin/token checks, static assets, and security headers. Browser checks cover
creation, claiming, resolution, persistence after reload, search, and responsive layout.
The temporary CLI demo produces service order 2, 4, 3, 1.

The GitHub Actions workflow is configured to run tests and the demo on Python
3.11 and 3.13 for pushes and pull requests. Check the repository's **Actions**
tab for its actual run status after publication.

Workflow references: [actions/checkout](https://github.com/actions/checkout),
[actions/setup-python](https://github.com/actions/setup-python).

## Project structure

```text
lab-support-queue/
├── app.py                      # Model, queue, storage, and CLI
├── server.py                   # Local HTTP server and JSON API
├── web/                        # HTML, CSS, and JavaScript interface
├── demo.py                     # Reproducible demo with temporary data
├── tests/
│   ├── test_app.py              # Core unit and integration tests
│   └── test_web.py              # HTTP and request-protection tests
├── .github/workflows/
│   └── tests.yml                # Python test matrix
├── .gitignore                  # Excludes databases and generated files
└── README.md
```

## Roadmap

- [ ] Reprioritize waiting tickets with validation and persistence tests.
- [ ] Explore an aging policy so low priority work is not starved.
- [ ] Compare heap scheduling with an indexed SQL query.
- [ ] Add staff assignment and document the resulting state rules.

These are optional future improvements, not requirements for the completed v1.

## AI assistance

The initial implementation, tests, and documentation were generated with
**OpenAI Codex**. This repository is a learning project for examining and
extending AI-generated software. The local test results validate specific
behaviors; they do not establish production readiness or independent mastery.

Personal review, additional tests, and extensions are ongoing learning goals.
