"""
レガシー: Start が Plan/Guard に直結していたセッションを Start→Game→Plan 形式へ変換する。
"""
import copy
import json
import uuid


def _new_graph_id():
    return '0x' + uuid.uuid4().hex[:12]


def _out_targets_for_node(connections, node_id):
    """out ポートから接続先ノードIDのリスト"""
    targets = []
    for c in connections:
        out = c.get('out') or []
        inn = c.get('in') or []
        if len(out) >= 2 and out[0] == node_id and out[1] == 'out' and inn:
            targets.append(inn[0])
    return targets


def migrate_legacy_start_game_session(data):
    """
    セッションディクショナリを原状更新する。
    トップレベル nodes/connections または graph.nodes / graph.connections に対応。
    """
    if not isinstance(data, dict):
        return
    nodes = None
    connections = None
    container = None
    if isinstance(data.get('nodes'), dict):
        nodes = data['nodes']
        connections = data.setdefault('connections', [])
        container = data
    elif isinstance(data.get('graph'), dict) and isinstance(data['graph'].get('nodes'), dict):
        g = data['graph']
        nodes = g['nodes']
        connections = g.setdefault('connections', data.get('connections', []))
        container = g
    else:
        return
    if not isinstance(connections, list):
        return

    for nid, nd in list(nodes.items()):
        if nd.get('type_') != 'macro.nodes.StartNode':
            continue
        targets = _out_targets_for_node(connections, nid)
        legacy = False
        has_game = False
        for tid in targets:
            tnd = nodes.get(tid) or {}
            tt = tnd.get('type_')
            if tt == 'macro.nodes.GameNode':
                has_game = True
            if tt in ('macro.nodes.PlanNode', 'macro.nodes.GuardNode'):
                legacy = True
        if not legacy or has_game:
            continue

        orig = copy.deepcopy(nd)
        nd['type_'] = 'macro.nodes.GameNode'
        if nd.get('name') in ('Start', '', None):
            nd['name'] = 'Game'
        nd.setdefault('custom', {})
        c = nd['custom']
        for k in ('plan_nodes_order', 'guard_nodes_order', 'daily_variables', 'reset_time', 'connected_nodes_order'):
            c.setdefault(k, '[]' if k != 'reset_time' else '05:00:00')

        new_id = _new_graph_id()
        while new_id in nodes:
            new_id = _new_graph_id()

        pos = list(orig.get('pos') or [0, 0])
        if len(pos) >= 2:
            pos[0] -= 180.0

        start_node = {
            'type_': 'macro.nodes.StartNode',
            'icon': orig.get('icon'),
            'name': 'Start',
            'color': [50, 150, 50, 255],
            'border_color': orig.get('border_color', [74, 84, 85, 255]),
            'text_color': orig.get('text_color', [255, 255, 255, 180]),
            'disabled': orig.get('disabled', False),
            'selected': False,
            'visible': orig.get('visible', True),
            'width': orig.get('width', 160),
            'height': orig.get('height', 60),
            'pos': pos,
            'layout_direction': orig.get('layout_direction', 0),
            'port_deletion_allowed': orig.get('port_deletion_allowed', False),
            'subgraph_session': orig.get('subgraph_session', {}),
            'custom': {
                'label': '',
                'connected_nodes_order': '[]',
                'game_nodes_order': json.dumps([nid], ensure_ascii=False),
            },
        }
        nodes[new_id] = start_node
        connections.append({'out': [new_id, 'out'], 'in': [nid, 'in']})
