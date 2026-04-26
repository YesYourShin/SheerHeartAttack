import json
from types import MethodType

from NodeGraphQt import NodeGraph
from NodeGraphQt.base.commands import PortConnectedCmd
from NodeGraphQt.nodes.base_node import BaseNode
from PySide6 import QtWidgets

from framework.graph_migration import migrate_legacy_start_game_session

TYPE_COLORS = {
    "macro.nodes.StartNode": (50, 150, 50, 255),
    "macro.nodes.GameNode": (140, 95, 210, 255),
    "macro.nodes.PlanNode": (150, 105, 65, 255),
    "macro.nodes.RuleNode": (100, 100, 100, 255),
    "macro.nodes.GuardNode": (70, 130, 220, 255),
}


class SafeNodeGraph(NodeGraph):
    """
    NodeGraphQt의 load_session에서 발생할 수 있는 알 수 없는 속성 에러를 방지하고,
    세션 JSON のキー（ノード ID）と model.id / view.id を一致させる。
    （Guard の after_guard_target_plan_id など、保存したノード参照がロード後も有効になるようにする）
    """
    def _deserialize(self, data, relative_pos=False, pos=None, adjust_graph_style=True):
        migrate_legacy_start_game_session(data)
        nodes_block = data.get("nodes")
        if not nodes_block and isinstance(data.get("graph"), dict):
            nodes_block = data["graph"].get("nodes", {})
        for _node_id, node_data in (nodes_block or {}).items():
            node_type = node_data.get("type_")
            custom_props = node_data.get("custom", {})

            node_cls = self._node_factory.nodes.get(node_type)
            if not node_cls:
                continue

            if node_type == "macro.nodes.GuardNode":
                custom_props.setdefault("after_guard_complete", "resume")
                custom_props.setdefault("after_guard_target_plan_id", "")

            try:
                temp_node = node_cls()
                allowed_keys = set(temp_node.model.custom_properties.keys())
                for k in list(custom_props.keys()):
                    if k not in allowed_keys:
                        del custom_props[k]
            except Exception:
                pass

        def convert_last_list_to_set(d):
            for key, value in d.items():
                if isinstance(value, dict):
                    convert_last_list_to_set(value)
                elif isinstance(value, list):
                    d[key] = set(value)

        for attr_name, attr_value in data.get("graph", {}).items():
            if adjust_graph_style:
                if attr_name == "layout_direction":
                    self.set_layout_direction(attr_value)
                elif attr_name == "acyclic":
                    self.set_acyclic(attr_value)
                elif attr_name == "pipe_collision":
                    self.set_pipe_collision(attr_value)
                elif attr_name == "pipe_slicing":
                    self.set_pipe_slicing(attr_value)
                elif attr_name == "pipe_style":
                    self.set_pipe_style(attr_value)

            if attr_name == "accept_connection_types":
                attr_value = json.loads(attr_value)
                convert_last_list_to_set(attr_value)
                self.model.accept_connection_types = attr_value

            elif attr_name == "reject_connection_types":
                attr_value = json.loads(attr_value)
                convert_last_list_to_set(attr_value)
                self.model.reject_connection_types = attr_value

        nodes = {}
        for n_id, n_data in data.get("nodes", {}).items():
            identifier = n_data["type_"]
            node = self._node_factory.create_node_instance(identifier)
            if node:
                # 日本語: ファイル上のノードキーと実行時の node.id を一致（プロパティ内の参照 ID 互換）
                sid = str(n_id)
                node.model.id = sid
                node.view.id = sid

                node.NODE_NAME = n_data.get("name", node.NODE_NAME)
                for prop in node.model.properties.keys():
                    if prop == "color":
                        continue
                    if prop in n_data.keys():
                        node.model.set_property(prop, n_data[prop])
                for prop, val in n_data.get("custom", {}).items():
                    node.model.set_property(prop, val)
                    if isinstance(node, BaseNode):
                        if prop in node.view.widgets:
                            node.view.widgets[prop].set_value(val)

                nodes[n_id] = node
                self.add_node(node, n_data.get("pos"), inherite_graph_style=adjust_graph_style)
                self._apply_type_color(node)

                if n_data.get("port_deletion_allowed", None):
                    node.set_ports({
                        "input_ports": n_data["input_ports"],
                        "output_ports": n_data["output_ports"],
                    })

        for connection in data.get("connections", []):
            nid, pname = connection.get("in", ("", ""))
            in_node = nodes.get(nid) or self.get_node_by_id(nid)
            if not in_node:
                continue
            in_port = in_node.inputs().get(pname) if in_node else None

            nid, pname = connection.get("out", ("", ""))
            out_node = nodes.get(nid) or self.get_node_by_id(nid)
            if not out_node:
                continue
            out_port = out_node.outputs().get(pname) if out_node else None

            if in_port and out_port:
                allow_connection = any([
                    not in_port.model.connected_ports,
                    in_port.model.multi_connection,
                ])
                if allow_connection:
                    self._undo_stack.push(
                        PortConnectedCmd(in_port, out_port, emit_signal=False)
                    )
                in_node.on_input_connected(in_port, out_port)

        node_objs = list(nodes.values())
        if relative_pos:
            self._viewer.move_nodes([n.view for n in node_objs])
            for n in node_objs:
                setattr(n.model, "pos", n.view.xy_pos)
        elif pos:
            self._viewer.move_nodes([n.view for n in node_objs], pos=pos)
            for n in node_objs:
                setattr(n.model, "pos", n.view.xy_pos)

        return node_objs

    def _apply_type_color(self, node):
        rgba = TYPE_COLORS.get(getattr(node, "type_", ""))
        if rgba is None:
            return
        try:
            node.model.set_property("color", rgba)
        except Exception:
            pass

    def disable_auto_zoom_on_resize(self):
        viewer = self.viewer()
        if getattr(viewer, "_macro_resize_zoom_locked", False):
            return

        def _resize_without_auto_zoom(viewer_self, event):
            w, h = viewer_self.size().width(), viewer_self.size().height()
            if 0 in [w, h]:
                viewer_self.resize(viewer_self._last_size)
            viewer_self._last_size = viewer_self.size()
            QtWidgets.QGraphicsView.resizeEvent(viewer_self, event)

        viewer.resizeEvent = MethodType(_resize_without_auto_zoom, viewer)
        viewer._macro_resize_zoom_locked = True

    def disable_middle_drag_zoom(self):
        viewer = self.viewer()
        if getattr(viewer, "_macro_middle_drag_zoom_locked", False):
            return

        original_set_viewer_zoom = viewer._set_viewer_zoom

        def _set_viewer_zoom_without_middle_drag(viewer_self, value, sensitivity=None, pos=None):
            # 日本語: 中クリックドラッグ中のズームだけ無効化し、他のズーム(ホイール等)は維持する。
            if getattr(viewer_self, "MMB_state", False):
                return
            return original_set_viewer_zoom(value, sensitivity, pos=pos)

        viewer._set_viewer_zoom = MethodType(_set_viewer_zoom_without_middle_drag, viewer)
        viewer._macro_middle_drag_zoom_locked = True
