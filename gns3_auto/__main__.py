import argparse
import io
import json
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .core import plan, configs, GNS3


def archive(lab):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in configs(lab).items():
            z.writestr(name, content)
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            self.reply(200, b'{"status":"ok","mode":"design-only"}', 'application/json')
        elif self.path == '/':
            self.reply(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        else:
            self.reply(404, b'Not found', 'text/plain')

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/api/plan', '/api/export'):
            return self.reply(404, b'Not found', 'text/plain')
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 20000:
                raise ValueError('요청 크기가 올바르지 않습니다.')
            request = json.loads(self.rfile.read(size))
            lab = plan(request.get('prompt'))
            if self.path == '/api/export':
                return self.reply(200, archive(lab), 'application/zip')
            self.reply(200, json.dumps({'plan': lab, 'configs': configs(lab)}, ensure_ascii=False).encode(), 'application/json')
        except (ValueError, TypeError, AttributeError) as exc:
            self.reply(400, json.dumps({'error': str(exc)}, ensure_ascii=False).encode(), 'application/json')


def main():
    parser = argparse.ArgumentParser(description='GNS3 redundancy lab assistant (constrained planner)')
    sub = parser.add_subparsers(dest='command', required=True)
    web = sub.add_parser('serve')
    web.add_argument('--host', default='127.0.0.1')
    web.add_argument('--port', type=int, default=8080)
    generate = sub.add_parser('plan')
    generate.add_argument('prompt')
    generate.add_argument('--output', default='lab.zip')
    inspect = sub.add_parser('inspect', help='Read GNS3 v2 version and templates')
    inspect.add_argument('--url', required=True)
    deploy = sub.add_parser('deploy', help='Create stopped nodes and links; no configuration injection')
    deploy.add_argument('--url', required=True)
    deploy.add_argument('--router-template', required=True)
    deploy.add_argument('--host-template', required=True)
    deploy.add_argument('--confirm-create', action='store_true', required=True)
    args = parser.parse_args()
    if args.command == 'serve':
        print(f'Design assistant listening on {args.host}:{args.port}', flush=True)
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    elif args.command == 'plan':
        target = Path(args.output)
        # Never overwrite a user's existing artifact.
        with target.open('xb') as out:
            out.write(archive(plan(args.prompt)))
        print(f'Created {target}; design only, not a validated network.')
    else:
        api = GNS3(args.url)
        result = api.inspect() if args.command == 'inspect' else api.deploy(
            plan('VRRP OSPF 이중화'), args.router_template, args.host_template)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
