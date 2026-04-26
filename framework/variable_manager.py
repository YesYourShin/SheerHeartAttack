import os
import json
import datetime

class VariableManager:
    """
    일일 기록 변수의 로드, 적재, 캐싱 및 디스크 동기화를 전담하는 클래스입니다.
    """
    def __init__(self, runner):
        self.runner = runner
        self.variables = {}  # 인메모리 캐시
        self.variable_scopes = {}  # var_name -> game_id

    def _plan_counter_key(self, plan_id):
        return f"__plan_done__{plan_id}"

    def _is_plan_counter_key(self, key):
        return isinstance(key, str) and key.startswith("__plan_done__")

    def _extract_plan_id_from_counter_key(self, key):
        if not self._is_plan_counter_key(key):
            return None
        return key[len("__plan_done__"):].strip()

    def _guard_counter_key(self, guard_id):
        return f"__guard_done__{guard_id}"

    def _is_guard_counter_key(self, key):
        return isinstance(key, str) and key.startswith("__guard_done__")

    def _extract_guard_id_from_counter_key(self, key):
        if not self._is_guard_counter_key(key):
            return None
        return key[len("__guard_done__"):].strip()

    def _find_game_id_by_name(self, game_name):
        target = str(game_name or '').strip()
        if not target:
            return None
        for nid, nd in self.runner.nodes.items():
            if nd.get('type_') != 'macro.nodes.GameNode':
                continue
            if str(nd.get('name') or '').strip() == target:
                return nid
        return None

    def _find_plan_id_by_labels(self, game_name, plan_name):
        game_id = self._find_game_id_by_name(game_name)
        if not game_id:
            return None
        target_plan = str(plan_name or '').strip()
        if not target_plan:
            return None
        for pid in self.runner.get_next_node_ids(game_id, 'out'):
            nd = self.runner.nodes.get(pid) or {}
            if nd.get('type_') != 'macro.nodes.PlanNode':
                continue
            if str(nd.get('name') or '').strip() == target_plan:
                return pid
        return None

    def _find_guard_id_by_labels(self, game_name, guard_name):
        game_id = self._find_game_id_by_name(game_name)
        if not game_id:
            return None
        target_guard = str(guard_name or '').strip()
        if not target_guard:
            return None
        for gid, nd in self.runner.nodes.items():
            if nd.get('type_') != 'macro.nodes.GuardNode':
                continue
            parent_game = self.runner._find_parent_game_id(gid)
            if parent_game != game_id:
                continue
            if str(nd.get('name') or '').strip() == target_guard:
                return gid
        return None

    def _parse_record_content(self, content):
        parsed_values = {}
        parsed_scopes = {}
        lines = content.splitlines()
        current_section = None
        current_subsection = None

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith('{'):
                try:
                    data = json.loads(content)
                    for k, v in data.items():
                        parsed_values[k] = int(v)
                    return parsed_values, parsed_scopes
                except Exception:
                    pass

            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1].strip()
                current_subsection = None
                continue

            if line.startswith('- [') and line.endswith(']') and current_section:
                current_subsection = line[3:-1].strip()
                continue

            if line.startswith('- ') and ':' in line and current_section and current_subsection == '플랜':
                plan_label, value_text = line[2:].split(':', 1)
                try:
                    value = int(value_text.strip())
                except Exception:
                    continue
                plan_id = self._find_plan_id_by_labels(current_section, plan_label.strip())
                if plan_id:
                    parsed_values[self._plan_counter_key(plan_id)] = value
                continue

            if line.startswith('- ') and ':' in line and current_section and current_subsection == '가드':
                guard_label, value_text = line[2:].split(':', 1)
                try:
                    value = int(value_text.strip())
                except Exception:
                    continue
                guard_id = self._find_guard_id_by_labels(current_section, guard_label.strip())
                if guard_id:
                    parsed_values[self._guard_counter_key(guard_id)] = value
                continue

            if line.startswith('- ') and ':' in line and current_section and current_subsection == '변수':
                var_name, value_text = line[2:].split(':', 1)
                var_name = var_name.strip()
                try:
                    value = int(value_text.strip())
                except Exception:
                    continue
                if not var_name:
                    continue
                parsed_values[var_name] = value
                gid = self._find_game_id_by_name(current_section)
                if gid:
                    parsed_scopes[var_name] = gid
                continue

            # 하위 호환: 기존 포맷([게임] 아래 바로 " - 플랜: N", " * 변수: M")도 읽는다.
            if line.startswith('- ') and ':' in line and current_section and current_subsection is None:
                label, value_text = line[2:].split(':', 1)
                try:
                    value = int(value_text.strip())
                except Exception:
                    continue
                plan_id = self._find_plan_id_by_labels(current_section, label.strip())
                if plan_id:
                    parsed_values[self._plan_counter_key(plan_id)] = value
                else:
                    parsed_values[label.strip()] = value
                    gid = self._find_game_id_by_name(current_section)
                    if gid:
                        parsed_scopes[label.strip()] = gid
                continue

            if line.startswith('* ') and ':' in line:
                var_name, value_text = line[2:].split(':', 1)
                var_name = var_name.strip()
                try:
                    value = int(value_text.strip())
                except Exception:
                    continue
                if not var_name:
                    continue
                parsed_values[var_name] = value
                if current_section:
                    gid = self._find_game_id_by_name(current_section)
                    if gid:
                        parsed_scopes[var_name] = gid
                continue

            if ':' in line:
                k, v = line.split(':', 1)
                key = k.strip()
                if not key:
                    continue
                try:
                    parsed_values[key] = int(v.strip())
                except Exception:
                    continue

        return parsed_values, parsed_scopes

    def _get_daily_record_file(self):
        # 現在の Game ノードから初期化時間（無ければデフォルト）
        reset_time_str = "05:00:00"
        config_id = getattr(self.runner, 'active_game_id', None)
        if config_id:
            cfg = self.runner.nodes.get(config_id, {})
            if cfg.get('type_') == 'macro.nodes.GameNode':
                reset_time_str = cfg.get('custom', {}).get('reset_time', '05:00:00')
            
        # Plan 고유 설정 덮어쓰기
        if getattr(self.runner, 'active_plan_id', None):
            plan_node = self.runner.nodes.get(self.runner.active_plan_id, {})
            custom = plan_node.get('custom', {})
            if custom.get('use_custom_reset_time') == 'True':
                reset_time_str = custom.get('reset_time', '05:00:00')
            
        # 초기화 시간 파싱
        try:
            r_hour, r_min, r_sec = map(int, reset_time_str.split(':'))
        except Exception:
            r_hour, r_min, r_sec = 5, 0, 0
            
        now = datetime.datetime.now()
        # 현재 시간에서 초기화 시각 분량만큼 뺀 시간을 구하여 해당 시점을 기준으로 일자 명명
        reset_delta = datetime.timedelta(hours=r_hour, minutes=r_min, seconds=r_sec)
        adjusted_time = now - reset_delta
        
        today_str = adjusted_time.strftime("%Y%m%d")
        record_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'daily_records')
        if not os.path.exists(record_dir):
            os.makedirs(record_dir)
        return os.path.join(record_dir, f"output_{today_str}.txt")

    def get_variable(self, var_name):
        """_get_daily_record의 외부 공개 버전"""
        # 1. 캐시 메모리에 있으면 즉시 반환
        if var_name in self.variables:
            return self.variables[var_name]
            
        # 2. 캐시에 없으면 로드 시도
        record_file = self._get_daily_record_file()
        if not os.path.exists(record_file):
            return 0
        try:
            with open(record_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                data, scopes = self._parse_record_content(content)
                for sk, sv in scopes.items():
                    if sk not in self.variable_scopes:
                        self.variable_scopes[sk] = sv
            # 메모리 캐시 동기화
            for k, v in data.items():
                if k not in self.variables:
                    self.variables[k] = v
            return self.variables.get(var_name, 0)
        except Exception:
            return 0

    def update_variable(self, var_name, operation, value):
        """_update_daily_variable의 외부 공개 버전"""
        if not var_name: return
        
        current = self.get_variable(var_name)
        
        if operation == '+':
            self.variables[var_name] = current + value
        elif operation == '-':
            self.variables[var_name] = current - value
        elif operation == '=':
            self.variables[var_name] = value

        if not self._is_plan_counter_key(var_name):
            gid = getattr(self.runner, 'active_game_id', None)
            if gid:
                self.variable_scopes[var_name] = gid
            
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}]  [🧮 캐시] {var_name} {operation} {value} -> 현재값: {self.variables[var_name]}")

    def sync_to_file(self):
        """_sync_variables_to_file의 외부 공개 버전"""
        if not self.variables: return
        record_file = self._get_daily_record_file()
        try:
            plan_counts_by_game = {}
            guard_counts_by_game = {}
            vars_by_game = {}
            common_vars = {}

            for key, value in self.variables.items():
                if self._is_plan_counter_key(key):
                    plan_id = self._extract_plan_id_from_counter_key(key)
                    plan_node = self.runner.nodes.get(plan_id) if plan_id else None
                    if not plan_node:
                        continue
                    plan_name = str(plan_node.get('name') or 'Plan').strip() or 'Plan'
                    game_id = self.runner._find_parent_game_id(plan_id)
                    game_node = self.runner.nodes.get(game_id) if game_id else None
                    game_name = str((game_node or {}).get('name') or 'Game').strip() or 'Game'
                    plan_counts_by_game.setdefault(game_name, {})[plan_name] = int(value)
                    continue

                if self._is_guard_counter_key(key):
                    guard_id = self._extract_guard_id_from_counter_key(key)
                    guard_node = self.runner.nodes.get(guard_id) if guard_id else None
                    if not guard_node:
                        continue
                    guard_name = str(guard_node.get('name') or 'Guard').strip() or 'Guard'
                    game_id = self.runner._find_parent_game_id(guard_id)
                    game_node = self.runner.nodes.get(game_id) if game_id else None
                    game_name = str((game_node or {}).get('name') or 'Game').strip() or 'Game'
                    guard_counts_by_game.setdefault(game_name, {})[guard_name] = int(value)
                    continue

                gid = self.variable_scopes.get(key)
                if gid:
                    gnode = self.runner.nodes.get(gid) or {}
                    gname = str(gnode.get('name') or 'Game').strip() or 'Game'
                    vars_by_game.setdefault(gname, {})[key] = int(value)
                else:
                    common_vars[key] = int(value)

            with open(record_file, 'w', encoding='utf-8') as f:
                unassigned_vars = {}
                for var_name, value in common_vars.items():
                    unassigned_vars[var_name] = value

                section_names = sorted(set(plan_counts_by_game.keys()) | set(guard_counts_by_game.keys()) | set(vars_by_game.keys()))
                for idx, game_name in enumerate(section_names):
                    if idx > 0:
                        f.write("\n")
                    f.write(f"[{game_name}]\n")
                    f.write(" - [플랜]\n")
                    for plan_name, count in sorted(plan_counts_by_game.get(game_name, {}).items()):
                        f.write(f"  - {plan_name}: {count}\n")
                    f.write(" - [가드]\n")
                    for guard_name, count in sorted(guard_counts_by_game.get(game_name, {}).items()):
                        f.write(f"  - {guard_name}: {count}\n")
                    f.write(" - [변수]\n")
                    for var_name, count in sorted(vars_by_game.get(game_name, {}).items()):
                        f.write(f"  - {var_name}: {count}\n")

                if unassigned_vars:
                    if section_names:
                        f.write("\n")
                    f.write("[미지정 게임]\n")
                    f.write(" - [플랜]\n")
                    f.write(" - [가드]\n")
                    f.write(" - [변수]\n")
                    for var_name, count in sorted(unassigned_vars.items()):
                        f.write(f"  - {var_name}: {count}\n")
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}]  [💾 기록] 일일 기록 변수 디스크 동기화 완료")
        except Exception as e:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] [⚠ 에러] 일일 기록 동기화 오류: {e}")

    def initialize_variables(self, config_node_id=None):
        """_initialize_daily_variables의 외부 공개 버전（config は Game ノードID）"""
        cfg_id = config_node_id
        if not cfg_id:
            cfg_id = getattr(self.runner, 'active_game_id', None) or self.runner.get_entry_start_node_id()
        if not cfg_id:
            return
        cfg_node = self.runner.nodes.get(cfg_id)
        if not cfg_node:
            return
        daily_vars_str = cfg_node.get('custom', {}).get('daily_variables', '[]')
        try:
            vars_list = json.loads(daily_vars_str)
        except Exception:
            vars_list = []
            
        if not vars_list: return
            
        record_file = self._get_daily_record_file()
        # 캐싱 초기 로드
        if os.path.exists(record_file):
            try:
                with open(record_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    data, scopes = self._parse_record_content(content)
                    for sk, sv in scopes.items():
                        if sk not in self.variable_scopes:
                            self.variable_scopes[sk] = sv
                    # self.variables에 병합
                    for k, v in data.items():
                        if k not in self.variables:
                            self.variables[k] = v
            except Exception:
                pass

        changed = False
        for v in vars_list:
            if isinstance(v, dict):
                label = v.get('label')
                if label and label not in self.variables:
                    self.variables[label] = int(v.get('value', 0))
                    changed = True
            elif isinstance(v, str):
                if v and v not in self.variables:
                    self.variables[v] = 0
                    changed = True
                    
        if changed:
            self.sync_to_file()
