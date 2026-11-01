"""Loopback-only stdlib server. Run: python server.py --port 8765 --db errands.db."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from errand.agent import Agent

STATIC = Path(__file__).resolve().parent / 'static'


def handler(agent):
    class Handler(BaseHTTPRequestHandler):
        def finish(self):
            try:
                super().finish()
            finally:
                agent.store.close_thread()

        def send(self, code, body, content_type='application/json; charset=utf-8'):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/api/state':
                return self.send(200, agent.snapshot(parse_qs(url.query).get('session_id', [None])[0]))
            path = (STATIC / (url.path.lstrip('/') or 'index.html')).resolve()
            if not path.is_relative_to(STATIC) or not path.is_file():
                return self.send(404, {'error': 'Not found'})
            self.send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = {'http://127.0.0.1:'+str(self.server.server_port), 'http://localhost:'+str(self.server.server_port)}
            if origin and origin not in expected:
                return self.send(403, {'error': 'Only the local app may mutate state.'})
            if self.path != '/api/action':
                return self.send(404, {'error': 'Not found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError()
                self.connection.settimeout(5)
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, OSError):
                return self.send(400, {'error': 'Send a JSON object under 16 KiB.'})
            self.send(200, agent.act(data.get('session_id'), data.get('event'), data.get('payload', {})))

    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', default='.data/errands.db')
    args = parser.parse_args()
    agent = Agent(args.db)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(agent))
    print(f'Consider it done: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        agent.close()
