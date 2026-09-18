import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from server import make_server


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = make_server(Path(cls.temp.name) / 'web.sqlite3', 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, json.dumps(payload) if payload is not None else None, headers or {})
        response = connection.getresponse()
        body = response.read()
        result = (response.status, body, dict(response.getheaders()))
        connection.close()
        return result

    def auth(self):
        _, body, _ = self.request('GET', '/api/tickets')
        return {'Content-Type':'application/json', 'X-Queue-Token':json.loads(body)['token']}

    def test_assets_and_security_headers(self):
        for path in ('/', '/style.css', '/main.js'):
            code, body, headers = self.request('GET', path)
            self.assertEqual(code, 200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_web_lifecycle(self):
        headers = self.auth()
        code, body, _ = self.request('POST', '/api/tickets', {'title':'Web example', 'priority':1}, headers)
        self.assertEqual(code, 200)
        ticket = json.loads(body)
        code, body, _ = self.request('POST', '/api/start-next', {}, headers)
        self.assertEqual(json.loads(body)['id'], ticket['id'])
        code, body, _ = self.request('POST', '/api/resolve', {'id':ticket['id']}, headers)
        self.assertEqual(json.loads(body)['status'], 'resolved')
        code, _, _ = self.request('POST', '/api/resolve', {'id':ticket['id']}, headers)
        self.assertEqual(code, 400)

    def test_requires_token(self):
        self.assertEqual(self.request('POST','/api/tickets',{}, {'Content-Type':'application/json'})[0],403)

    def test_rejects_foreign_origin(self):
        headers = self.auth(); headers['Origin'] = 'https://example.com'
        self.assertEqual(self.request('POST','/api/start-next',{},headers)[0],403)

    def test_rejects_foreign_host(self):
        self.assertEqual(self.request('GET','/api/tickets',headers={'Host':'attacker.test'})[0],403)

    def test_rejects_invalid_payloads(self):
        for payload in ([], {'title':42}, {'title':' '}, {'title':'x','priority':True}, {'title':'x'*161}):
            self.assertEqual(self.request('POST','/api/tickets',payload,self.auth())[0],400)

    def test_rejects_oversized_request(self):
        self.assertEqual(self.request('POST','/api/tickets',{'title':'x'*5000},self.auth())[0],413)

    def test_no_arbitrary_file_access(self):
        self.assertEqual(self.request('GET','/../app.py')[0],404)

    def test_wrong_content_type(self):
        headers = self.auth(); headers['Content-Type']='text/plain'
        self.assertEqual(self.request('POST','/api/tickets',{},headers)[0],415)

    def test_missing_route(self):
        self.assertEqual(self.request('POST','/api/missing',{},self.auth())[0],404)


if __name__ == '__main__':
    unittest.main()
