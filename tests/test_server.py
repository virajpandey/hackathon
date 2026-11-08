import http.client
import json
import threading
import unittest
from http.server import HTTPServer

from engine.session import Session
from run import Handler


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session().__enter__()
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.server.session = cls.session
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.session.close()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        try:
            body = json.dumps(data) if data is not None else None
            connection.request(method, path, body, {"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_status(self):
        status, _, body = self.request("GET", "/api/status")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["parameters"], 19295)
        self.assertEqual(data["nodes"], {node: "local process" for node in "ABC"})

    def test_live_then_tampered_then_recovered(self):
        for lie in [None, "A", "B", "C", None]:
            status, _, body = self.request("POST", "/api/run", {"prompt": "patient reports knee", "lie": lie})
            result = json.loads(body)
            self.assertEqual(status, 200, body)
            self.assertEqual(result["caught"], lie is not None)
            if lie:
                accepted = len(result["steps"])
                self.assertEqual(accepted, result["rejected_character"])
                self.assertGreater(accepted, 0)
                self.assertTrue(honest_text.startswith(result["private_text"]))
                self.assertIn(result["client_exchange_phases"], (accepted * 2 + 1, accepted * 2 + 2))
            else:
                self.assertTrue(result["bit_exact"])
                self.assertEqual(result["client_exchange_phases"], len(result["steps"]) * 2)
                honest_text = result["private_text"]

    def test_bad_requests_do_not_run(self):
        for data in [None, [], {"prompt": ""}, {"prompt": 12}, {"prompt": "x" * 121},
                     {"prompt": "hello", "lie": "D"}]:
            status, _, _ = self.request("POST", "/api/run", data)
            self.assertIn(status, (400, 413))

    def test_cross_origin_and_host_rejected(self):
        for headers in [{"Origin": "https://other.example"}, {"Host": "other.example"}]:
            status, _, _ = self.request("POST", "/api/run", {"prompt": "patient reports chest"}, headers)
            self.assertEqual(status, 403)

    def test_static_pages_and_no_external_dependencies(self):
        for path in ["/", "/demo.html", "/whiteboard.html", "/slides.html"]:
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
            self.assertNotIn(b'src="https://', body)
            self.assertNotIn(b'href="https://fonts.', body)

    def test_source_and_git_not_served(self):
        for path in ["/engine/private_lm_model.json", "/.git/config", "/../run.py"]:
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
