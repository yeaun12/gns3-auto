import io
import json
import threading
import unittest
import urllib.request
import urllib.error
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from gns3_auto.core import plan, configs, GNS3
from gns3_auto.__main__ import Handler, archive


class PlannerTests(unittest.TestCase):
    def test_redundancy_configuration(self):
        lab = plan('OSPF와 VRRP 이중화')
        files = configs(lab)
        self.assertEqual(len(lab['links']), 6)
        self.assertIn('priority 150', files['R1/keepalived.conf'])
        self.assertIn('priority 100', files['R2/keepalived.conf'])
        self.assertIn('192.168.10.1/24', files['R1/keepalived.conf'])
        self.assertIn('passive-interface eth2', files['R3/frr.conf'])
        self.assertIn('ospfd=yes', files['R3/daemons'])
        with zipfile.ZipFile(io.BytesIO(archive(lab))) as z:
            self.assertEqual(json.loads(z.read('plan.json'))['mode'], 'design-only')
            self.assertIn('R1/keepalived.conf', z.namelist())

    def test_reject_unsupported_or_invalid_requests(self):
        for prompt in ('', 'BGP 설정', None, 'OSPF' * 1001):
            with self.assertRaises(ValueError):
                plan(prompt)

    def test_gns3_deployment_contract(self):
        calls = []
        def fake(path, data=None, method=None):
            calls.append((path, data))
            if path == '/templates':
                return [{'template_id': 'router'}, {'template_id': 'host'}]
            if path == '/projects':
                return {'project_id': 'test-project'}
            if '/templates/' in path or path.endswith('/nodes'):
                return {'node_id': data['name']}
            return {}
        api = GNS3('http://localhost:3080')
        with patch.object(api, 'call', side_effect=fake):
            result = api.deploy(plan('이중화'), 'router', 'host')
        self.assertFalse(result['configuration_applied'])
        links = [data for path, data in calls if path.endswith('/links')]
        self.assertEqual(len(links), 6)
        lan_link = links[2]['nodes'][1]
        self.assertEqual(lan_link, {'node_id': 'LAN', 'adapter_number': 0, 'port_number': 2})
        self.assertFalse(any('/start' in path for path, _ in calls))

    def test_missing_template_does_not_create_project(self):
        api = GNS3('http://localhost:3080')
        with patch.object(api, 'call', return_value=[]) as call:
            with self.assertRaises(ValueError):
                api.deploy(plan('이중화'), 'missing', 'missing')
            self.assertEqual(call.call_count, 1)

    def test_partial_deployment_reports_project(self):
        api = GNS3('http://localhost:3080')
        with patch.object(api, 'call', side_effect=[
                [{'template_id': 'r'}, {'template_id': 'h'}], {'project_id': 'recover-me'}, OSError('offline')]):
            with self.assertRaisesRegex(RuntimeError, 'recover-me'):
                api.deploy(plan('이중화'), 'r', 'h')


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, path, prompt):
        return urllib.request.urlopen(urllib.request.Request(self.base + path,
            data=json.dumps({'prompt': prompt}).encode(), headers={'Content-Type': 'application/json'}))

    def test_home_and_health(self):
        with urllib.request.urlopen(self.base + '/') as r:
            self.assertIn(b'GNS3 Lab Studio', r.read())
        with urllib.request.urlopen(self.base + '/api/health') as r:
            self.assertEqual(json.load(r)['status'], 'ok')

    def test_plan_and_export(self):
        with self.post('/api/plan', 'VRRP 이중화') as r:
            self.assertIn('R2/keepalived.conf', json.load(r)['configs'])
        with self.post('/api/export', 'OSPF') as r:
            with zipfile.ZipFile(io.BytesIO(r.read())) as z:
                self.assertIn('hosts.txt', z.namelist())

    def test_invalid_request(self):
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.post('/api/plan', 'unsupported')
        self.assertEqual(err.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
