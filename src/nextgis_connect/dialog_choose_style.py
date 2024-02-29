from typing import Optional

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

from .ngw_api.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from .ngw_api.core.ngw_qgis_style import NGWQGISRasterStyle, NGWQGISVectorStyle
from .ngw_api.core.ngw_raster_layer import NGWRasterLayer
from .tree_widget import QNGWResourceItem


class NGWResourcesTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)


class StyleFilterProxyModel(QSortFilterProxyModel):
    def filterAcceptsRow(self, sourceRow, sourceParent):
        index = self.sourceModel().index(sourceRow, 0, sourceParent)
        if index is None or not index.isValid():
            return False
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        return isinstance(
            ngw_resource,
            (
                NGWQGISVectorStyle,
                NGWQGISRasterStyle,
                NGWAbstractVectorResource,
                NGWRasterLayer,  # must also be included here so styles could be displayed
            ),
        )


class NGWLayerStyleChooserDialog(QDialog):
    def __init__(
        self,
        title: str,
        ngw_resources_model_index: QModelIndex,
        model: QAbstractItemModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        self.__sort_model = StyleFilterProxyModel(self)
        self.__sort_model.setSourceModel(model)

        self.__layout = QVBoxLayout(self)
        self.tree = NGWResourcesTreeView(self)
        self.tree.setModel(self.__sort_model)
        self.tree.setRootIndex(
            self.__sort_model.mapFromSource(ngw_resources_model_index)
        )
        self.tree.selectionModel().selectionChanged.connect(self.validate)
        self.__layout.addWidget(self.tree)

        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok, Qt.Orientation.Horizontal, self
        )
        self.btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.__layout.addWidget(self.btn_box)

        self.validate()

    def selectedStyleIndex(self):
        proxy_index = self.tree.selectionModel().currentIndex()
        if proxy_index is None or not proxy_index.isValid():
            return None
        return self.tree.model().mapToSource(proxy_index)

    def selectedStyle(self):
        selected_index = self.selectedStyleIndex()
        if selected_index is None or not selected_index.isValid():
            return None
        item = selected_index.internalPointer()
        return item

    def selectedStyleId(self):
        item = self.selectedStyle()
        if item is None:
            return None
        return item.ngw_resource_id()

    def validate(self):
        index = self.selectedStyleIndex()
        self.btn_box.button(QDialogButtonBox.Ok).setEnabled(
            index is not None and index.isValid()
        )
