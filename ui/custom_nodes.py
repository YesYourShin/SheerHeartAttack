from NodeGraphQt import BaseNode


class MacroBaseNode(BaseNode):
    """
    모든 커스텀 노드의 공통 부모 클래스.
    저장된 세션(JSON)을 불러올 때 현재 노드에 없는 속성(예: label)을 
    설정하려 하면 에러가 발생하므로, 이를 무시하도록 처리합니다.
    """
    def __init__(self):
        super(MacroBaseNode, self).__init__()
        # 구버전 JSON 호환용 (사용은 안 하지만 NodeGraphQt 로드 에러 방지용)
        self.create_property('label', '')
        
        # 노드 표면 이름 직접 편집 비활성화
        try:
            from Qt import QtCore
            if hasattr(self.view, 'text_item'):
                self.view.text_item.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
            elif hasattr(self.view, '_text_item'):
                self.view._text_item.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        except Exception:
            pass


class StartNode(MacroBaseNode):
    """매크로 진입점. Game 노드만 연결한다."""
    __identifier__ = 'macro.nodes'
    NODE_NAME = 'Start'

    def __init__(self):
        super(StartNode, self).__init__()
        self.set_color(50, 150, 50)
        self.add_output('out', color=(50, 200, 50))
        # 接続順の保存用（NodeGraphQt互換）
        self.create_property('connected_nodes_order', '[]')
        self.create_property('game_nodes_order', '[]')


class GameNode(MacroBaseNode):
    """ゲーム単位: Plan/Guard 順序・日次変数。Start からのみ接続。"""
    __identifier__ = 'macro.nodes'
    NODE_NAME = 'Game'

    def __init__(self):
        super(GameNode, self).__init__()
        self.set_color(140, 95, 210)
        self.add_input('in', color=(155, 120, 220))
        self.add_output('out', color=(170, 135, 230))
        self.create_property('connected_nodes_order', '[]')
        self.create_property('plan_nodes_order', '[]')
        self.create_property('guard_nodes_order', '[]')
        self.create_property('daily_variables', '[]')
        self.create_property('reset_time', '05:00:00')
        # 起動する Android パッケージ（空なら起動しない）
        self.create_property('launch_package', '')
        # 起動後、Guard/Plan 検査前に待つ秒（文字列で保存）
        self.create_property('post_launch_wait_seconds', '0')


class PlanNode(MacroBaseNode):
    """
    매크로 전체 설정 및 설계(Plan)를 선언하는 노드.
    Game 노드에 연결하여 해당 게임의 플랜을 구성합니다.
    """
    __identifier__ = 'macro.nodes'
    NODE_NAME = 'Plan'

    def __init__(self):
        super(PlanNode, self).__init__()
        self.set_color(150, 105, 65)
        self.add_input('in', color=(170, 125, 85))
        self.add_output('out', color=(180, 135, 95))
        
        self.create_property('loop_count', '1')
        # 개별 초기화 시간 사용 속성 (플랜 노드 전용)
        self.create_property('use_custom_reset_time', 'False')
        self.create_property('reset_time', '05:00:00')
        # Planの出力に接続したGuardの実行順（JSON、Gameのguard_nodes_orderと同様）
        self.create_property('guard_nodes_order', '[]')
        self.create_property('completion_counter_var', '')


class RuleNode(MacroBaseNode):
    """
    하나의 매크로 규칙(Rule) 블록.
    
    - 조건(conditions): 여러 개의 이미지/색상 조건 리스트 (모두 만족해야 matched)
    - 동작(actions): 여러 개의 클릭/대기 동작 리스트 (위에서 순서대로 실행)
    - matched 시 → 다음 노드로 이동
    - not matched 시 → 이 노드를 반복
    
    핀: in(입력), out(출력) 단 2개만.
    노드 표면에는 라벨만 표시.
    """
    __identifier__ = 'macro.nodes'
    NODE_NAME = 'Rule'

    def __init__(self):
        super(RuleNode, self).__init__()
        self.set_color(100, 100, 100)
        self.add_input('in', color=(200, 100, 100), multi_input=True)
        self.add_output('out', color=(100, 200, 100))
        
        # 조건 리스트 (JSON 문자열로 저장)
        # 예: [{"type":"image","image":"path.png","threshold":0.8}, {"type":"color",...}]
        self.create_property('conditions', '[]')
        
        # 캡처 이미지 경로 (노드당 1장)
        self.create_property('capture_image', '')
        
        # 동작 리스트 (JSON 문자열로 저장)
        self.create_property('actions', '[]')
        
        # 변수 조작 리스트 (JSON 문자열로 저장)
        self.create_property('variable_ops', '[]')
        
        # Rule 갈래 분기 우선순위 리스트 (다음 Rule들의 node_id 배열)
        self.create_property('out_nodes_order', '[]')
        self.create_property('next_rule_search_timeout_seconds', '5')


class GuardNode(MacroBaseNode):
    """
    공통 검증 노드 (Guard).

    - Game/Plan の出力から接続
    - Guard의 출력에 RuleNode를 연결하면, 매 루프마다 그 RuleNode를 먼저 검사
    - Guard에 연결된 RuleNode가 매칭되면 → Guard 흐름으로 진행
    - 매칭 안 되면 → 정상 Plan 흐름으로 진행
    - 예기치 못한 화면(팝업, 에러 등) 감지용
    """
    __identifier__ = 'macro.nodes'
    NODE_NAME = 'Guard'

    def __init__(self):
        super(GuardNode, self).__init__()
        self.set_color(70, 130, 220)
        self.add_input('in', color=(95, 150, 230))
        self.add_output('out', color=(95, 150, 230))

        self.create_property('loop_count', '1')
        # ガード処理完了後: resume / restart_from_start / goto_plan（goto時はafter_guard_target_plan_id）
        self.create_property('after_guard_complete', 'resume')
        self.create_property('after_guard_target_plan_id', '')
