"""Local-only web interface. Run: python3 server.py (no dependencies)."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit

from app import TicketStore

STATIC = Path(__file__).parent / 'web'


def make_server(database, port=8000):
    # One token per server process; cross-origin sites cannot read it.
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, mime='application/json'):
            data = json.dumps(body).encode() if mime == 'application/json' else body
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') in (
                f'127.0.0.1:{self.server.server_port}',
                f'localhost:{self.server.server_port}',
            )

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {'error': 'Invalid host'})
            path = urlsplit(self.path).path
            if path == '/api/tickets':
                try:
                    with TicketStore(database) as store:
                        tickets = [asdict(t) for t in store.list_tickets()]
                    return self.reply(200, {'tickets': tickets, 'token': token})
                except sqlite3.Error:
                    return self.reply(503, {'error': 'Database unavailable. Please try again.'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8'),
                     '/apple.css': ('apple.css', 'text/css; charset=utf-8'),
                     '/main.js': ('main.js', 'text/javascript; charset=utf-8')}
            if path not in files:
                return self.reply(404, {'error': 'Not found'})
            filename, mime = files[path]
            self.reply(200, (STATIC / filename).read_bytes(), mime)

        def do_POST(self):
            origin = self.headers.get('Origin')
            if (not self.valid_host() or self.headers.get('X-Queue-Token') != token
                    or (origin and origin != 'http://' + self.headers.get('Host', ''))):
                return self.reply(403, {'error': 'Refresh this page before making changes.'})
            if self.headers.get('Content-Type') != 'application/json':
                return self.reply(415, {'error': 'Expected application/json'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    return self.reply(413, {'error': 'Request must be 1–4096 bytes'})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                with TicketStore(database) as store:
                    if self.path == '/api/tickets':
                        if not isinstance(payload.get('title'), str):
                            raise ValueError('Enter an issue title')
                        result = store.create(payload['title'], payload.get('priority', 2))
                    elif self.path == '/api/start-next':
                        result = store.start_next()
                        if result is None:
                            return self.reply(409, {'error': 'No waiting tickets'})
                    elif self.path == '/api/resolve':
                        if type(payload.get('id')) is not int or payload['id'] < 1:
                            raise ValueError('A positive ticket ID is required')
                        result = store.resolve(payload['id'])
                    else:
                        return self.reply(404, {'error': 'Not found'})
                self.reply(200, asdict(result))
            except (ValueError, UnicodeDecodeError) as error:
                self.reply(400, {'error': str(error)})
            except sqlite3.Error:
                self.reply(503, {'error': 'Database busy or unavailable. Please try again.'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='tickets.sqlite3')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = make_server(args.db, args.port)
    print(f'Lab Support Queue → http://127.0.0.1:{server.server_port}', flush=True)
    print('Local use only. Press Control+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
