"""Local Sherlock interface; no external web dependencies."""
import io
import json
import multiprocessing as mp
import queue
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from gui.china_sites import SITES, manual_searches, search_china

ROOT = Path(__file__).resolve().parents[1]
TOKEN = secrets.token_urlsafe(24)


def load_site_data(scope):
    if scope == 'china':
        return {}
    if scope != 'all':
        raise ValueError('未知搜索范围')
    from sherlock_project.sites import SitesInformation
    sites = SitesInformation(str(ROOT / 'sherlock_project/resources/data.json'))
    sites.remove_nsfw_sites()
    return {s.name: s.information for s in sites if s.name not in SITES}


def search_worker(username, timeout, events, scope='all'):
    try:
        from sherlock_project.notify import QueryNotify
        from sherlock_project.sherlock import sherlock
        class Notify(QueryNotify):
            def update(self, result):
                events.put({'type': 'result', 'site': result.site_name, 'url': result.site_url_user,
                            'status': str(result.status), 'username': result.username,
                            'region': 'china' if result.site_name == 'Vjudge' else 'other'})
        data = load_site_data(scope)
        events.put({'type': 'total', 'total': len(data) + len(SITES)})
        for row in search_china(username, timeout):
            events.put({'type': 'result', **row})
        if data:
            sherlock(username, data, Notify(), timeout=timeout)
        events.put({'type': 'done'})
    except Exception as exc:
        events.put({'type': 'error', 'message': str(exc)})


class State:
    def __init__(self):
        self.process = None
        self.events = None
        self.rows = []
        self.status = 'idle'
        self.total = 0
        self.error = ''
        self.scope = 'all'
        self.username = ''
        self.lock = threading.Lock()

    def drain(self):
        if self.events:
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                if event['type'] == 'result': self.rows.append(event)
                elif event['type'] == 'total': self.total = event['total']
                elif event['type'] == 'done': self.status = 'done'
                elif event['type'] == 'error':
                    self.status, self.error = 'error', event['message']

state = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, body, kind='application/json', status=200):
        if isinstance(body, dict): body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self.reply((ROOT / 'gui/index.html').read_bytes().replace(b'__TOKEN__', TOKEN.encode()), 'text/html; charset=utf-8')
        elif path == '/api/state':
            with state.lock:
                state.drain()
                self.reply(dict(status=state.status, total=state.total, rows=state.rows, error=state.error,
                                scope=state.scope, username=state.username,
                                china_sites=[s['name'] for s in SITES.values()],
                                manual_sites=manual_searches(state.username)))
        elif path == '/api/export':
            from openpyxl import Workbook
            with state.lock: rows = list(state.rows)
            book = Workbook()
            sheet = book.active
            sheet.title = 'Sherlock'
            sheet.append(['用户名', '网站', '检测状态', '账号链接', '地区', '检测说明'])
            for r in rows:
                values = [r['username'], r.get('display_name', r['site']), r['status'], r['url'],
                          '中国/中文' if r.get('region') == 'china' else '其他', r.get('detail', '')]
                sheet.append(values)
                for cell in sheet[sheet.max_row]: cell.data_type = 's'
            for col, width in [('A', 25), ('B', 30), ('C', 20), ('D', 80), ('E', 16), ('F', 65)]: sheet.column_dimensions[col].width = width
            sheet.freeze_panes = 'A2'
            stream = io.BytesIO()
            book.save(stream)
            self.reply(stream.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        else: self.reply({'error': 'Not found'}, status=404)

    def do_POST(self):
        if self.headers.get('X-Sherlock-Token') != TOKEN:
            return self.reply({'error': '请求验证失败'}, status=403)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size > 4096: raise ValueError('请求过长')
            data = json.loads(self.rfile.read(size) or b'{}')
            with state.lock:
                if self.path == '/api/start':
                    if state.process and state.process.is_alive(): raise ValueError('请先停止当前搜索')
                    username = data.get('username', '').strip()
                    if not username or len(username) > 100 or any(c.isspace() for c in username): raise ValueError('请输入一个有效用户名（不含空格）')
                    timeout = int(data.get('timeout', 15))
                    if not 5 <= timeout <= 60: raise ValueError('超时范围为 5–60 秒')
                    scope = data.get('scope', 'all')
                    if scope not in ('all', 'china'): raise ValueError('未知搜索范围')
                    state.scope, state.username = scope, username
                    state.rows, state.total, state.error, state.status = [], 0, '', 'running'
                    state.events = mp.Queue()
                    state.process = mp.Process(target=search_worker, args=(username, timeout, state.events, scope), daemon=True)
                    state.process.start()
                elif self.path == '/api/stop':
                    if state.process and state.process.is_alive():
                        state.process.terminate()
                        state.process.join(3)
                    state.drain()
                    state.status = 'stopped'
                else: raise ValueError('未知操作')
            self.reply({'ok': True})
        except (ValueError, TypeError) as exc: self.reply({'error': str(exc)}, status=400)


if __name__ == '__main__':
    mp.set_start_method('spawn')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    address = f'http://127.0.0.1:{server.server_port}'
    print(f'Sherlock GUI: {address}', flush=True)
    threading.Timer(0.7, lambda: webbrowser.open(address)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        if state.process and state.process.is_alive(): state.process.terminate()
        server.server_close()
