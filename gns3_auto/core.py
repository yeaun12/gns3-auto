"""Dependency-free lab planner. Generated configurations are reviewable artifacts."""
import ipaddress
import json
import urllib.request
import urllib.error


def plan(prompt):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
        raise ValueError('요청은 1~4000자로 입력하세요.')
    # A deliberately constrained intent parser; never invent unsupported execution.
    if not any(word in prompt.lower() for word in ('이중화', 'vrrp', 'ospf', 'redundan', 'failover')):
        raise ValueError('현재는 VRRP/OSPF 이중화 실습만 지원합니다. 요청에 이중화 또는 OSPF를 포함하세요.')
    return {
        'schema_version': 1, 'name': 'redundant-lab', 'request': prompt,
        'mode': 'design-only',
        'assumptions': ['고정된 3라우터·2호스트 IPv4 실습입니다.',
                        'VRRP는 keepalived, OSPF는 FRRouting 구성을 생성합니다.',
                        'GNS3 장비 템플릿은 eth0부터 순서대로 3개 이상의 Ethernet 포트를 제공해야 합니다.',
                        '설정은 자동 주입하지 않습니다. 이미지별 적용 및 실행 권한을 확인해야 합니다.'],
        'nodes': [{'name': n, 'role': 'host' if n.startswith('PC') else 'router'}
                  for n in ['PC1', 'R1', 'R2', 'R3', 'PC2']],
        'links': [
            {'a': 'PC1', 'ap': 0, 'b': 'LAN', 'bp': 0},
            {'a': 'R1', 'ap': 0, 'b': 'LAN', 'bp': 1},
            {'a': 'R2', 'ap': 0, 'b': 'LAN', 'bp': 2},
            {'a': 'R1', 'ap': 1, 'b': 'R3', 'bp': 0},
            {'a': 'R2', 'ap': 1, 'b': 'R3', 'bp': 1},
            {'a': 'R3', 'ap': 2, 'b': 'PC2', 'bp': 0}],
        'addresses': {'PC1': ['192.168.10.10/24'], 'R1': ['192.168.10.2/24', '10.0.13.1/30'],
                      'R2': ['192.168.10.3/24', '10.0.23.1/30'],
                      'R3': ['10.0.13.2/30', '10.0.23.2/30', '192.168.20.1/24'],
                      'PC2': ['192.168.20.10/24']},
        'vip': '192.168.10.1/24',
        'checks': ['PC1 → 192.168.20.10 연속 ping', 'R1/R2/R3 OSPF 인접 관계 확인',
                   'R1 정지 후 R2가 VIP를 인계하고 ping이 복구되는지 확인',
                   'R1 복구 후 우선순위 150으로 재선출되는지 확인'],
        'limitations': ['실제 전환 시간·패킷 손실은 연결된 실습에서 측정해야 합니다.',
                        '업링크 장애 감지는 이 초안에 포함되지 않습니다. R1 전체 정지 시나리오입니다.']}


def configs(lab):
    files = {}
    for index, name in enumerate(('R1', 'R2', 'R3'), 1):
        lines = ['frr defaults traditional', f'hostname {name}', 'service integrated-vtysh-config', 'ip forwarding']
        for port, addr in enumerate(lab['addresses'][name]):
            ipaddress.ip_interface(addr)
            lines += [f'interface eth{port}', f' ip address {addr}', ' ip ospf area 0', '!']
        lines += ['router ospf', f' ospf router-id {index}.{index}.{index}.{index}']
        if name in ('R1', 'R2'):
            lines += [' passive-interface eth0']
        else:
            lines += [' passive-interface eth2']
        files[f'{name}/frr.conf'] = '\n'.join(lines) + '\n'
        files[f'{name}/daemons'] = 'zebra=yes\nospfd=yes\nvtysh_enable=yes\n'
        if name != 'R3':
            priority = 150 if name == 'R1' else 100
            files[f'{name}/keepalived.conf'] = f'''vrrp_instance LAN {{
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority {priority}
    advert_int 1
    virtual_ipaddress {{
        {lab['vip']} dev eth0
    }}
}}
'''
    files['hosts.txt'] = ('PC1 (VPCS): ip 192.168.10.10/24 192.168.10.1\n'
                          'PC2 (VPCS): ip 192.168.20.10/24 192.168.20.1\n')
    files['README.txt'] = ('DESIGN ARTIFACTS ONLY — not an executed or validated network.\n'
        'Use isolated FRRouting + keepalived Linux routers with eth0/eth1/eth2.\n'
        'Enable IPv4 forwarding, FRR zebra/ospfd and keepalived in each router image.\n'
        'Review multicast VRRP support and NET_ADMIN/NET_RAW capabilities.\n'
        'Apply frr.conf, daemons and keepalived.conf via image-supported mechanisms.\n'
        'The deploy command creates stopped nodes and links only; no config injection.\n'
        'Do not run these router configs on the development host.\n')
    files['plan.json'] = json.dumps(lab, ensure_ascii=False, indent=2)
    return files


class GNS3:
    def __init__(self, url):
        if not url.startswith(('http://', 'https://')):
            raise ValueError('GNS3 URL must use http:// or https://')
        self.url = url.rstrip('/')

    def call(self, path, data=None, method=None):
        req = urllib.request.Request(self.url + '/v2' + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read()
            return json.loads(body) if body else None

    def inspect(self):
        return {'version': self.call('/version'), 'templates': self.call('/templates')}

    def deploy(self, lab, router_template, host_template):
        templates = self.call('/templates')
        ids = {t['template_id'] for t in templates}
        if router_template not in ids or host_template not in ids:
            raise ValueError('Both template IDs must exist on the GNS3 server.')
        project = self.call('/projects', {'name': lab['name']})
        pid = project['project_id']
        nodes = {}
        try:
            for i, node in enumerate(lab['nodes']):
                tid = host_template if node['role'] == 'host' else router_template
                created = self.call(f'/projects/{pid}/templates/{tid}',
                                    {'x': i * 180 - 360, 'y': 0, 'name': node['name']})
                nodes[node['name']] = created['node_id']
            switch = self.call(f'/projects/{pid}/nodes', {
                'name': 'LAN', 'node_type': 'ethernet_switch', 'compute_id': 'local', 'x': -180, 'y': 160})
            nodes['LAN'] = switch['node_id']
            for link in lab['links']:
                self.call(f'/projects/{pid}/links', {'nodes': [
                    {'node_id': nodes[link['a']], 'adapter_number': link['ap'] if link['a'] != 'LAN' else 0,
                     'port_number': link['ap'] if link['a'] == 'LAN' else 0},
                    {'node_id': nodes[link['b']], 'adapter_number': link['bp'] if link['b'] != 'LAN' else 0,
                     'port_number': link['bp'] if link['b'] == 'LAN' else 0}]})
        except Exception as exc:
            raise RuntimeError(f'Deployment incomplete. Inspect project {pid}; it was preserved for diagnosis. {exc}') from exc
        return {'project_id': pid, 'status': 'created-stopped', 'configuration_applied': False,
                'message': 'Review and apply exported configurations before starting nodes.'}
