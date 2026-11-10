import io
import json
import queue
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from openpyxl import load_workbook
from gui import app
from gui.test_china_sites import response


class ChinaIntegrationTests(unittest.TestCase):
    def test_china_only_does_not_search_international_sites(self):
        events = queue.Queue()
        with patch('requests.get', side_effect=lambda url, **kwargs: response(404, '', url)):
            app.search_worker('example', 5, events, 'china')
        items = []
        while not events.empty(): items.append(events.get())
        self.assertEqual(items[0], {'type': 'total', 'total': 7})
        results = [r for r in items if r['type'] == 'result']
        self.assertEqual({r['site'] for r in results}, {'Gitee', 'CNblogs', 'V2EX', 'CSDN', 'SegmentFault', 'Zhihu', 'Douban'})
        self.assertTrue(all(r['region'] == 'china' for r in results))
        self.assertEqual(items[-1]['type'], 'done')

    def test_global_search_deduplicates_gitee_and_still_excludes_nsfw(self):
        with patch('requests.get', side_effect=lambda url, **kwargs: response(200, '', url)):
            sites = app.load_site_data('all')
        self.assertIn('GitHub', sites)
        self.assertNotIn('Gitee', sites)
        self.assertNotIn('Xvideos', sites)
        self.assertEqual(app.load_site_data('china'), {})

    def test_connection_error_is_inconclusive(self):
        import requests
        from gui.china_sites import search_china
        with patch('requests.get', side_effect=requests.exceptions.SSLError('untrusted')):
            rows = list(search_china('example', 5))
        self.assertTrue(all(r['status'] == 'Unknown' for r in rows))

    def test_scope_validation_catalog_and_export(self):
        old_state = app.state
        app.state = app.State()
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            req = urllib.request.Request(base+'/api/start', data=b'{"username":"example","scope":"bad"}',
                headers={'X-Sherlock-Token': app.TOKEN}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as result: urllib.request.urlopen(req)
            self.assertEqual(result.exception.code, 400)
            state = json.load(urllib.request.urlopen(base+'/api/state'))
            self.assertEqual(state['status'], 'idle')
            self.assertIn('博客园', state['china_sites'])
            app.state.username = 'example'
            app.state.rows = [dict(username='=FORMULA()', site='CNblogs', display_name='博客园',
                region='china', status='Unknown', url='https://www.cnblogs.com/example', detail='未能确认')]
            state = json.load(urllib.request.urlopen(base+'/api/state'))
            self.assertEqual(len(state['manual_sites']), 4)
            book = load_workbook(io.BytesIO(urllib.request.urlopen(base+'/api/export').read()))
            row = [c.value for c in book.active[2]]
            self.assertIn('博客园', row)
            self.assertIn('未能确认', row)
            self.assertEqual(book.active['A2'].data_type, 's')
        finally:
            server.shutdown()
            server.server_close()
            app.state = old_state


if __name__ == '__main__': unittest.main()
