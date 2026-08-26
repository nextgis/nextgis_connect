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

from unittest import mock

from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_import import (
    QgisResourceBatchImporter,
)
from nextgis_connect.legacy.ngw.core.ngw_webmap import NGWWebMapGroup
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem


def _create_importer() -> QgisResourceBatchImporter:
    importer = QgisResourceBatchImporter.__new__(QgisResourceBatchImporter)
    importer._QgisResourceBatchImporter__skipped_resources = set()
    importer._QgisResourceBatchImporter__insert_group = mock.Mock()
    importer._QgisResourceBatchImporter__add_service_layer = mock.Mock()
    return importer


def _create_service_index(service_resource: mock.Mock) -> mock.Mock:
    service_index = mock.Mock()
    service_index.data.return_value = service_resource
    return service_index


def test_add_service_with_single_layer_does_not_create_group() -> None:
    layer = mock.Mock()
    service_resource = mock.Mock()
    service_resource.layers = [layer]

    importer = _create_importer()
    service_index = _create_service_index(service_resource)

    importer._QgisResourceBatchImporter__add_service(service_index)

    importer._QgisResourceBatchImporter__insert_group.assert_not_called()
    importer._QgisResourceBatchImporter__add_service_layer.assert_called_once_with(
        service_resource, layer
    )
    service_index.data.assert_called_once_with(
        QNGWResourceItem.NGWResourceRole
    )


def test_add_service_with_multiple_layers_creates_group() -> None:
    first_layer = mock.Mock()
    second_layer = mock.Mock()
    service_resource = mock.Mock()
    service_resource.display_name = "WFS service"
    service_resource.layers = [first_layer, second_layer]

    importer = _create_importer()
    service_index = _create_service_index(service_resource)
    importer._QgisResourceBatchImporter__insertion_stack = [mock.Mock()]

    importer._QgisResourceBatchImporter__add_service(service_index)

    importer._QgisResourceBatchImporter__insert_group.assert_called_once_with(
        service_resource.display_name
    )
    importer._QgisResourceBatchImporter__add_service_layer.assert_has_calls(
        [
            mock.call(service_resource, first_layer),
            mock.call(service_resource, second_layer),
        ]
    )


def test_add_service_with_one_available_layer_does_not_create_group() -> None:
    skipped_layer = mock.Mock()
    added_layer = mock.Mock()
    service_resource = mock.Mock()
    service_resource.layers = [skipped_layer, added_layer]

    importer = _create_importer()
    importer._QgisResourceBatchImporter__skipped_resources = {
        id(skipped_layer)
    }
    service_index = _create_service_index(service_resource)

    importer._QgisResourceBatchImporter__add_service(service_index)

    importer._QgisResourceBatchImporter__insert_group.assert_not_called()
    importer._QgisResourceBatchImporter__add_service_layer.assert_called_once_with(
        service_resource, added_layer
    )


def test_add_webmap_group_applies_group_visibility() -> None:
    webmap_group = NGWWebMapGroup("Hidden group", is_visible=False)
    qgs_group = mock.Mock()
    group_insertion_point = mock.Mock()
    group_insertion_point.position = 1
    importer = QgisResourceBatchImporter.__new__(QgisResourceBatchImporter)
    importer._QgisResourceBatchImporter__insert_group = mock.Mock(
        return_value=qgs_group
    )
    importer._QgisResourceBatchImporter__insertion_stack = [
        mock.Mock(),
        group_insertion_point,
    ]

    importer._QgisResourceBatchImporter__add_webmap_group(
        mock.Mock(), webmap_group
    )

    qgs_group.setItemVisibilityChecked.assert_called_once_with(False)


def test_add_layer_from_style_appends_style_name() -> None:
    importer = _create_importer()
    layer = mock.Mock()
    layer.name.return_value = "Roads"
    layer_node = mock.Mock()
    layer_node.layer.return_value = layer
    importer._QgisResourceBatchImporter__add_layer = mock.Mock(
        return_value=layer_node
    )
    style_resource = mock.Mock()
    style_resource.display_name = "Night"
    style_index = _create_service_index(style_resource)

    importer._QgisResourceBatchImporter__add_layer_from_style(style_index)

    layer.styleManager().setCurrentStyle.assert_called_once_with("Night")
    layer.setName.assert_called_once_with("Roads — Night")


def test_add_layer_from_style_uses_style_name_when_it_includes_layer_name() -> (
    None
):
    importer = _create_importer()
    layer = mock.Mock()
    layer.name.return_value = "Roads"
    layer_node = mock.Mock()
    layer_node.layer.return_value = layer
    importer._QgisResourceBatchImporter__add_layer = mock.Mock(
        return_value=layer_node
    )
    style_resource = mock.Mock()
    style_resource.display_name = "Roads - Night"
    style_index = _create_service_index(style_resource)

    importer._QgisResourceBatchImporter__add_layer_from_style(style_index)

    layer.setName.assert_called_once_with("Roads - Night")
