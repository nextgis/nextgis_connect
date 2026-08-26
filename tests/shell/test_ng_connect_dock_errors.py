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

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import qgis.utils
from qgis.core import Qgis, QgsLayerTreeLayer, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QModelIndex
from qgis.PyQt.QtWidgets import QMessageBox, QTreeView

from nextgis_connect.legacy.shell.presentation.dock import ng_connect_dock
from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
    NgConnectDock,
)
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem
from nextgis_connect.legacy.tree_widget.model import QNGWResourceTreeModelBase
from nextgis_connect.legacy.tree_widget.overlay import OverlayAction
from nextgis_connect.legacy.tree_widget.proxy_model import NgConnectProxyModel
from nextgis_connect.platform.qgis import utils
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgwConnectionError,
    NgwError,
)


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


def test_diagnostics_overlay_starts_diagnostics_immediately() -> None:
    dock = SimpleNamespace()
    open_diagnostics = Mock()
    dock._NgConnectDock__open_current_connection_diagnostics = open_diagnostics

    handle_action = NgConnectDock._NgConnectDock__handle_tree_overlay_action
    handle_action(dock, OverlayAction.RUN_DIAGNOSTICS)

    open_diagnostics.assert_called_once_with(start_immediately=True)


def test_root_loading_titles_include_ellipsis() -> None:
    begin_loading = Mock()
    dock = SimpleNamespace(
        resources_tree_view=SimpleNamespace(begin_loading=begin_loading),
        tr=lambda text: text,
        _NgConnectDock__root_loading_cancel_requested=True,
        _NgConnectDock__root_children_loading_parent_id=1,
        _NgConnectDock__cancel_pending_job_id="job",
    )

    start_loading = NgConnectDock._NgConnectDock__start_root_loading_overlay
    start_loading(dock)

    begin_loading.assert_called_once_with(
        "Loading Web GIS resources...",
        compact_title="Loading resources...",
        message="Loading the root resource.",
        draw_background=True,
    )


def test_add_layers_cancel_is_forwarded_to_active_importer() -> None:
    importer = Mock()
    mark_cancel_requested = Mock()
    dock = SimpleNamespace(
        _NgConnectDock__cancelable_job_ids=["AddLayersStub"],
        _NgConnectDock__active_resource_importer=importer,
        _NgConnectDock__cancel_pending_job_id=None,
        _NgConnectDock__mark_loading_cancel_requested=(mark_cancel_requested),
    )

    cancel_loading = NgConnectDock._NgConnectDock__cancel_active_loading
    cancel_loading(dock)

    importer.cancel.assert_called_once_with()
    mark_cancel_requested.assert_called_once_with("AddLayersStub")


def test_top_model_job_takes_cancel_priority_over_layer_importer() -> None:
    importer = Mock()
    resource_model = SimpleNamespace(cancel_job=Mock(return_value=True))
    mark_cancel_requested = Mock()
    dock = SimpleNamespace(
        resource_model=resource_model,
        _NgConnectDock__cancelable_job_ids=[
            "AddLayersStub",
            "ResourcesDownloader",
        ],
        _NgConnectDock__active_resource_importer=importer,
        _NgConnectDock__cancel_pending_job_id=None,
        _NgConnectDock__canceled_job_ids=set(),
        _NgConnectDock__mark_loading_cancel_requested=(mark_cancel_requested),
    )

    cancel_loading = NgConnectDock._NgConnectDock__cancel_active_loading
    cancel_loading(dock)

    resource_model.cancel_job.assert_called_once_with("ResourcesDownloader")
    importer.cancel.assert_not_called()
    mark_cancel_requested.assert_called_once_with("ResourcesDownloader")


def test_finishing_job_restores_previous_cancel_target() -> None:
    dock = SimpleNamespace(
        _NgConnectDock__cancelable_job_ids=[
            "ResourcesDownloader",
            "AddLayersStub",
            "NgwStylesDownloader",
        ],
    )
    remove_cancelable_job = NgConnectDock._NgConnectDock__remove_cancelable_job

    remove_cancelable_job(dock, "NgwStylesDownloader")
    assert dock._NgConnectDock__cancelable_job_ids[-1] == "AddLayersStub"

    remove_cancelable_job(dock, "AddLayersStub")
    assert dock._NgConnectDock__cancelable_job_ids[-1] == "ResourcesDownloader"


class _FakeModelResponse:
    def __init__(self) -> None:
        self.done = _FakeSignal()


class _FakeSelectionModel:
    def __init__(self, current_index) -> None:
        self._current_index = current_index

    def currentIndex(self):
        return self._current_index


class _FakeTreeView:
    def __init__(self, current_index) -> None:
        self._selection_model = _FakeSelectionModel(current_index)
        self.current_index = None

    def selectionModel(self) -> _FakeSelectionModel:
        return self._selection_model

    def setCurrentIndex(self, index) -> None:
        self.current_index = index


class _FakeProxyModel:
    def __init__(self, source_index) -> None:
        self._source_index = source_index

    def mapToSource(self, index):
        del index
        return self._source_index

    def mapFromSource(self, index):
        return ("proxy", index)


class _FakeSourceIndex:
    def __init__(self, resource) -> None:
        self._resource = resource

    def data(self, role):
        assert role == QNGWResourceItem.NGWResourceRole
        return self._resource


class _FakeButton:
    def __init__(self) -> None:
        self.text = None

    def setText(self, text: str) -> None:
        self.text = text


class _FakeMessageBox:
    Icon = QMessageBox.Icon
    StandardButton = QMessageBox.StandardButton
    next_result = QMessageBox.StandardButton.Yes
    last = None

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.icon = None
        self.window_title = None
        self.text = None
        self.text_format = None
        self.standard_buttons = None
        self.default_button = None
        self.buttons = {
            QMessageBox.StandardButton.Yes: _FakeButton(),
            QMessageBox.StandardButton.Cancel: _FakeButton(),
        }
        _FakeMessageBox.last = self

    def setIcon(self, icon) -> None:
        self.icon = icon

    def setWindowTitle(self, title: str) -> None:
        self.window_title = title

    def setText(self, text: str) -> None:
        self.text = text

    def setTextFormat(self, text_format) -> None:
        self.text_format = text_format

    def setStandardButtons(self, buttons) -> None:
        self.standard_buttons = buttons

    def setDefaultButton(self, button) -> None:
        self.default_button = button

    def button(self, button):
        return self.buttons[button]

    def exec(self):
        return self.next_result


class _FakeRootOverlayView:
    def __init__(self) -> None:
        self.calls = []

    def end_loading(self) -> None:
        self.calls.append(("end_loading",))

    def set_error_state(self, message: str, **kwargs) -> None:
        self.calls.append(("set_error_state", message, kwargs))


def _root_error_dock() -> tuple:
    overlay_view = _FakeRootOverlayView()
    dock = SimpleNamespace(
        resources_tree_view=overlay_view,
        disable_tools=lambda: None,
        tr=lambda text: text,
        _NgConnectDock__root_children_loading_parent_id=None,
        _NgConnectDock__root_loading_cancel_requested=False,
    )
    dock._NgConnectDock__error_candidates = (
        NgConnectDock._NgConnectDock__error_candidates
    )
    dock._NgConnectDock__is_nextgis_cloud_url = (
        NgConnectDock._NgConnectDock__is_nextgis_cloud_url
    )
    dock._NgConnectDock__is_nextgis_cloud_http_500_error = lambda exception: (
        NgConnectDock._NgConnectDock__is_nextgis_cloud_http_500_error(
            dock,
            exception,
        )
    )
    dock._NgConnectDock__is_connection_error = lambda exception: (
        NgConnectDock._NgConnectDock__is_connection_error(
            dock,
            exception,
        )
    )
    dock._NgConnectDock__connection_error_details = lambda: (
        NgConnectDock._NgConnectDock__connection_error_details(dock)
    )
    return dock, overlay_view


@pytest.mark.parametrize("job_name", [None, ""])
def test_reset_model_error_stops_root_loading(job_name) -> None:
    calls = []
    error = NgwError("Connection error", is_network_problem=True)
    dock = SimpleNamespace(
        _NgConnectDock__root_children_loading_parent_id=None,
        _NgConnectDock__root_loading_cancel_requested=False,
        unblock_gui=lambda: calls.append("unblock"),
        _NgConnectDock__show_root_loading_error=lambda exception: calls.append(
            ("root_error", exception)
        ),
    )
    process_exception = NgConnectDock._NgConnectDock__model_exception_process

    process_exception(
        dock,
        job_name,
        "",
        error,
        Qgis.MessageLevel.Critical,
    )

    assert calls == ["unblock", ("root_error", error)]


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://nextgis.com", True),
        ("https://demo.nextgis.com", True),
        ("https://demo.nextgis.ru", True),
        ("https://nextgis.com.attacker.example", False),
        ("https://evilnextgis.com", False),
        ("https://example.com", False),
    ],
)
def test_nextgis_cloud_url_requires_domain_boundary(url, expected) -> None:
    is_nextgis_cloud_url = NgConnectDock._NgConnectDock__is_nextgis_cloud_url

    assert is_nextgis_cloud_url(url) is expected


@pytest.mark.parametrize(
    "error",
    [
        NgwError("Connection error", is_network_problem=True),
        NgwConnectionError(code=ErrorCode.InvalidConnection),
    ],
)
def test_connection_error_uses_diagnostics_and_retry(error) -> None:
    dock, overlay_view = _root_error_dock()
    show_root_error = NgConnectDock._NgConnectDock__show_root_loading_error

    show_root_error(dock, error)

    _, message, state = overlay_view.calls[-1]
    assert state["title"] == "Unable to connect"
    assert message == ""
    assert state["details"] == (
        "The selected connection is invalid or unavailable.\n\n"
        "Run diagnostics to check the connection settings and server availability."
    )
    assert state["action"].action == OverlayAction.RUN_DIAGNOSTICS
    assert state["secondary_action"].action == OverlayAction.RELOAD_TREE


def test_connection_parameters_error_uses_diagnostics_and_retry() -> None:
    dock, overlay_view = _root_error_dock()
    show_connection_parameters_error = (
        NgConnectDock._NgConnectDock__show_connection_parameters_error
    )

    show_connection_parameters_error(dock)

    _, message, state = overlay_view.calls[-1]
    assert message == ""
    assert state["details"] == (
        "The selected connection is invalid or unavailable.\n\n"
        "Run diagnostics to check the connection settings and server availability."
    )
    assert state["action"].action == OverlayAction.RUN_DIAGNOSTICS
    assert state["secondary_action"].action == OverlayAction.RELOAD_TREE


@pytest.mark.parametrize(
    "url, status_code, expected_contact_support",
    [
        ("https://demo.nextgis.com", 500, True),
        ("https://demo.nextgis.ru", 500, True),
        ("https://nextgis.com.attacker.example", 500, False),
        ("https://example.com", 500, False),
        ("https://demo.nextgis.com", 503, False),
    ],
)
def test_http_error_offers_contact_support_only_for_nextgis_cloud_500(
    monkeypatch,
    url,
    status_code,
    expected_contact_support,
) -> None:
    dock, overlay_view = _root_error_dock()
    show_root_error = NgConnectDock._NgConnectDock__show_root_loading_error
    connection = SimpleNamespace(url=url)
    monkeypatch.setattr(
        ng_connect_dock,
        "NgwConnectionsManager",
        lambda: SimpleNamespace(current_connection=connection),
    )

    show_root_error(dock, NgwError(status_code=status_code))

    _, _, state = overlay_view.calls[-1]
    if expected_contact_support:
        assert state["action"].action == OverlayAction.RELOAD_TREE
        assert (
            state["secondary_action"].action == OverlayAction.CONTACT_SUPPORT
        )
    else:
        assert state["action"].action == OverlayAction.RELOAD_TREE
        assert (
            state["secondary_action"].action == OverlayAction.RUN_DIAGNOSTICS
        )


def test_create_group_cancel_refreshes_lazy_parent_branch(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    model = QNGWResourceTreeModelBase()
    model.support_status = utils.SupportStatus.SUPPORTED
    resource = SimpleNamespace(
        display_name="Group",
        common=SimpleNamespace(cls="resource_group", children=True),
        icon_path="",
        resource_id=1,
        type_id="resource_group",
        connection=SimpleNamespace(server_url=""),
        children_count=None,
    )
    item = QNGWResourceItem(resource)
    model.root_item.addChild(item)
    source_index = model.index(0, 0, QModelIndex())

    proxy_model = NgConnectProxyModel(None)
    proxy_model.setSourceModel(model)
    tree_view = QTreeView()
    tree_view.setModel(proxy_model)
    proxy_index = proxy_model.mapFromSource(source_index)
    tree_view.setCurrentIndex(proxy_index)

    refreshed_indexes = []

    def refresh_lazy_children_state(index: QModelIndex) -> None:
        refreshed_indexes.append(index)

    def fail_create_group(*args, **kwargs) -> None:
        del args
        del kwargs
        raise AssertionError("Create group job must not start after cancel")

    monkeypatch.setattr(
        ng_connect_dock.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("", False),
    )
    monkeypatch.setattr(
        model,
        "refresh_lazy_children_state",
        refresh_lazy_children_state,
    )
    monkeypatch.setattr(
        model,
        "tryCreateNGWGroup",
        fail_create_group,
        raising=False,
    )
    dock = SimpleNamespace(
        proxy_model=proxy_model,
        resources_tree_view=tree_view,
        resource_model=model,
        show_info=lambda message: None,
        tr=lambda text: text,
    )

    NgConnectDock.create_group(dock)

    assert len(refreshed_indexes) == 1
    assert refreshed_indexes[0].internalPointer() is item
    assert tree_view.currentIndex() == proxy_index

    tree_view.deleteLater()
    proxy_model.deleteLater()


def test_create_web_map_for_layer_cancel_without_styles_does_not_start_job(
    qgis_app,
) -> None:
    del qgis_app

    resource = SimpleNamespace(
        type_id=ng_connect_dock.NGWVectorLayer.type_id,
        display_name="Layer",
        get_children=list,
    )
    dock, _, _, create_calls = _web_map_dock(
        resource,
        should_create_default_style=False,
    )

    NgConnectDock.create_web_map_for_layer(dock)

    assert create_calls == []


def test_create_web_map_for_layer_accepts_default_style_creation(
    qgis_app,
) -> None:
    del qgis_app

    resource = SimpleNamespace(
        type_id=ng_connect_dock.NGWVectorLayer.type_id,
        display_name="Layer",
        get_children=list,
    )
    dock, source_index, response, create_calls = _web_map_dock(
        resource,
        should_create_default_style=True,
    )

    NgConnectDock.create_web_map_for_layer(dock)

    assert create_calls == [(source_index, None)]
    assert dock.create_map_response is response
    assert len(response.done.callbacks) == 2


def test_default_style_confirmation_uses_create_and_cancel_buttons(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ng_connect_dock, "QMessageBox", _FakeMessageBox)
    dock = SimpleNamespace(tr=lambda text: text)

    _FakeMessageBox.next_result = QMessageBox.StandardButton.Yes
    confirm_default_style = (
        NgConnectDock._NgConnectDock__confirm_create_default_style_for_web_map
    )
    result = confirm_default_style(dock, "Layer")

    box = _FakeMessageBox.last
    assert result is True
    assert box is not None
    assert box.window_title == "Create Web map for layer"
    assert 'Layer "Layer" has no styles.' in box.text
    assert box.default_button == QMessageBox.StandardButton.Cancel
    assert (
        box.buttons[QMessageBox.StandardButton.Yes].text
        == "Create default style"
    )

    _FakeMessageBox.next_result = QMessageBox.StandardButton.Cancel

    result = confirm_default_style(dock, "Layer")

    assert result is False


def test_select_qgis_layers_selects_added_layers(qgis_app) -> None:
    del qgis_app

    project = QgsProject.instance()
    first_layer = QgsVectorLayer("Point?crs=EPSG:4326", "First", "memory")
    second_layer = QgsVectorLayer("Point?crs=EPSG:4326", "Second", "memory")
    project.addMapLayers([first_layer, second_layer])
    dock = NgConnectDock.__new__(NgConnectDock)
    dock.iface = qgis.utils.iface

    try:
        dock._NgConnectDock__select_qgis_layers(
            (first_layer.id(), second_layer.id())
        )

        layer_tree_view = qgis.utils.iface.layerTreeView()
        selected_layer_ids = {
            node.layerId()
            for node in layer_tree_view.selectedNodes()
            if isinstance(node, QgsLayerTreeLayer)
        }
        current_node = layer_tree_view.currentNode()

        assert selected_layer_ids == {first_layer.id(), second_layer.id()}
        assert isinstance(current_node, QgsLayerTreeLayer)
        assert current_node.layerId() == second_layer.id()
    finally:
        project.removeMapLayers([first_layer.id(), second_layer.id()])


def _web_map_dock(
    resource,
    *,
    should_create_default_style: bool,
):
    source_index = _FakeSourceIndex(resource)
    proxy_index = object()
    response = _FakeModelResponse()
    create_calls = []

    def create_map_for_layer(index, style_id):
        create_calls.append((index, style_id))
        return response

    dock = SimpleNamespace(
        proxy_model=_FakeProxyModel(source_index),
        resources_tree_view=_FakeTreeView(proxy_index),
        resource_model=SimpleNamespace(createMapForLayer=create_map_for_layer),
        open_create_web_map=lambda index: None,
        tr=lambda text: text,
        _NgConnectDock__layer_style_children=lambda resource: [],
        _NgConnectDock__confirm_create_default_style_for_web_map=(
            lambda layer_name: should_create_default_style
        ),
    )
    return dock, source_index, response, create_calls
