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

from typing import ClassVar, List
from unittest import mock

import pytest
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.features.resource_browser.application import (
    ResourceAddingErrorContext,
    ResourceImportCancelledError,
)
from nextgis_connect.features.resource_browser.domain.resource_batch_import import (
    ResourceBatchImportStatus,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_import import (
    QgisResourceBatchImporter,
)
from nextgis_connect.features.resource_browser.infrastructure.resource_dependency_analyzer import (
    ResourceDependencyAnalyzer,
)
from nextgis_connect.features.resource_browser.presentation import (
    resource_import_interaction as interaction_module,
)
from nextgis_connect.legacy.dialog_choose_style import StyleFilterProxyModel
from nextgis_connect.legacy.ngw.core import NGWWebMap
from nextgis_connect.legacy.ngw.core.ngw_webmap import NGWWebMapLayer
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem
from nextgis_connect.platform.qgis.errors import ResourcePermissionError


class _ResourceModelProbe(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.forbidden_resource_ids = set()
        self.resources = {}

    def is_forbidden(self, resource_id: int) -> bool:
        return resource_id in self.forbidden_resource_ids

    def resource(self, resource_id: int):
        return self.resources.get(resource_id)


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _FakeCheckBox:
    def __init__(self, text: str) -> None:
        self.text = text
        self.checked = True

    def isChecked(self) -> bool:
        return self.checked


class _FakeMessageBox:
    Icon = QMessageBox.Icon
    StandardButton = QMessageBox.StandardButton
    StandardButtons = QMessageBox.StandardButtons
    instances: ClassVar[List["_FakeMessageBox"]] = []

    def __init__(self) -> None:
        self.window_title = ""
        self.text = ""
        self.informative_text = ""
        self.detailed_text = ""
        self.checkbox = None
        self.buttons = {
            QMessageBox.StandardButton.Ignore: _FakeButton(),
            QMessageBox.StandardButton.Cancel: _FakeButton(),
        }
        _FakeMessageBox.instances.append(self)

    def setWindowTitle(self, title: str) -> None:
        self.window_title = title

    def setIcon(self, icon) -> None:
        del icon

    def setText(self, text: str) -> None:
        self.text = text

    def setInformativeText(self, text: str) -> None:
        self.informative_text = text

    def setDetailedText(self, text: str) -> None:
        self.detailed_text = text

    def setStandardButtons(self, buttons) -> None:
        del buttons

    def button(self, button):
        return self.buttons[button]

    def setDefaultButton(self, button) -> None:
        del button

    def setCheckBox(self, checkbox) -> None:
        self.checkbox = checkbox

    def exec(self):
        return QMessageBox.StandardButton.Ignore


def _insertion_point():
    return (
        QgsProject.instance().layerTreeRegistryBridge().layerInsertionPoint()
    )


def _webmap() -> NGWWebMap:
    resource_factory = mock.Mock()
    resource_factory.connection.server_url = "https://example.nextgis.com/"
    return NGWWebMap(
        resource_factory,
        {
            "resource": {
                "id": 265,
                "cls": NGWWebMap.type_id,
                "display_name": "Map",
                "description": None,
                "parent": None,
                "owner_user": None,
                "children": False,
                "interfaces": [],
            },
            "webmap": {"root_item": {"children": []}},
        },
    )


def test_webmap_permission_error_names_inaccessible_layer(qgis_app) -> None:
    del qgis_app

    model = _ResourceModelProbe()
    model.forbidden_resource_ids.add(164)
    importer = QgisResourceBatchImporter(
        model,
        [],
        _insertion_point(),
        interaction_module.QgisResourceImportInteraction(lambda text: text),
    )
    webmap_layer = NGWWebMapLayer(
        264,
        "Restricted roads",
        is_visible=True,
        transparency=None,
        legend=False,
        style_parent_id=164,
    )

    with pytest.raises(ResourcePermissionError) as error_info:
        importer._QgisResourceBatchImporter__collect_params_for_webmap_layer(
            _webmap(),
            webmap_layer,
        )

    error = error_info.value
    assert "Restricted roads" in error.user_message
    assert "164" in (error.detail or "")
    assert "Restricted roads" in error.log_message


def test_batch_import_can_be_cancelled_before_execution(qgis_app) -> None:
    del qgis_app

    importer = QgisResourceBatchImporter(
        _ResourceModelProbe(),
        [],
        _insertion_point(),
        interaction_module.QgisResourceImportInteraction(lambda text: text),
    )

    importer.cancel()
    result = importer.execute()

    assert result.status == ResourceBatchImportStatus.CANCELLED
    assert result.added_layer_ids == ()


def test_webmap_missing_resources_ignores_forbidden_ids(qgis_app) -> None:
    del qgis_app

    model = _ResourceModelProbe()
    model.forbidden_resource_ids.add(164)
    webmap = mock.Mock(spec=NGWWebMap)
    webmap.all_resources_id = [164]
    index = mock.Mock()
    index.data.return_value = webmap

    resource_ids = ResourceDependencyAnalyzer(model).missing_resource_ids(
        [index]
    )

    assert resource_ids == ()


def test_batch_adding_error_dialog_can_skip_and_apply_to_all(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    _FakeMessageBox.instances = []
    monkeypatch.setattr(interaction_module, "QMessageBox", _FakeMessageBox)
    monkeypatch.setattr(interaction_module, "QCheckBox", _FakeCheckBox)

    model = _ResourceModelProbe()
    importer = QgisResourceBatchImporter(
        model,
        [],
        _insertion_point(),
        interaction_module.QgisResourceImportInteraction(lambda text: text),
    )
    importer._QgisResourceBatchImporter__is_mass_adding = True
    context = ResourceAddingErrorContext(
        display_name="Restricted roads",
        insertion_id=123,
        resource_ids=(164,),
        resource_url="https://example.nextgis.com/resource/164",
    )

    is_skipped = importer._QgisResourceBatchImporter__skip_after_adding_error(
        ResourcePermissionError(user_message="No access"),
        context,
    )

    assert is_skipped is True
    interaction = importer._QgisResourceBatchImporter__interaction
    assert interaction.applies_to_future_errors is True
    assert 123 in importer._QgisResourceBatchImporter__skipped_resources
    assert 164 in importer._QgisResourceBatchImporter__skipped_resources
    assert len(_FakeMessageBox.instances) == 1
    assert "Restricted roads" in _FakeMessageBox.instances[0].text
    assert _FakeMessageBox.instances[0].checkbox.text == "Apply to all"
    assert (
        _FakeMessageBox.instances[0]
        .buttons[QMessageBox.StandardButton.Ignore]
        .text
        == "Skip"
    )
    assert (
        _FakeMessageBox.instances[0]
        .buttons[QMessageBox.StandardButton.Cancel]
        .text
        == "Cancel"
    )

    second_context = ResourceAddingErrorContext(
        display_name="Restricted buildings",
        insertion_id=124,
        resource_ids=(165,),
    )
    is_second_skipped = (
        importer._QgisResourceBatchImporter__skip_after_adding_error(
            RuntimeError("Second error"),
            second_context,
        )
    )

    assert is_second_skipped is True
    assert 124 in importer._QgisResourceBatchImporter__skipped_resources
    assert 165 in importer._QgisResourceBatchImporter__skipped_resources
    assert len(_FakeMessageBox.instances) == 1


class _CancelledStyleDialog:
    DialogCode = interaction_module.NGWLayerStyleChooserDialog.DialogCode

    def __init__(self, title, index, resource_model) -> None:
        del title
        del index
        del resource_model

    def exec(self):
        return self.DialogCode.Rejected

    def selectedStyleIndex(self):
        return None


def test_select_default_style_cancel_raises_import_cancellation(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app
    monkeypatch.setattr(
        interaction_module,
        "NGWLayerStyleChooserDialog",
        _CancelledStyleDialog,
    )

    interaction = interaction_module.QgisResourceImportInteraction(
        lambda text: text
    )

    with pytest.raises(ResourceImportCancelledError):
        interaction.select_default_style(
            "Select style", mock.Mock(), mock.Mock()
        )


def test_batch_import_uses_parent_layer_container_for_style_download_check(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    expected_path = mock.Mock()
    expected_path.exists.return_value = True
    captured_resource_ids = []

    storage_service = mock.Mock()

    def fake_container_path(domain_uuid: str, resource_id: int):
        del domain_uuid
        captured_resource_ids.append(resource_id)
        return expected_path

    storage_service.container_path.side_effect = fake_container_path

    from nextgis_connect.legacy.tree_widget import model as tree_model_module

    class _FakeStyle:
        def __init__(self) -> None:
            self.connection_id = "connection-id"
            self.resource_id = 3065

    class _FakeLayer:
        def __init__(self) -> None:
            self.resource_id = 3064

    monkeypatch.setattr(tree_model_module, "NGWQGISVectorStyle", _FakeStyle)
    monkeypatch.setattr(tree_model_module, "NGWVectorLayer", _FakeLayer)

    monkeypatch.setattr(
        tree_model_module.DetachedStorageServiceFactory,
        "create",
        mock.Mock(return_value=storage_service),
    )

    connections_manager = mock.Mock()
    connections_manager.connection.return_value = mock.Mock(
        domain_uuid="domain-uuid"
    )
    monkeypatch.setattr(
        tree_model_module,
        "NgwConnectionsManager",
        mock.Mock(return_value=connections_manager),
    )

    style_resource = _FakeStyle()
    parent_resource = _FakeLayer()

    parent_index = mock.Mock()
    parent_index.data.return_value = parent_resource

    style_index = mock.Mock()
    style_index.data.return_value = style_resource
    style_index.parent.return_value = parent_index

    tree_model = tree_model_module.QNGWResourceTreeModel.__new__(
        tree_model_module.QNGWResourceTreeModel
    )
    tree_model.rowCount = mock.Mock(return_value=0)

    response = tree_model_module.QNGWResourceTreeModel.download_vector_layers_if_needed(
        tree_model,
        [style_index],
    )

    assert response is None
    assert captured_resource_ids == [3064]
    style_index.data.assert_called_with(QNGWResourceItem.NGWResourceRole)
    parent_index.data.assert_called_with(QNGWResourceItem.NGWResourceRole)


def test_style_filter_keeps_layer_root_visible_through_filtered_groups(
    qgis_app,
    monkeypatch,
) -> None:
    del qgis_app

    from nextgis_connect.legacy import dialog_choose_style as dialog_module

    class _FakeStyle:
        pass

    monkeypatch.setattr(dialog_module, "NGWQGISStyle", _FakeStyle)

    model = QStandardItemModel()
    group_item = QStandardItem("group")
    layer_item = QStandardItem("layer")
    style_item = QStandardItem("style")
    style_item.setData(_FakeStyle(), QNGWResourceItem.NGWResourceRole)

    layer_item.appendRow(style_item)
    group_item.appendRow(layer_item)
    model.invisibleRootItem().appendRow(group_item)

    proxy_model = StyleFilterProxyModel()
    proxy_model.setSourceModel(model)
    proxy_model.setRecursiveFilteringEnabled(True)

    source_layer_index = model.indexFromItem(layer_item)
    proxy_layer_index = proxy_model.mapFromSource(source_layer_index)

    assert proxy_layer_index.isValid() is True
    assert proxy_model.rowCount(proxy_layer_index) == 1
