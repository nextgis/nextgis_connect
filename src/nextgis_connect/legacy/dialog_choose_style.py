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

from typing import Optional, Tuple, Type

from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QSizePolicy,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from nextgis_connect.legacy.ngw.core.ngw_qgis_style import (
    NGWQGISStyle,
)
from nextgis_connect.legacy.ngw.core.ngw_raster_layer import NGWRasterLayer
from nextgis_connect.legacy.ngw.core.ngw_raster_mosaic import NGWRasterMosaic
from nextgis_connect.legacy.ngw.core.ngw_raster_style import NGWRasterStyle
from nextgis_connect.legacy.ngw.core.ngw_resource import NGWResource
from nextgis_connect.legacy.tree_widget import QNGWResourceItem


class NGWResourcesTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(QModelIndex)

    def __init__(self, parent):
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def mouseDoubleClickEvent(self, e):
        index = self.indexAt(e.pos())
        if index.isValid():
            self.itemDoubleClicked.emit(index)

        super().mouseDoubleClickEvent(e)


class StyleFilterProxyModel(QSortFilterProxyModel):
    """Filter a resource tree to QGIS styles and their parent layers."""

    def style_type(self) -> Type[NGWResource]:
        """Return the resource type users may select in the dialog."""
        return NGWQGISStyle

    def resource_types(self) -> Tuple[Type[NGWResource], ...]:
        """Return the resource types retained in the filtered tree."""
        return (
            self.style_type(),
            NGWAbstractVectorResource,
            NGWRasterLayer,
        )

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:
        """Return whether a source-model row is visible in the style tree.

        :param source_row: Row in the source model to evaluate.
        :param source_parent: Source-model parent of the row.
        """
        index = self.sourceModel().index(source_row, 0, source_parent)
        if index is None or not index.isValid():
            return False
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        return isinstance(ngw_resource, self.resource_types())


class RasterMosaicStyleFilterProxyModel(StyleFilterProxyModel):
    """Filter a resource tree to raster mosaics and server raster styles."""

    def style_type(self) -> Type[NGWResource]:
        """Return the server-side style type used to render a mosaic."""
        return NGWRasterStyle

    def resource_types(self) -> Tuple[Type[NGWResource], ...]:
        """Return the mosaic resources retained in the filtered tree."""
        return (self.style_type(), NGWRasterMosaic)


class NGWLayerStyleChooserDialog(QDialog):
    """Select a style compatible with the root resource."""

    __sort_model: StyleFilterProxyModel
    __style_type: Type[NGWResource]

    def __init__(
        self,
        title: str,
        ngw_resources_model_index: QModelIndex,
        model: QAbstractItemModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        root_resource = ngw_resources_model_index.data(
            QNGWResourceItem.NGWResourceRole
        )
        proxy_model_class = (
            RasterMosaicStyleFilterProxyModel
            if isinstance(root_resource, NGWRasterMosaic)
            else StyleFilterProxyModel
        )
        self.__sort_model = proxy_model_class(self)
        self.__style_type = self.__sort_model.style_type()
        self.__sort_model.setSourceModel(model)
        self.__sort_model.setRecursiveFilteringEnabled(True)

        self.__layout = QVBoxLayout(self)
        self.tree = NGWResourcesTreeView(self)
        self.tree.setModel(self.__sort_model)
        self.tree.setRootIndex(
            self.__sort_model.mapFromSource(ngw_resources_model_index)
        )
        self.tree.selectionModel().selectionChanged.connect(self.validate)
        self.__layout.addWidget(self.tree)

        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.btn_box.button(
            QDialogButtonBox.StandardButton.Ok
        ).clicked.connect(self.accept)
        self.btn_box.button(
            QDialogButtonBox.StandardButton.Cancel
        ).clicked.connect(self.reject)
        self.__layout.addWidget(self.btn_box)

        self.tree.itemDoubleClicked.connect(self.accept)

        self.validate()

    def selectedStyleIndex(self) -> Optional[QModelIndex]:
        """Return the selected source-model index when it is a valid style."""
        proxy_index = self.tree.selectionModel().currentIndex()
        if proxy_index is None or not proxy_index.isValid():
            return None
        source_index = self.__sort_model.mapToSource(proxy_index)
        resource = source_index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(resource, self.__style_type):
            return None
        return source_index

    def selectedStyle(self):
        selected_index = self.selectedStyleIndex()
        if selected_index is None or not selected_index.isValid():
            return None
        return selected_index.internalPointer()

    def selectedStyleId(self):
        item = self.selectedStyle()
        if item is None:
            return None
        return item.ngw_resource_id()

    def validate(self) -> None:
        """Enable acceptance only when a selectable style is selected."""
        index = self.selectedStyleIndex()
        self.btn_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            index is not None and index.isValid()
        )
