import argparse
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from engine.session import Session

WEB = Path(__file__).resolve().parent / "web"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'")
        super().end_headers()

    def reply(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/status":
            return self.reply(200, self.server.session.info())
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/run":
            return self.reply(404, {"error": "Not found"})
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        if host not in (expected, f"localhost:{self.server.server_port}"):
            return self.reply(403, {"error": "Local requests only"})
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            return self.reply(403, {"error": "Cross-origin requests are not allowed"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"error": "Send JSON"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2048:
                return self.reply(413, {"error": "Request is too large or empty"})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            result = self.server.session.run(data.get("prompt"), data.get("lie"))
        except (ValueError, TypeError):
            return self.reply(400, {"error": "Use a short English prompt and an optional server letter"})
        except (OSError, EOFError, RuntimeError):
            return self.reply(503, {"error": "A server disconnected or timed out. Restart the server and retry."})
        self.reply(200, result)


def main():
    parser = argparse.ArgumentParser(description="Blindfold: private, checked inference demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--servers", type=int, default=3, help="How many local servers to start (2 or more)")
    parser.add_argument("--nodes", nargs="+", metavar="SPEC",
                        help="Two or more endpoints: local, tcp:host:port, or serial:device (instead of --servers)")
    args = parser.parse_args()
    with Session(args.nodes, args.servers) as session:
        with HTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.session = session
            print(f"Blindfold: http://127.0.0.1:{server.server_port}/", flush=True)
            print(f"{len(session.specs)} servers ready. Ctrl-C stops the web server and local servers.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
