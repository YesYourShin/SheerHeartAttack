"""
통합 RuleNode 기반 매크로 실행 엔진.

실행 로직:
1. Start → 연결된 다음 노드들을 순차적으로 검사
2. RuleNode: 조건 리스트를 모두 확인 → 모두 matched면 동작 리스트 순서대로 실행 → 다음 노드로
3. 한 노드가 not matched면 → 연결된 다른 다음 노드를 검사
4. 모든 다음 노드가 not matched면 → 처음부터 다시 반복
"""
import json
import time
import os
import tempfile
import datetime
from PIL import Image
from library.macro_manager import MacroManager

from framework.variable_manager import VariableManager
from framework.condition_evaluator import ConditionEvaluator
from framework.action_executor import ActionExecutor
from framework.graph_migration import migrate_legacy_start_game_session
import library.adb_manager as adb_manager


class FlowRunner:
    def __init__(self, json_path, progress_callback=None):
        self.json_path = json_path
        self.macro = MacroManager()
        self.nodes = {}
        self.connections = []
        self.is_running = False
        self.progress_callback = progress_callback
        # 現在実行中の Game ノードID（日次変数・上位ガードの基準）
        self.active_game_id = None
        
        # 구조 분할 클래스 인스턴스화
        self.variable_manager = VariableManager(self)
        self.condition_evaluator = ConditionEvaluator(self)
        self.action_executor = ActionExecutor(self)
        # ガードの「全体再開」時にrunループが検知
        self._request_full_restart = False
        # ガード完了後: 現在PlanのルートRuleへ / 指定Planへジャンプ
        self._request_restart_plan = False
        self._request_goto_plan = False
        self._goto_plan_target_id = None
        self._pending_jump_to_plan_id = None
        # goto_plan検証用（run()で設定）
        self._full_plan_ids = []
        # goto_plan や run_from で「この Plan 以降だけ」を走らせる開始インデックス（0 なら Game 内 Plan 全件）
        self._plan_slice_start = 0
        # run_from が Game の out に無いとき 1 回だけ使う Plan ID 列（後方互換）
        self._pending_plan_ids_override = None
        self._default_next_rule_search_timeout_seconds = 5.0

    def _sleep_interruptible(self, seconds, interval=0.02):
        end_at = time.monotonic() + max(0.0, float(seconds))
        while self.is_running and time.monotonic() < end_at:
            remain = end_at - time.monotonic()
            if remain <= 0:
                break
            time.sleep(min(interval, remain))
        return self.is_running

    def _get_next_rule_search_timeout_seconds(self, rule_id):
        default_timeout = self._default_next_rule_search_timeout_seconds
        node = self.nodes.get(rule_id) or {}
        if node.get('type_') != 'macro.nodes.RuleNode':
            return default_timeout
        custom = node.get('custom') or {}
        raw = custom.get('next_rule_search_timeout_seconds', default_timeout)
        try:
            sec = float(raw)
        except (TypeError, ValueError):
            sec = default_timeout
        if sec < 0.5:
            sec = 0.5
        return sec

    def load_graph(self):
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        migrate_legacy_start_game_session(data)
        if isinstance(data.get('nodes'), dict):
            self.nodes = data['nodes']
            self.connections = data.get('connections', [])
        else:
            g = data.get('graph') or {}
            self.nodes = g.get('nodes', {})
            self.connections = g.get('connections', data.get('connections', []))
        for nd in self.nodes.values():
            if 'custom' not in nd:
                nd['custom'] = {}

    def get_entry_start_node_id(self):
        """진입 Start 노드 1개의 ID"""
        for nid, nd in self.nodes.items():
            if nd.get('type_') == 'macro.nodes.StartNode':
                return nid
        return None

    def get_start_node_id(self):
        """後方互換: 진입 Start ID"""
        return self.get_entry_start_node_id()

    def _resolve_full_game_ids(self, entry_start_id):
        """Start の game_nodes_order と out 接続から Game ID リスト"""
        r_node = self.nodes.get(entry_start_id)
        if not r_node:
            return []
        order_json = r_node.get('custom', {}).get('game_nodes_order', '[]')
        ordered_ids = self._load_json_prop(order_json)
        out_ids = self.get_next_node_ids(entry_start_id, 'out')
        result = [nid for nid in ordered_ids if nid in out_ids]
        for nid in out_ids:
            if nid not in result and self.nodes.get(nid, {}).get('type_') == 'macro.nodes.GameNode':
                result.append(nid)
        return result

    def _resolve_full_plan_ids(self, game_id):
        """Game の plan_nodes_order と out から Plan ID リスト"""
        r_node = self.nodes.get(game_id)
        if not r_node:
            return []
        plan_order_json = r_node.get('custom', {}).get('plan_nodes_order', '[]')
        ordered_plan_ids = self._load_json_prop(plan_order_json)
        r_out_ids = self.get_next_node_ids(game_id, 'out')
        full_plan_ids = [nid for nid in ordered_plan_ids if nid in r_out_ids]
        for nid in r_out_ids:
            if nid not in full_plan_ids and self.nodes.get(nid, {}).get('type_') == 'macro.nodes.PlanNode':
                full_plan_ids.append(nid)
        return full_plan_ids

    def _find_parent_game_id(self, node_id):
        """Plan/Rule/Guard から上流へ辿り GameNode を探す"""
        visited = set()
        cur = node_id
        while cur and cur not in visited:
            visited.add(cur)
            nd = self.nodes.get(cur)
            if not nd:
                return None
            if nd.get('type_') == 'macro.nodes.GameNode':
                return cur
            prevs = self.get_prev_node_ids(cur, 'in')
            cur = prevs[0] if prevs else None
        return None

    def _find_parent_plan_id(self, node_id):
        """Rule から上流へ辿り PlanNode を探す"""
        visited = set()
        cur = node_id
        while cur and cur not in visited:
            visited.add(cur)
            nd = self.nodes.get(cur)
            if not nd:
                return None
            if nd.get('type_') == 'macro.nodes.PlanNode':
                return cur
            prevs = self.get_prev_node_ids(cur, 'in')
            cur = prevs[0] if prevs else None
        return None

    def get_next_node_ids(self, node_id, port='out'):
        """현재 노드의 출력 핀에 연결된 모든 다음 노드 ID 리스트를 리턴 (우선순위 순으로 정렬)."""
        result = []
        for conn in self.connections:
            out_side = conn.get('out', [])
            if out_side and out_side[0] == node_id and out_side[1] == port:
                in_side = conn.get('in', [])
                if in_side:
                    result.append(in_side[0])
                    
        # 우선순위 부여 로직
        node_data = self.nodes.get(node_id, {})
        custom = node_data.get('custom', {})
        order_json = custom.get('out_nodes_order', '[]')
        ordered_ids = self._load_json_prop(order_json)
        
        if ordered_ids:
            # 보존된 순서대로 추출
            sorted_result = []
            for oid in ordered_ids:
                if oid in result:
                    sorted_result.append(oid)
                    result.remove(oid)
            # 순서 배열에 없던(새로 연결된) 노드는 뒤에 이어붙임
            sorted_result.extend(result)
            return sorted_result
            
        return result

    def get_prev_node_ids(self, node_id, port='in'):
        """현재 노드의 입력 핀에 연결된 모든 이전 노드 ID 리스트를 리턴."""
        result = []
        for conn in self.connections:
            in_side = conn.get('in', [])
            if in_side and in_side[0] == node_id and in_side[1] == port:
                out_side = conn.get('out', [])
                if out_side:
                    result.append(out_side[0])
        return result

    def _load_json_prop(self, val):
        try:
            return json.loads(val) if val else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _resolve_guard_ids_for_parent(self, parent_node_id):
        """Game または Plan の guard_nodes_order と out 接続から有効な Guard ID リストを構築する"""
        r_node = self.nodes.get(parent_node_id)
        if not r_node:
            return []
        guard_order_json = r_node.get('custom', {}).get('guard_nodes_order', '[]')
        ordered_guard_ids = self._load_json_prop(guard_order_json)
        r_out_ids = self.get_next_node_ids(parent_node_id, 'out')
        valid_guard_ids = [nid for nid in ordered_guard_ids if nid in r_out_ids]
        for nid in r_out_ids:
            if nid not in valid_guard_ids and self.nodes.get(nid, {}).get('type_') == 'macro.nodes.GuardNode':
                valid_guard_ids.append(nid)
        return valid_guard_ids

    def _normalize_after_guard_mode(self, gprops):
        """Guardノードのafter_guard_completeを検証し、goto_plan時は_full_plan_idsでターゲット確認"""
        mode = gprops.get('after_guard_complete', 'resume')
        if mode not in ('resume', 'restart_from_start', 'goto_plan'):
            mode = 'resume'
        if mode == 'goto_plan':
            tid = str(gprops.get('after_guard_target_plan_id') or '').strip()
            if not tid or tid not in self._full_plan_ids:
                mode = 'resume'
            else:
                self._goto_plan_target_id = tid
        return mode

    def _check_guards_stabilized(self, game_guard_ids, plan_guard_ids):
        """Game 単位ガードを順に検査し、次に Plan ガードを検査する"""
        while self.is_running:
            triggered, mode = self._check_guard_sequence(game_guard_ids)
            if triggered:
                if mode == 'restart_from_start':
                    self._request_full_restart = True
                    return
                if mode == 'goto_plan':
                    self._request_goto_plan = True
                    return
                self._sleep_interruptible(0.5)
                continue
            triggered, mode = self._check_guard_sequence(plan_guard_ids)
            if triggered:
                if mode == 'restart_from_start':
                    self._request_full_restart = True
                    return
                if mode == 'goto_plan':
                    self._request_goto_plan = True
                    return
                self._sleep_interruptible(0.5)
                continue
            break







    # ──────────────────────────────────────────
    # Guard 노드 수집
    # ──────────────────────────────────────────
    def _collect_guard_ids(self):
        """그래프 내 모든 GuardNode의 ID 리스트를 반환."""
        guard_ids = []
        for nid, nd in self.nodes.items():
            if nd.get('type_') == 'macro.nodes.GuardNode':
                guard_ids.append(nid)
        return guard_ids

    def _check_guard_rules(self, guard_ids):
        """Guard에 연결된 RuleNode들을 검사. 매칭된 RuleNode가 있으면 (node_id, found_pos) 반환."""
        for gid in guard_ids:
            guard_name = self.nodes[gid].get('custom', {}).get('label', self.nodes[gid].get('name', 'Guard'))
            rule_ids = self.get_next_node_ids(gid, 'out')
            for rid in rule_ids:
                nd = self.nodes.get(rid)
                if not nd or nd.get('type_') != 'macro.nodes.RuleNode':
                    continue
                props = nd.get('custom', {})
                label = nd.get('name', '?')
                conditions = self._load_json_prop(props.get('conditions', '[]'))
                capture_image = props.get('capture_image', '')
                if not conditions:
                    continue  # 조건 없는 Guard 연결 Rule은 건너뜀
                matched, found_pos = self.condition_evaluator.check_conditions(conditions, capture_image)
                if matched:
                    print(f"[🛡⚠] Guard '{guard_name}' → '{label}' 매칭!")
                    return rid, found_pos
        return None, None

    # ──────────────────────────────────────────
    # 메인 실행 루프
    # ──────────────────────────────────────────
    def run(self, run_from_node_id=None):
        self.load_graph()
        self.active_game_id = None
        entry_start_id = self.get_entry_start_node_id()
        if not entry_start_id:
            print("오류: Start 노드를 찾을 수 없습니다.")
            return

        full_game_ids = self._resolve_full_game_ids(entry_start_id)
        if not full_game_ids:
            print("오류: Start에 연결된 Game 노드가 없습니다.")
            return

        run_from = run_from_node_id
        game_idx = 0
        valid_plan_ids = []
        starting_rule_id = None
        is_first_segment = True

        if not run_from or run_from == entry_start_id:
            game_idx = 0
            gid = full_game_ids[0]
            valid_plan_ids = list(self._resolve_full_plan_ids(gid))
            self._plan_slice_start = 0
            self.variable_manager.initialize_variables(config_node_id=gid)
            if self.progress_callback:
                self.progress_callback(entry_start_id)
        else:
            rf_node = self.nodes.get(run_from)
            ntype = rf_node.get('type_') if rf_node else None
            if ntype == 'macro.nodes.GameNode':
                if run_from not in full_game_ids:
                    print("오류: 해당 Game이 Start의 game 순서에 없습니다.")
                    return
                game_idx = full_game_ids.index(run_from)
                gid = run_from
                valid_plan_ids = list(self._resolve_full_plan_ids(gid))
                self._plan_slice_start = 0
                self.variable_manager.initialize_variables(config_node_id=gid)
                if self.progress_callback:
                    self.progress_callback(run_from)
            elif ntype == 'macro.nodes.PlanNode':
                parent_game = self._find_parent_game_id(run_from)
                if not parent_game or parent_game not in full_game_ids:
                    print("오류: Plan의 상위 Game 노드를 찾을 수 없습니다.")
                    return
                game_idx = full_game_ids.index(parent_game)
                gid = parent_game
                fp = self._resolve_full_plan_ids(gid)
                if run_from in fp:
                    self._plan_slice_start = fp.index(run_from)
                    valid_plan_ids = fp
                else:
                    self._plan_slice_start = 0
                    valid_plan_ids = [run_from]
                    self._pending_plan_ids_override = [run_from]
                self.variable_manager.initialize_variables(config_node_id=gid)
                if self.progress_callback:
                    self.progress_callback(run_from)
            elif ntype == 'macro.nodes.RuleNode':
                parent_plan = self._find_parent_plan_id(run_from)
                if not parent_plan:
                    print("오류: Rule의 부모 Plan 노드를 찾을 수 없습니다.")
                    return
                parent_game = self._find_parent_game_id(parent_plan)
                if not parent_game or parent_game not in full_game_ids:
                    print("오류: Rule의 상위 Game 노드를 찾을 수 없습니다.")
                    return
                game_idx = full_game_ids.index(parent_game)
                gid = parent_game
                fp = self._resolve_full_plan_ids(gid)
                if parent_plan in fp:
                    self._plan_slice_start = fp.index(parent_plan)
                    valid_plan_ids = fp
                else:
                    self._plan_slice_start = 0
                    valid_plan_ids = [parent_plan]
                    self._pending_plan_ids_override = [parent_plan]
                starting_rule_id = run_from
                self.variable_manager.initialize_variables(config_node_id=gid)
                if self.progress_callback:
                    self.progress_callback(run_from)
                print(f"👉 Rule '{rf_node.get('name')}'에서 시작합니다. (Plan: {self.nodes[parent_plan].get('name')})")
            else:
                print(f"⚠ 경고: 지원하지 않는 노드 타입('{ntype}')에서 시작을 시도했습니다.")
                return

        if not valid_plan_ids:
            print("오류: 실행할 Plan 노드가 없습니다.")
            return

        self.is_running = True

        while self.is_running:
            game_id = full_game_ids[game_idx]
            self.active_game_id = game_id
            full_plan_ids_cur = self._resolve_full_plan_ids(game_id)
            game_guard_ids = self._resolve_guard_ids_for_parent(game_id)

            if is_first_segment:
                current_rule = starting_rule_id
            else:
                current_rule = None

            if self._pending_plan_ids_override is not None:
                self._full_plan_ids = list(self._pending_plan_ids_override)
                self._pending_plan_ids_override = None
            else:
                self._full_plan_ids = list(full_plan_ids_cur)
            gname = self.nodes.get(game_id, {}).get('name', game_id)
            slice_note = (
                f", Plan 구간 {self._plan_slice_start}번째〜"
                if self._plan_slice_start
                else ""
            )
            print(
                f"═══ 매크로 — Game '{gname}' (상위 가드 {len(game_guard_ids)}개, "
                f"플랜 {len(full_plan_ids_cur)}개{slice_note}) ═══"
            )

            self._launch_game_package_if_set(game_id)
            self._run_plan_sequence(game_guard_ids, starting_rule_id=current_rule)

            if self._request_full_restart:
                self._request_full_restart = False
                game_idx = 0
                gid0 = full_game_ids[0]
                valid_plan_ids = list(self._resolve_full_plan_ids(gid0))
                self._plan_slice_start = 0
                starting_rule_id = None
                is_first_segment = True
                self.active_game_id = gid0
                continue

            if self._pending_jump_to_plan_id:
                jp = self._pending_jump_to_plan_id
                self._pending_jump_to_plan_id = None
                if jp in self._full_plan_ids:
                    idx = self._full_plan_ids.index(jp)
                    self._plan_slice_start = idx
                    is_first_segment = True
                    starting_rule_id = None
                continue

            game_idx += 1
            is_first_segment = False
            valid_plan_ids = []
            starting_rule_id = None
            self._plan_slice_start = 0

            if game_idx >= len(full_game_ids):
                print("=== 모든 Game의 Plan 시퀀스를 완료했습니다. 첫 Game부터 다시 반복합니다. ===")
                game_idx = 0
                self._plan_slice_start = 0
                self._sleep_interruptible(1.0)

        self.is_running = False

    def _check_guard_sequence(self, valid_guard_ids):
        """
        모든 Guard 시퀀스를 검사합니다.
        조건이 맞는 Guard가 있으면, 해당 Guard 하위의 Rule들을 수행하고 (True, after_mode)를 반환합니다.
        """
        for gid in valid_guard_ids:
            if not self.is_running:
                return False, None
            
            g_node = self.nodes.get(gid)
            if not g_node:
                continue
            g_name = g_node.get('name', 'Guard')
            
            gprops = g_node.get('custom', {})
            
            # 루프 횟수 변수 제거됨
            
            # 파일 누적 기반 차단 로직 제거됨
            
            g_rule_ids = self.get_next_node_ids(gid, 'out')
            if not g_rule_ids: continue
            
            guard_triggered = False
            matched_rule_id = None
            matched_fpos = None
            matched_img = None
            matched_node = None
            
            for rid in g_rule_ids:
                if self.progress_callback:
                    self.progress_callback(rid)
                
                rnd = self.nodes.get(rid)
                rprops = rnd.get('custom', {})
                conds = self._load_json_prop(rprops.get('conditions', '[]'))
                cap_img = rprops.get('capture_image', '')
                
                if conds:
                    matched, fpos = self.condition_evaluator.check_conditions(
                        conds,
                        cap_img,
                        scope_log_prefix=f"Guard - {g_name}",
                        rule_label=rprops.get('name', rnd.get('name', '?'))
                    )
                    if matched:
                        guard_triggered = True
                        matched_rule_id = rid
                        matched_fpos = fpos
                        matched_img = cap_img
                        matched_node = rnd
                        break
                        
            if guard_triggered:
                if self.progress_callback: self.progress_callback(matched_rule_id)
                
                rname = matched_node.get('name', '?')
                print(f"[🛡⚠] 돌발 상황 감지! Guard '{g_name}' 발동 -> '{rname}'")
                self._record_guard_trigger(gid)
                
                actions = self._load_json_prop(matched_node.get('custom', {}).get('actions', '[]'))
                if actions:
                    self.action_executor.execute_actions(actions, matched_fpos, matched_img)
                    self.variable_manager.sync_to_file()  # 액션 실행 후 동기화
                
                variable_ops = self._load_json_prop(matched_node.get('custom', {}).get('variable_ops', '[]'))
                if variable_ops:
                    self.action_executor.execute_variable_ops(json.dumps(variable_ops))
                    self.variable_manager.sync_to_file()  # 변수 연산 후 동기화
                
                current_g_loop = 0
                next_g_ids = self.get_next_node_ids(matched_rule_id, 'out')
                first_guard_run = True
                guard_root_rule_id = matched_rule_id
                previous_guard_rule_id = matched_rule_id
                guard_next_search_started_at = time.monotonic()
                
                # 루프 제거: 1회만 실행
                current_g_loop_run = True
                while current_g_loop_run and self.is_running:
                    current_g_loop_run = False
                        
                    g_candidates = list(next_g_ids) if first_guard_run else list(g_rule_ids)
                    first_guard_run = False
                    g_chain_running = bool(g_candidates)
                    
                    while g_chain_running and self.is_running:
                        g_any_matched = False
                        for grid in g_candidates:
                            grnd = self.nodes.get(grid)
                            if not grnd: continue
                            
                            grprops = grnd.get('custom', {})
                            grname = grnd.get('name', '?')
                            gconds = self._load_json_prop(grprops.get('conditions', '[]'))
                            gimg = grprops.get('capture_image', '')
                            
                            if self.progress_callback: self.progress_callback(grid)
                            
                            gmatched, gfpos = self.condition_evaluator.check_conditions(
                                gconds,
                                gimg,
                                scope_log_prefix=f"Guard - {g_name}",
                                rule_label=grname
                            ) if gconds else (True, None)
                            
                            if gmatched:
                                gactions = self._load_json_prop(grprops.get('actions', '[]'))
                                if gactions: 
                                    self.action_executor.execute_actions(gactions, gfpos, gimg)
                                    self.variable_manager.sync_to_file()
                                
                                g_variable_ops = self._load_json_prop(grprops.get('variable_ops', '[]'))
                                if g_variable_ops:
                                    self.action_executor.execute_variable_ops(json.dumps(g_variable_ops))
                                    self.variable_manager.sync_to_file()
                                
                                g_candidates = self.get_next_node_ids(grid, 'out')
                                previous_guard_rule_id = grid
                                if not g_candidates: g_chain_running = False
                                else:
                                    guard_next_search_started_at = time.monotonic()
                                g_any_matched = True
                                break
                                
                        if not g_any_matched and g_chain_running:
                            timeout_sec = self._get_next_rule_search_timeout_seconds(previous_guard_rule_id)
                            elapsed = time.monotonic() - guard_next_search_started_at
                            if elapsed >= timeout_sec:
                                if previous_guard_rule_id == guard_root_rule_id:
                                    print(f"    [↩] Guard 다음 Rule 탐색 {timeout_sec:.1f}초 초과(첫 Rule) -> Guard 루프 종료 후 전체 재스캔")
                                    return False, None
                                prev_name = self.nodes.get(previous_guard_rule_id, {}).get('name', '?')
                                print(f"    [↩] Guard 다음 Rule 탐색 {timeout_sec:.1f}초 초과 -> 이전 Rule '{prev_name}'로 복귀")
                                g_candidates = [previous_guard_rule_id]
                                guard_next_search_started_at = time.monotonic()
                                continue
                            self._sleep_interruptible(0.5)
                        else:
                            self._sleep_interruptible(0.1)
                            
                    if self.is_running and not g_chain_running:
                        pass
                            
                print(f"[🛡 완료] Guard '{g_name}' 처리를 마치고 원래 Plan으로 복귀합니다.")
                mode = self._normalize_after_guard_mode(gprops)
                return True, mode
                
        return False, None

    def _launch_game_package_if_set(self, game_id):
        """Game の launch_package があれば ADB で起動し、post_launch_wait_seconds だけ待つ。"""
        node = self.nodes.get(game_id) or {}
        custom = node.get('custom') or {}
        raw = (custom.get('launch_package') or '').strip()
        pkg = adb_manager.safe_package_token(raw)
        if not pkg:
            return
        dev = adb_manager.adbdevice
        if dev is None:
            print("[Game] ADB 미연결 — 패키지 실행 생략")
            return
        try:
            dev.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
            print(f"[Game] 앱 실행: {pkg}")
        except Exception as e:
            print(f"[Game] 앱 실행 실패 ({pkg}): {e}")
        try:
            w = float(custom.get('post_launch_wait_seconds') or 0)
        except (TypeError, ValueError):
            w = 0.0
        if w > 0:
            self._sleep_interruptible(w)

    def _record_plan_completion(self, plan_id):
        plan_node = self.nodes.get(plan_id) or {}
        game_node = self.nodes.get(self.active_game_id) or {}
        game_name = str(game_node.get('name') or 'Game').strip() or 'Game'
        plan_name = str(plan_node.get('name') or 'Plan').strip() or 'Plan'
        counter_var = f"__plan_done__{plan_id}"
        self.variable_manager.update_variable(counter_var, '+', 1)
        self.variable_manager.sync_to_file()
        print(f"[Plan 완료] {game_name} / {plan_name} +1")

    def _record_guard_trigger(self, guard_id):
        guard_node = self.nodes.get(guard_id) or {}
        game_id = self._find_parent_game_id(guard_id)
        game_node = self.nodes.get(game_id) if game_id else {}
        game_name = str((game_node or {}).get('name') or 'Game').strip() or 'Game'
        guard_name = str(guard_node.get('name') or 'Guard').strip() or 'Guard'
        counter_var = f"__guard_done__{guard_id}"
        self.variable_manager.update_variable(counter_var, '+', 1)
        self.variable_manager.sync_to_file()
        print(f"[Guard 완료] {game_name} / {guard_name} +1")

    def _recheck_guards_after_plan_completion(self, game_guard_ids, plan_guard_ids):
        """Plan 마지막 Rule 완료 직후 Guard를 반드시 재검사한다."""
        triggered, mode = self._check_guard_sequence(game_guard_ids)
        if not triggered:
            triggered, mode = self._check_guard_sequence(plan_guard_ids)
        if not triggered:
            return False
        if mode == 'restart_from_start':
            self._request_full_restart = True
            return True
        if mode == 'goto_plan':
            tid = self._goto_plan_target_id
            self._goto_plan_target_id = None
            if tid:
                self._pending_jump_to_plan_id = tid
            return True
        return True

    def _run_plan_sequence(self, game_guard_ids, starting_rule_id=None):
        """
        Game 単位: 各サイクルで Game Guard → 各 Plan の Plan Guard → 各 Plan のルート Rule(条件ありのみ)を順にスキャン。
        1 サイクル全体で一度もマッチしなければ次の Game へ。マッチしたら従来の Rule チェーンへ。
        """
        while self.is_running:
            self.variable_manager.initialize_variables(config_node_id=self.active_game_id)
            rescan_current_game = False
            full_plan_ids = self._full_plan_ids

            triggered, mode = self._check_guard_sequence(game_guard_ids)
            if triggered:
                if mode == 'restart_from_start':
                    self._request_full_restart = True
                    return
                if mode == 'goto_plan':
                    tid = self._goto_plan_target_id
                    self._goto_plan_target_id = None
                    if tid:
                        self._pending_jump_to_plan_id = tid
                    return
                # 日本語: Guard 処理が走ったサイクルは「ヒットあり」として Game を維持
                self._sleep_interruptible(0.5)
                continue

            matched_cycle = False

            for plan_id in full_plan_ids[self._plan_slice_start:]:
                if not self.is_running:
                    return
                self.active_plan_id = plan_id
                nd = self.nodes.get(plan_id)
                if not nd or nd.get('type_') != 'macro.nodes.PlanNode':
                    continue
                props = nd.get('custom', {})
                plan_name = nd.get('name', 'Plan')
                plan_guard_ids = self._resolve_guard_ids_for_parent(plan_id)

                triggered, mode = self._check_guard_sequence(plan_guard_ids)
                if triggered:
                    if mode == 'restart_from_start':
                        self._request_full_restart = True
                        return
                    if mode == 'goto_plan':
                        tid = self._goto_plan_target_id
                        self._goto_plan_target_id = None
                        if tid:
                            self._pending_jump_to_plan_id = tid
                        return
                    matched_cycle = True
                    break

                all_out = self.get_next_node_ids(plan_id, 'out')
                root_rule_ids = [
                    nid for nid in all_out
                    if self.nodes.get(nid, {}).get('type_') == 'macro.nodes.RuleNode'
                ]
                if not root_rule_ids:
                    continue

                # 日本語: run_from で指定されたルート Rule は条件が空でもスイープで採用する
                debug_start_rid = None
                if starting_rule_id and starting_rule_id in root_rule_ids:
                    debug_start_rid = starting_rule_id
                    cand_list = [starting_rule_id]
                    starting_rule_id = None
                else:
                    cand_list = list(root_rule_ids)
                    starting_rule_id = None

                for rid in cand_list:
                    if not self.is_running:
                        return
                    rnd = self.nodes.get(rid)
                    if not rnd or rnd.get('type_') != 'macro.nodes.RuleNode':
                        continue
                    rprops = rnd.get('custom', {})
                    conds = self._load_json_prop(rprops.get('conditions', '[]'))
                    cap_img = rprops.get('capture_image', '')
                    if self.progress_callback:
                        self.progress_callback(rid)
                    if not conds:
                        if rid != debug_start_rid:
                            continue
                        matched, fpos = True, None
                    else:
                        matched, fpos = self.condition_evaluator.check_conditions(
                            conds,
                            cap_img,
                            scope_log_prefix=f"Plan - {plan_name}",
                            rule_label=rnd.get('name', '?')
                        )
                    if not matched:
                        continue

                    rname = rnd.get('name', '?')
                    actions = self._load_json_prop(rprops.get('actions', '[]'))
                    if actions:
                        self.action_executor.execute_actions(actions, fpos, cap_img)
                        self.variable_manager.sync_to_file()
                    variable_ops = self._load_json_prop(rprops.get('variable_ops', '[]'))
                    if variable_ops:
                        self.action_executor.execute_variable_ops(json.dumps(variable_ops))
                        self.variable_manager.sync_to_file()
                    next_ids = self.get_next_node_ids(rid, 'out')
                    current_rule_candidates = list(next_ids) if next_ids else []
                    chain_running = bool(next_ids)
                    plan_completed_naturally = not chain_running
                    previous_rule_id = rid
                    root_rule_id = rid
                    next_search_started_at = time.monotonic()
                    request_full_rescan_after_timeout = False

                    while chain_running and self.is_running:
                        self._check_guards_stabilized(game_guard_ids, plan_guard_ids)
                        if self._request_full_restart:
                            return
                        if self._request_goto_plan:
                            self._request_goto_plan = False
                            tid = self._goto_plan_target_id
                            self._goto_plan_target_id = None
                            if tid:
                                self._pending_jump_to_plan_id = tid
                            return
                        if self._request_restart_plan:
                            self._request_restart_plan = False
                            current_rule_candidates = list(root_rule_ids)
                            continue

                        matched_any = False
                        for crid in current_rule_candidates:
                            if not self.is_running:
                                break
                            crnd = self.nodes.get(crid)
                            if not crnd or crnd.get('type_') != 'macro.nodes.RuleNode':
                                continue
                            if self.progress_callback:
                                self.progress_callback(crid)
                            crprops = crnd.get('custom', {})
                            crname = crnd.get('name', '?')
                            c_conds = self._load_json_prop(crprops.get('conditions', '[]'))
                            c_img = crprops.get('capture_image', '')
                            c_matched = True
                            c_fpos = None
                            if c_conds:
                                c_matched, c_fpos = self.condition_evaluator.check_conditions(
                                    c_conds,
                                    c_img,
                                    scope_log_prefix=f"Plan - {plan_name}",
                                    rule_label=crname
                                )
                            if c_matched:
                                c_actions = self._load_json_prop(crprops.get('actions', '[]'))
                                if c_actions:
                                    self.action_executor.execute_actions(c_actions, c_fpos, c_img)
                                    self.variable_manager.sync_to_file()
                                c_vops = self._load_json_prop(crprops.get('variable_ops', '[]'))
                                if c_vops:
                                    self.action_executor.execute_variable_ops(json.dumps(c_vops))
                                    self.variable_manager.sync_to_file()
                                nxt = self.get_next_node_ids(crid, 'out')
                                previous_rule_id = crid
                                if nxt:
                                    current_rule_candidates = nxt
                                    next_search_started_at = time.monotonic()
                                else:
                                    chain_running = False
                                    plan_completed_naturally = True
                                matched_any = True
                                break

                        if not matched_any and chain_running:
                            timeout_sec = self._get_next_rule_search_timeout_seconds(previous_rule_id)
                            elapsed = time.monotonic() - next_search_started_at
                            if elapsed >= timeout_sec and previous_rule_id:
                                if previous_rule_id == root_rule_id:
                                    print(f"    [↩] 다음 Rule 탐색 {timeout_sec:.1f}초 초과(첫 Rule) -> Plan 루프 종료 후 Guard부터 재스캔")
                                    request_full_rescan_after_timeout = True
                                    chain_running = False
                                    break
                                prev_name = self.nodes.get(previous_rule_id, {}).get('name', '?')
                                print(f"    [↩] 다음 Rule 탐색 {timeout_sec:.1f}초 초과 -> 이전 Rule '{prev_name}'로 복귀")
                                current_rule_candidates = [previous_rule_id]
                                next_search_started_at = time.monotonic()
                                continue
                            self._sleep_interruptible(0.5)
                        else:
                            self._sleep_interruptible(0.1)

                    if request_full_rescan_after_timeout:
                        rescan_current_game = True
                        break

                    if (
                        plan_completed_naturally and
                        not self._request_full_restart and
                        not self._request_goto_plan and
                        not self._request_restart_plan and
                        self.is_running
                    ):
                        self._record_plan_completion(plan_id)
                        # 日本語: Game 末尾 Plan まで自然完了したら、次サイクルは先頭 Plan から Guard〜順に戻す
                        if plan_id == full_plan_ids[-1]:
                            self._plan_slice_start = 0
                        guard_triggered_after_completion = self._recheck_guards_after_plan_completion(
                            game_guard_ids, plan_guard_ids
                        )
                        if guard_triggered_after_completion:
                            if self._request_full_restart:
                                return
                            if self._pending_jump_to_plan_id:
                                return
                            if self._request_restart_plan:
                                self._request_restart_plan = False
                                continue

                    matched_cycle = True
                    break

                if rescan_current_game:
                    break

                if matched_cycle:
                    break

            if rescan_current_game:
                print("🔁 [Game] 첫 Rule 타임아웃으로 Guard부터 다시 전체 스캔합니다.")
                self._sleep_interruptible(0.1)
                continue

            if not matched_cycle:
                if self._plan_slice_start > 0:
                    print(
                        "📭 [Game] goto/run_from 구간만 스캔하여 매칭 없음 — "
                        "전체 Plan 순서로 한 번 더 시도합니다."
                    )
                    self._plan_slice_start = 0
                    self._sleep_interruptible(0.1)
                    continue
                print("📭 [Game] 한 사이클 전체에서 매칭 없음 — 다음 Game으로")
                return

            self._sleep_interruptible(0.1)

    def stop(self):
        self.is_running = False

