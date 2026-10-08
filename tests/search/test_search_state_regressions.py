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

import pytest
from qgis.PyQt.QtCore import QByteArray, Qt
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtTest import QSignalSpy, QTest
from qgis.PyQt.QtWidgets import QAction, QToolButton, QWidget

from nextgis_connect.features.search.domain.resource_type_catalog import (
    ResourceTypeCatalogParser,
)
from nextgis_connect.legacy.search.resource_type_search_widget import (
    ResourceTypeSearchWidget,
)
from nextgis_connect.legacy.search.search_panel import SearchPanel
from nextgis_connect.legacy.search.utils import SearchType
from nextgis_connect.legacy.tree_widget.model import (
    NGWResourceModelJobResult,
    NGWResourceModelResponse,
    QNGWResourceTreeModel,
    QNGWResourceTreeModelBase,
)
from nextgis_connect.ui_kit.widgets.interaction_guard import InteractionGuard
from nextgis_connect.ui_kit.widgets.multi_select_combo_box import (
    MultiSelectComboBox,
)


def test_late_blueprint_does_not_reset_expression(
    qgis_app, reset_qgis_settings
):
    parent = QWidget()
    panel = SearchPanel(None, parent)
    panel.set_type(SearchType.ByResourceType)
    panel.set_type(SearchType.ByDisplayName)
    panel._SearchPanel__text_search_widget.setText("Roads")
    panel.mark_search_applied()
    resets = QSignalSpy(panel.reset_requested)
    types = panel.findChild(ResourceTypeSearchWidget)
    types._ResourceTypeSearchWidget__set_resource_types(
        {"resources": {"vector_layer": {"label": "Vector"}}}
    )
    assert len(resets) == 0
    parent.close()


@pytest.mark.parametrize(
    "blueprint",
    [
        {"resources": {"vector_layer": {"label": None}}},
        {"categories": None},
        {"resources": []},
    ],
)
def test_invalid_blueprint_is_rejected_at_boundary(blueprint):
    with pytest.raises(ValueError):
        ResourceTypeCatalogParser().parse(blueprint)


def test_invalid_network_response_reports_error_and_releases_reply(qgis_app):
    class Reply(QNetworkReply):
        released = False

        def readAll(self):
            return QByteArray(
                b'{"resources": {"vector_layer": {"label": null}}}'
            )

        def deleteLater(self):
            self.released = True
            super().deleteLater()

    widget = ResourceTypeSearchWidget(None)
    reply = Reply(widget)
    widget._ResourceTypeSearchWidget__resource_types_network_reply = reply
    reply.finished.connect(
        widget._ResourceTypeSearchWidget__update_resource_types
    )
    reply.finished.emit()
    combo = widget.findChild(MultiSelectComboBox)
    assert combo.defaultText() == "Unable to load resource types"
    assert not combo.isEnabled()
    assert reply.released
    assert (
        widget._ResourceTypeSearchWidget__resource_types_network_reply is None
    )


def test_guard_preserves_live_action_state(qgis_app):
    scope = QWidget()
    button = QToolButton(scope)
    action = QAction("Action", scope)
    button.setDefaultAction(action)
    allowed = QToolButton(scope)
    guard = InteractionGuard(scope, (allowed,), scope)
    scope.show()
    guard.set_active(True)
    clicks = QSignalSpy(action.triggered)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(clicks) == 0
    action.setEnabled(False)
    guard.set_active(False)
    assert not action.isEnabled()
    action.setEnabled(True)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(clicks) == 1
    scope.close()


@pytest.mark.parametrize(
    "error,resources,expected",
    [
        (None, [1], False),
        (RuntimeError("Failed"), None, True),
        (None, None, True),
    ],
)
def test_only_successful_search_applies_query(
    qgis_app, reset_qgis_settings, error, resources, expected
):
    parent = QWidget()
    panel = SearchPanel(None, parent)
    field = panel._SearchPanel__text_search_widget
    field.setText("Roads")
    panel.mark_search_applied()
    field.setText("Buildings")
    pending = QSignalSpy(panel.criteria_pending)
    response = NGWResourceModelResponse()
    result = NGWResourceModelJobResult()
    result.found_resources = resources
    job = SimpleNamespace(
        model_response=response,
        getResult=lambda: result,
        error=lambda: error,
        getJobId=lambda: "NgwSearch",
    )
    panel.track_search(response, panel.current_query())
    model = QNGWResourceTreeModelBase()
    model._search_job = job
    model.processJobResult(job)
    response.finished.emit()
    field.setText("Buildings ")
    assert pending[-1][0] is expected
    parent.close()


def test_reset_invalidates_pending_completion(qgis_app, reset_qgis_settings):
    parent = QWidget()
    panel = SearchPanel(None, parent)
    field = panel._SearchPanel__text_search_widget
    field.setText("Roads")
    job = NGWResourceModelResponse()
    panel.track_search(job, panel.current_query())
    panel.mark_search_reset()
    job.search_completed.emit()
    job.finished.emit()
    pending = QSignalSpy(panel.criteria_pending)
    field.setText("Buildings")
    assert pending[-1][0] is False
    parent.close()


def test_hiding_search_clears_pending_notice(qgis_app, reset_qgis_settings):
    from nextgis_connect.legacy.shell.presentation.dock.ng_connect_dock import (
        NgConnectDock,
    )

    parent = QWidget()
    panel = SearchPanel(None, parent)
    field = panel._SearchPanel__text_search_widget
    field.setText("Roads")
    panel.mark_search_applied()
    field.setText("Buildings")
    pending = QSignalSpy(panel.criteria_pending)
    dock = SimpleNamespace(
        resource_model=SimpleNamespace(reset_search=lambda: None),
        search_panel=panel,
        _NgConnectDock__clear_search_connection_target=lambda: None,
    )
    NgConnectDock._NgConnectDock__toggle_filter(dock, False)
    assert pending[-1][0] is False
    parent.close()


@pytest.mark.parametrize("superseded", [False, True])
def test_late_search_result_does_not_change_tree(qgis_app, superseded):
    model = QNGWResourceTreeModel()
    response = NGWResourceModelResponse()
    result = NGWResourceModelJobResult()
    result.found_resources = [1]
    job = SimpleNamespace(
        model_response=response,
        getResult=lambda: result,
        error=lambda: None,
        getJobId=lambda: "NgwSearch",
    )
    model._search_job = job
    model.reset_search()
    if superseded:
        model._search_job = object()
    changes = QSignalSpy(model.found_resources_changed)
    completed = QSignalSpy(response.search_completed)
    model.processJobResult(job)
    assert len(changes) == 0
    assert len(completed) == 0
    assert model._found_resources_id == []


def test_connection_change_clears_applied_query(qgis_app, reset_qgis_settings):
    parent = QWidget()
    panel = SearchPanel(None, parent)
    field = panel._SearchPanel__text_search_widget
    field.setText("Roads")
    panel.mark_search_applied()
    panel.set_connection_id("")
    pending = QSignalSpy(panel.criteria_pending)
    field.setText("Buildings")
    assert pending[-1][0] is False
    parent.close()
