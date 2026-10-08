# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qgis.PyQt.QtCore import (
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QTemporaryFile,
)
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtTest import QSignalSpy

from nextgis_connect.features.resource_browser.domain import (
    ResourceKind,
    ResourceMenuAction,
    ResourceMenuContext,
    ResourceMenuItem,
    ResourceMenuPolicy,
)
from nextgis_connect.legacy.ngw.core.ngw_resource import NGWResource
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job import (
    NGWResourceModelJobResult,
)
from nextgis_connect.legacy.shell.presentation.dock import ng_connect_dock
from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
    NgConnectDock,
)
from nextgis_connect.legacy.tree_widget.model import (
    NGWResourceModelResponse,
    QNGWResourceTreeModelBase,
)
from nextgis_connect.platform.qgis.utils import SupportStatus


def resource(
    resource_id,
    parent_id=None,
    cls="resource_group",
    server="https://example.test",
):
    connection = SimpleNamespace(
        server_url=server, connection_id=server, put=Mock()
    )
    factory = SimpleNamespace(connection=connection)
    result = NGWResource(
        factory,
        {
            "resource": {
                "id": resource_id,
                "cls": cls,
                "display_name": str(resource_id),
                "parent": {"id": parent_id} if parent_id is not None else None,
                "owner_user": None,
                "children": False,
            }
        },
    )
    result.update = Mock()
    result.get_parent = Mock(return_value=None)
    return result


@pytest.mark.parametrize("parent_class", ["resource_group", "demo_project"])
def test_move_updates_only_parent(parent_class):
    source = resource(2, 1, "vector_layer")
    source.get_parent.return_value = resource(1, cls=parent_class)
    target = resource(3)
    source.move_to(target)
    source.connection.put.assert_called_once_with(
        "/api/resource/2", params={"resource": {"parent": {"id": 3}}}
    )
    assert source.parent_id == 3


@pytest.mark.parametrize("target_class", ["demo_project", "vector_layer"])
def test_move_rejects_non_group_target(target_class):
    source = resource(2, 1)
    with pytest.raises(ValueError):
        source.move_to(resource(3, cls=target_class))
    source.connection.put.assert_not_called()


def test_move_rejects_another_server_before_any_request():
    source = resource(2, 1)
    with pytest.raises(ValueError):
        source.move_to(resource(3, server="https://another.test"))
    source.update.assert_not_called()
    source.connection.put.assert_not_called()


@pytest.mark.parametrize("descendant", [False, True])
def test_move_rejects_self_and_descendants(descendant):
    source = resource(2, 1)
    source.get_parent.return_value = resource(1)
    target = resource(3) if descendant else source
    if descendant:
        target.get_parent.return_value = source
    with pytest.raises(ValueError):
        source.move_to(target)
    source.connection.put.assert_not_called()


def test_move_rejects_child_of_layer():
    source = resource(2, 1, "qgis_vector_style")
    source.get_parent.return_value = resource(1, cls="vector_layer")
    with pytest.raises(ValueError):
        source.move_to(resource(3))
    source.connection.put.assert_not_called()


def test_move_failure_preserves_parent():
    source = resource(2, 1)
    source.get_parent.return_value = resource(1)
    source.connection.put.side_effect = RuntimeError("Permission denied")
    with pytest.raises(RuntimeError):
        source.move_to(resource(3))
    assert source.parent_id == 1


def test_model_move_preserves_loaded_subtree(qgis_app):
    model = QNGWResourceTreeModelBase()
    root = model.addNGWResourceToTree(QModelIndex(), resource(0))
    old_parent = model.addNGWResourceToTree(root, resource(1, 0))
    target = model.addNGWResourceToTree(root, resource(3, 0))
    source = resource(2, 1)
    source_index = model.addNGWResourceToTree(old_parent, source)
    model.addNGWResourceToTree(source_index, resource(4, 2))
    model.addNGWResourceToTree(target, resource(5, 3))
    source_item = source_index.internalPointer()
    moved = deepcopy(source)
    moved.common.parent.id = 3
    result = NGWResourceModelJobResult()
    result.putEditedResource(moved, is_main=True)
    job = SimpleNamespace(
        getResult=lambda: result,
        error=lambda: None,
        getJobId=lambda: "NGWMoveResource",
        model_response=None,
    )
    model.processJobResult(job)
    moved_index = model.index_from_id(2)
    assert moved_index.parent() == target
    assert moved_index.internalPointer() is source_item
    assert source_item.childCount() == 1
    assert model.index_from_id(4).parent() == moved_index
    assert old_parent.internalPointer().childCount() == 0
    assert [
        model.index(row, 0, target).data(Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount(target))
    ] == ["2", "5"]
    model.deleteLater()


@pytest.mark.parametrize("remaining_children", [0, 1])
def test_model_move_updates_known_child_counts(qgis_app, remaining_children):
    model = QNGWResourceTreeModelBase()
    model.support_status = SupportStatus.SUPPORTED
    root = model.addNGWResourceToTree(QModelIndex(), resource(0))
    old_resource = resource(1, 0)
    old_parent = model.addNGWResourceToTree(root, old_resource)
    target_resource = resource(3, 0)
    target = model.addNGWResourceToTree(root, target_resource)
    source = resource(2, 1)
    model.addNGWResourceToTree(old_parent, source)
    if remaining_children:
        model.addNGWResourceToTree(old_parent, resource(4, 1))
    old_resource.set_children_count(remaining_children + 1)
    target_resource.set_children_count(0)
    moved = deepcopy(source)
    moved.common.parent.id = 3
    result = NGWResourceModelJobResult()
    result.putEditedResource(moved, is_main=True)

    model.processJobResult(
        SimpleNamespace(
            getResult=lambda: result,
            error=lambda: None,
            getJobId=lambda: "NGWMoveResource",
            model_response=None,
        )
    )

    assert not model.canFetchMore(old_parent)
    assert old_resource.children_count == remaining_children
    assert model.hasChildren(old_parent) == bool(remaining_children)
    assert target_resource.children_count == 1
    assert model.hasChildren(target)
    model.deleteLater()


def test_cut_highlight_can_be_cleared_after_tree_reset(qgis_app):
    model = QNGWResourceTreeModelBase()
    source = resource(2)
    model.addNGWResourceToTree(QModelIndex(), source)
    model.set_cut_resource(source)
    model.resetModel(None)

    model.set_cut_resource(None)

    assert model.rowCount() == 0
    model.deleteLater()


@pytest.mark.parametrize("into_root", [False, True])
def test_move_keeps_parent_notifications_and_job_locks_valid(
    qgis_app, into_root
):
    model = QNGWResourceTreeModelBase()
    root = model.addNGWResourceToTree(QModelIndex(), resource(0))
    group = model.addNGWResourceToTree(root, resource(3, 0))
    source = resource(1, 3 if into_root else 0)
    model.addNGWResourceToTree(group if into_root else root, source)
    group = model.index_from_id(3)
    moved = deepcopy(source)
    moved.common.parent.id = 0 if into_root else 3
    result = NGWResourceModelJobResult()
    result.putEditedResource(moved, is_main=True)
    job = Mock()
    job.getResult.return_value = result
    job.error.return_value = None
    job.getJobId.return_value = "NGWMoveResource"
    job.model_response = None
    model._lockIndexByJob([root, group], job)
    notifications = QSignalSpy(model.dataChanged)

    model.processJobResult(job)
    model._unlockIndexesByJob(job)

    for index, *_ in notifications:
        current_index = model.index_from_id(
            index.data(ng_connect_dock.QNGWResourceItem.NGWResourceIdRole)
        )
        assert index == current_index
        assert not current_index.internalPointer().locked
    model.deleteLater()


def test_cut_style_copies_selected_index_instead_of_current(
    qgis_app, monkeypatch
):
    source = Mock(spec=ng_connect_dock.NGWQGISVectorStyle)
    source.display_name = "Selected style"
    selected_index = Mock()
    selected_index.data.return_value = source
    current_resource = Mock(spec=ng_connect_dock.NGWQGISVectorStyle)
    current_resource.display_name = "Deselected current style"
    current_index = Mock()
    current_index.data.return_value = current_resource
    clipboard = Mock()
    clipboard.mime_data.return_value = QMimeData()
    clipboard.set_mime_data.side_effect = lambda data: setattr(
        clipboard.mime_data, "return_value", data
    )
    monkeypatch.setattr(ng_connect_dock, "Clipboard", lambda: clipboard)
    qml_file = QTemporaryFile()
    assert qml_file.open()
    qml_file.write(b"<qgis><layerGeometryType>1</layerGeometryType></qgis>")
    qml_file.close()
    dock = SimpleNamespace(
        resources_tree_view=SimpleNamespace(
            selectedIndexes=lambda: [selected_index],
            selectionModel=lambda: SimpleNamespace(
                currentIndex=lambda: current_index
            ),
        ),
        proxy_model=SimpleNamespace(mapToSource=lambda index: index),
        resource_model=Mock(),
        _NgConnectDock__create_resource_menu_context=lambda indexes: (
            SimpleNamespace(can_cut_resource=True)
        ),
        _downloadStyleAsQML=Mock(return_value=True),
        dwn_qml_file=qml_file,
        _NgConnectDock__show_status_message=Mock(),
        tr=lambda text: text,
    )
    dock.copy_style = lambda **kwargs: NgConnectDock.copy_style(dock, **kwargs)

    NgConnectDock._NgConnectDock__cut_selected_resource(dock)

    dock._downloadStyleAsQML.assert_called_once_with(source, mes_bar=False)
    assert (
        bytes(clipboard.mime_data().data("application/x-nextgis-style-name"))
        == b"Selected style"
    )
    assert dock._NgConnectDock__cut_resource is source


@pytest.mark.parametrize("is_root", [False, True])
def test_cut_menu_requires_capability_and_non_root(is_root):
    policy = ResourceMenuPolicy()
    for can_cut in (False, True):
        layout = policy.create_layout(
            ResourceMenuContext(
                resources=(
                    ResourceMenuItem(ResourceKind.UNKNOWN, is_root=is_root),
                ),
                can_cut_resource=can_cut,
            )
        )
        assert layout.contains_action(ResourceMenuAction.CUT_RESOURCE) == (
            can_cut and not is_root
        )


@pytest.mark.parametrize(
    "kind", [ResourceKind.GROUP, ResourceKind.VECTOR_LAYER]
)
def test_paste_menu_requires_compatible_source(kind):
    for can_paste in (False, True):
        layout = ResourceMenuPolicy().create_layout(
            ResourceMenuContext(
                resources=(ResourceMenuItem(kind),),
                can_paste_resource=can_paste,
            )
        )
        assert layout.contains_action(ResourceMenuAction.PASTE_RESOURCE) == (
            can_paste
        )


@pytest.mark.parametrize(
    "case",
    [
        "group",
        "other_server",
        "demo",
        "self",
        "descendant",
        "old_parent",
        "locked",
    ],
)
def test_paste_availability_checks_server_and_hierarchy(qgis_app, case):
    model = QNGWResourceTreeModelBase()
    root = model.addNGWResourceToTree(QModelIndex(), resource(0))
    old_parent = model.addNGWResourceToTree(root, resource(1, 0))
    source = resource(2, 1)
    source_index = model.addNGWResourceToTree(old_parent, source)
    target_resource = resource(3, 0)
    if case == "other_server":
        target_resource.connection.server_url = "https://another.test"
    if case == "demo":
        target_resource.common.cls = "demo_project"
    target = model.addNGWResourceToTree(root, target_resource)
    if case == "self":
        target = source_index
    elif case == "descendant":
        target = model.addNGWResourceToTree(source_index, resource(4, 2))
    elif case == "old_parent":
        target = old_parent
    elif case == "locked":
        old_parent.internalPointer().lock()
    dock = SimpleNamespace(
        resource_model=model,
        _NgConnectDock__cut_resource=source,
        _NgConnectDock__has_cut_resource=lambda: True,
    )
    assert NgConnectDock._NgConnectDock__can_paste_resource(dock, target) == (
        case == "group"
    )
    model.deleteLater()


@pytest.mark.parametrize("has_cut", [False, True])
def test_paste_shortcut_selects_resource_or_style(has_cut):
    trigger = Mock()
    dock = SimpleNamespace(
        _NgConnectDock__has_cut_resource=lambda: has_cut,
        _NgConnectDock__trigger_resource_style_shortcut=trigger,
    )
    NgConnectDock._NgConnectDock__paste_resource_style_shortcut(dock)
    trigger.assert_called_once_with(
        ResourceMenuAction.PASTE_RESOURCE
        if has_cut
        else ResourceMenuAction.PASTE_STYLE
    )


def test_replacing_clipboard_invalidates_cut(monkeypatch):
    mime_data = Mock()
    mime_data.data.return_value = b"another clipboard value"
    monkeypatch.setattr(
        ng_connect_dock,
        "Clipboard",
        lambda: SimpleNamespace(mime_data=lambda: mime_data),
    )
    dock = SimpleNamespace(
        _NgConnectDock__cut_resource=resource(2, 1),
        _NgConnectDock__cut_token=b"original token",
    )
    assert not NgConnectDock._NgConnectDock__has_cut_resource(dock)


@pytest.mark.parametrize("load_fails", [False, True])
def test_paste_waits_for_target_loading(qgis_app, load_fails):
    tree_model = QNGWResourceTreeModelBase()
    target = tree_model.addNGWResourceToTree(QModelIndex(), resource(0))
    response = NGWResourceModelResponse()
    model = Mock()
    model.canFetchMore.return_value = True
    model.load_resource_children.return_value = response
    continue_move = Mock()
    dock = SimpleNamespace(
        resources_tree_view=SimpleNamespace(selectedIndexes=lambda: [target]),
        proxy_model=SimpleNamespace(mapToSource=lambda index: index),
        resource_model=model,
        _NgConnectDock__can_paste_resource=lambda index: True,
        _NgConnectDock__cut_token=b"token",
        _NgConnectDock__continue_resource_move=continue_move,
    )
    NgConnectDock._NgConnectDock__paste_cut_resource(dock)
    model.load_resource_children.assert_called_once_with(target)
    model.move_resource.assert_not_called()
    continue_move.assert_not_called()
    if load_fails:
        response.failed.emit(RuntimeError("Loading failed"))
    response.finished.emit()
    assert continue_move.call_count == (0 if load_fails else 1)
    tree_model.deleteLater()


def test_cut_item_is_dimmed_and_italic_until_cleared(qgis_app):
    model = QNGWResourceTreeModelBase()
    source = resource(2)
    index = model.addNGWResourceToTree(QModelIndex(), source)
    model.set_cut_resource(source)
    assert model.data(index, Qt.ItemDataRole.FontRole).italic()
    assert model.data(index, Qt.ItemDataRole.ForegroundRole).color().isValid()
    assert model.data(index, Qt.ItemDataRole.BackgroundRole).color().isValid()
    another_server = resource(2, server="https://another.test")
    model.set_cut_resource(another_server)
    assert not isinstance(model.data(index, Qt.ItemDataRole.FontRole), QFont)
    model.set_cut_resource(None)
    assert not isinstance(model.data(index, Qt.ItemDataRole.FontRole), QFont)
    model.deleteLater()


@pytest.mark.parametrize("cut_active", [False, True])
def test_cut_rendering_does_not_resolve_server_settings(qgis_app, cut_active):
    class Connection:
        connection_id = "test-connection"

        @property
        def server_url(self):
            raise AssertionError("Rendering must not resolve server settings")

    model = QNGWResourceTreeModelBase()
    source = resource(2)
    index = model.addNGWResourceToTree(QModelIndex(), source)
    source.res_factory.connection = Connection()
    if cut_active:
        model.set_cut_resource(source)
    for role in (
        Qt.ItemDataRole.DisplayRole,
        Qt.ItemDataRole.DecorationRole,
        Qt.ItemDataRole.FontRole,
        Qt.ItemDataRole.ForegroundRole,
        Qt.ItemDataRole.BackgroundRole,
        Qt.ItemDataRole.ToolTipRole,
    ):
        model.data(index, role)
    model.deleteLater()


def test_clipboard_change_clears_cut_highlight():
    model = Mock()
    dock = SimpleNamespace(
        resource_model=model,
        _NgConnectDock__has_cut_resource=lambda: False,
        _NgConnectDock__cut_resource=resource(2),
        _NgConnectDock__cut_token=b"old token",
    )
    NgConnectDock._NgConnectDock__sync_cut_resource(dock)
    assert dock._NgConnectDock__cut_resource is None
    model.set_cut_resource.assert_called_once_with(None)


@pytest.mark.parametrize("accepted", [False, True])
def test_move_requires_confirmation(qgis_app, accepted):
    tree = QNGWResourceTreeModelBase()
    target = tree.addNGWResourceToTree(QModelIndex(), resource(3))
    source = resource(2, 1)
    model = Mock()
    model.move_resource.return_value = NGWResourceModelResponse()
    dock = SimpleNamespace(
        resource_model=model,
        _NgConnectDock__cut_resource=source,
        _NgConnectDock__cut_token=b"token",
        _NgConnectDock__can_paste_resource=lambda index: True,
        _NgConnectDock__confirm_resource_move=Mock(return_value=accepted),
        _NgConnectDock__finish_resource_move=Mock(),
    )
    NgConnectDock._NgConnectDock__continue_resource_move(
        dock, b"token", QPersistentModelIndex(target)
    )
    assert model.move_resource.call_count == int(accepted)
    tree.deleteLater()


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_cut_style_is_deleted_only_after_successful_paste(
    qgis_app, monkeypatch, replace, success, cancelled
):
    source = Mock(spec=ng_connect_dock.NGWQGISVectorStyle)
    target = Mock(
        spec=ng_connect_dock.NGWQGISVectorStyle
        if replace
        else ng_connect_dock.NGWVectorLayer
    )
    target.display_name = "target"
    target.generate_unique_child_name.return_value = "new style"
    index = Mock()
    index.data.return_value = target
    index.parent.return_value.data.return_value = Mock()
    mime_data = Mock()
    mime_data.data.return_value = b"source style"
    monkeypatch.setattr(
        ng_connect_dock,
        "Clipboard",
        lambda: SimpleNamespace(mime_data=lambda: mime_data),
    )
    create = Mock(return_value=success)
    update = Mock(return_value=success)
    delete = Mock()
    dock = SimpleNamespace(
        tr=lambda text: text,
        _NgConnectDock__cut_token=b"token",
        _NgConnectDock__clipboard_style_qml=lambda: "<qgis/>",
        _NgConnectDock__has_cut_resource=lambda: True,
        _NgConnectDock__is_qml_style_compatible=lambda layer, qml: True,
        _NgConnectDock__confirm_style_replacement=lambda: not cancelled,
        _NgConnectDock__request_style_name=lambda *args: (
            None if cancelled else "new style"
        ),
        _NgConnectDock__replace_style_qml=update,
        _NgConnectDock__create_style_from_qml=create,
        _NgConnectDock__delete_pasted_cut_style=delete,
    )
    NgConnectDock.paste_style(dock, cut_source=source, target_index=index)
    assert delete.call_count == int(success and not cancelled)
    assert update.call_count == int(replace and not cancelled)
    assert create.call_count == int(not replace and not cancelled)


def test_clipboard_actions_have_separate_menu_section():
    context = ResourceMenuContext(
        resources=(ResourceMenuItem(ResourceKind.QGIS_VECTOR_STYLE),),
        can_cut_resource=True,
        can_paste_resource=True,
    )
    layout = ResourceMenuPolicy().create_layout(context)
    clipboard_section = next(
        section
        for section in layout.sections
        if section.contains_action(ResourceMenuAction.CUT_RESOURCE)
    )
    assert clipboard_section.actions == (
        ResourceMenuAction.CUT_RESOURCE,
        ResourceMenuAction.COPY_STYLE,
        ResourceMenuAction.PASTE_RESOURCE,
    )
    assert not clipboard_section.contains_action(
        ResourceMenuAction.RENAME_RESOURCE
    )


@pytest.mark.parametrize("compatible", [False, True])
@pytest.mark.parametrize("same_server", [False, True])
def test_cut_style_paste_checks_compatibility_and_server(
    compatible, same_server
):
    source = Mock(spec=ng_connect_dock.NGWQGISVectorStyle)
    source.resource_id = 2
    source.parent_id = 1
    source.connection = SimpleNamespace(server_url="https://example.test")
    target = Mock(spec=ng_connect_dock.NGWVectorLayer)
    target.resource_id = 3
    target.connection = SimpleNamespace(
        server_url="https://example.test"
        if same_server
        else "https://another.test"
    )
    source_index = Mock()
    source_index.data.return_value = source
    source_index.internalPointer.return_value.locked = False
    source_index.parent.return_value.internalPointer.return_value.locked = (
        False
    )
    target_index = Mock()
    target_index.data.side_effect = lambda role: (
        target
        if role == ng_connect_dock.QNGWResourceItem.NGWResourceRole
        else 3
    )
    target_index.internalPointer.return_value.locked = False
    target_index.parent.return_value = QModelIndex()
    dock = SimpleNamespace(
        resource_model=SimpleNamespace(
            index_from_id=lambda resource_id: source_index
        ),
        _NgConnectDock__cut_resource=source,
        _NgConnectDock__has_cut_resource=lambda: True,
        _NgConnectDock__clipboard_style_qml=lambda: "<qgis/>",
        _NgConnectDock__is_qml_style_compatible=lambda layer, qml: compatible,
    )
    assert NgConnectDock._NgConnectDock__can_paste_resource(
        dock, target_index
    ) == (compatible and same_server)


@pytest.mark.parametrize("geometry", [0, 1, 2, -1])
def test_qml_paste_uses_same_geometry_compatibility_for_cut(geometry):
    layer = Mock(spec=ng_connect_dock.NGWVectorLayer)
    layer.geometry_type = geometry
    qml = "<qgis><layerGeometryType>1</layerGeometryType></qgis>"
    assert NgConnectDock._NgConnectDock__is_qml_style_compatible(
        None, layer, qml
    ) == (geometry == 1)
