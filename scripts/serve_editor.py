# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2,<3", "gguf==0.19.0", "threadpoolctl>=3,<4", "psutil>=6,<8"]
# ///
"""本机编辑器服务：静态页面＋一级切片任务；只绑定 IPv4/IPv6 回环。"""
import argparse
import functools
import ipaddress
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import slice1

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'prototype/editor_ux/20261122-055413-124110'


class Jobs:
    def __init__(self, store=slice1.STORE):
        self.store = Path(store)
        self.process = None
        self.job = None
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)

    def active(self):
        if self.process is not None and self.process.poll() is None:
            try:
                if slice1.read_json(self.job / 'status.json')['state'] in ('complete','partial','cancelled','failed'):
                    return None
            except (OSError, ValueError, KeyError):
                pass
            return self.job.name
        return None

    def start(self, request):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                status = slice1.read_json(self.job / 'status.json')
                if status['state'] in ('complete','partial','cancelled','failed'):
                    # 完成标记已发布，但进程可能仍回收读取器；等它正常退出，不并发启动第二个计算进程。
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError('已完成任务仍在回收进程，请稍后再试')
                else:
                    raise RuntimeError('已有切片任务正在运行，请先等待或取消')
            self.job = slice1.create_job(request, self.store)
            env = {**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'}
            with (self.job / 'process.log').open('x', encoding='utf-8') as log:
                self.process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'scripts/slice1.py'), '--job', str(self.job)],
                                                cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
            return slice1.read_json(self.job / 'status.json')

    def path(self, ident):
        if not ident.startswith('slice-') or any(c not in 'slice-0123456789' for c in ident):
            raise ValueError('任务编号无效')
        job = self.store / 'jobs' / ident
        if not job.is_dir():
            raise FileNotFoundError('任务不存在')
        return job

    def status(self, ident):
        job = self.path(ident)
        result = slice1.read_json(job / 'status.json')
        if result['state'] in ('running', 'queued') and (self.job is None or self.job.name != ident or not self.active()):
            result = {**result, 'state': 'interrupted', 'stage': '任务进程已退出；再次切片可复用已完成张量'}
        return result

    def cancel(self, ident):
        job = self.path(ident)
        if self.active() != ident:
            raise ValueError('任务没有运行')
        (job / 'cancel').touch(exist_ok=True)
        return {'id': ident, 'state': 'cancelling'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, bundle, jobs, port, **kwargs):
        self.bundle, self.jobs, self.port = Path(bundle).resolve(), jobs, port
        super().__init__(*args, directory=str(self.bundle), **kwargs)

    def allowed(self, write=False):
        try:
            address = ipaddress.ip_address(self.client_address[0])
            if not address.is_loopback:
                return False
        except ValueError:
            return False
        hosts = {f'localhost:{self.port}', f'127.0.0.1:{self.port}', f'[::1]:{self.port}'}
        if self.headers.get('Host') not in hosts:
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + h for h in hosts}:
            return False
        return not write or secrets.compare_digest(self.headers.get('X-Snowglass-Token', ''), self.jobs.token)

    def send_json(self, value, code=200):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def file_response(self, path):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.allowed():
            self.send_json({'error': '仅允许本机同源访问'}, 403)
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == '/api/slice1/capabilities':
                self.send_json({'kind': 'snowglass.slice1-service.v1', 'token': self.jobs.token,
                                'active': self.jobs.active(), 'recipe': 'on-demand-v1', 'default_grid': slice1.DEFAULT_GRID,
                                                                'sources': list(slice1.CHANNELS), 'conventions': ['gguf','hf'], 'optional_diagnostics': True})
            elif path.startswith('/api/slice1/jobs/'):
                parts = path.split('/')
                if len(parts) != 6:
                    raise ValueError('任务路径无效')
                ident, action = parts[4:]
                if action == 'status':
                    self.send_json(self.jobs.status(ident))
                elif action == 'manifest':
                    self.file_response(self.jobs.path(ident) / 'manifest.json')
                else:
                    raise FileNotFoundError('未知任务资源')
            elif path.startswith('/api/slice1/files/'):
                resource = (self.jobs.store / path[len('/api/slice1/files/'):]).resolve()
                if not resource.is_relative_to((self.jobs.store / 'artifacts').resolve()) or resource.name != 'result.json':
                    raise ValueError('只提供完成的张量统计，不提供原权重')
                if not (resource.parent / 'complete.json').exists():
                    raise FileNotFoundError('张量尚未完成')
                self.file_response(resource)
            elif path.startswith('/api/'):
                raise FileNotFoundError('未知接口')
            else:
                target = Path(self.translate_path(path)).resolve()
                if not target.is_relative_to(self.bundle):
                    self.send_json({'error': '静态路径越界'}, 403)
                    return
                super().do_GET()
        except FileNotFoundError as e:
            self.send_json({'error': str(e)}, 404)
        except (ValueError, KeyError) as e:
            self.send_json({'error': str(e)}, 400)

    def do_POST(self):
        if not self.allowed(write=True):
            self.send_json({'error': '需要本机同源任务令牌'}, 403)
            return
        try:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('仅接受 JSON')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 131072:
                raise ValueError('请求大小无效')
            request = json.loads(self.rfile.read(length).decode('utf-8'))
            path = urlsplit(self.path).path
            if path == '/api/slice1/plan':
                plan = slice1.make_plan(request)
                self.send_json({k: plan[k] for k in ('request', 'block_count', 'tensor_count', 'signature', 'recipe', 'note')})
            elif path == '/api/slice1/start':
                self.send_json(self.jobs.start(request), 202)
            elif path.startswith('/api/slice1/jobs/') and path.endswith('/cancel'):
                parts = path.split('/')
                if len(parts) != 6:
                    raise ValueError('任务路径无效')
                self.send_json(self.jobs.cancel(parts[4]), 202)
            else:
                self.send_json({'error': '未知接口'}, 404)
        except RuntimeError as e:
            self.send_json({'error': str(e)}, 409)
        except (ValueError, KeyError, FileNotFoundError, TypeError) as e:
            self.send_json({'error': str(e)}, 400)

    def list_directory(self, path):
        self.send_error(403, 'Directory listing is disabled')
        return None

    def do_HEAD(self):
        target=Path(self.translate_path(unquote(urlsplit(self.path).path))).resolve()
        if self.allowed() and target.is_relative_to(self.bundle) and not self.path.startswith('/api/'):
            super().do_HEAD()
        else:
            self.send_error(403)

    def log_message(self, fmt, *args):
        if '/api/slice1/jobs/' not in str(args[0] if args else ''):
            super().log_message(fmt, *args)


class IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8128)
    args = parser.parse_args()
    jobs = Jobs()
    handler = functools.partial(Handler, bundle=BUNDLE, jobs=jobs, port=args.port)
    servers = [ThreadingHTTPServer(('127.0.0.1', args.port), handler)]
    try:
        servers.append(IPv6Server(('::1', args.port), handler))
    except OSError as e:
        print('IPv6 回环不可用，请使用 127.0.0.1：' + str(e), flush=True)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'snowglass 本机计算服务 http://localhost:{args.port}/ （仅回环；旧缓存不覆盖）', flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if jobs.active():
            jobs.cancel(jobs.active())
            jobs.process.wait(timeout=15)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
