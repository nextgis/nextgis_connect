from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QSizePolicy, QTreeView, QVBoxLayout,
)
from qgis.PyQt.QtCore import pyqtSignal, QSortFilterProxyModel, Qt

from .ngw_api.core.ngw_qgis_style import NGWQGISVectorStyle
from .ngw_api.core.ngw_qgis_style import NGWQGISRasterStyle
from .ngw_api.core.ngw_vector_layer import NGWVectorLayer
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
        return isinstance(ngw_resource, (
            NGWQGISVectorStyle, NGWQGISRasterStyle,
            NGWVectorLayer, NGWRasterLayer,  # must also be included here so styles could be displayed
        ))


class NGWLayerStyleChooserDialog(QDialog):

    def __init__(self, title, ngw_resources_model_index, model, filter_styles, parent=None):  # TODO: 4th param - parent?
        super().__init__(parent)

        self.setWindowTitle(title)

        self.layout = QVBoxLayout(self)

        self.tree = NGWResourcesTreeView(self)
        sort_model = StyleFilterProxyModel() # TODO: understand is it ok to leave this proxy model without parent? When it will be deleted?
        sort_model.setSourceModel(model)
        self.tree.setModel(sort_model)
        self.tree.setRootIndex(sort_model.mapFromSource(ngw_resources_model_index))
        self.tree.selectionModel().selectionChanged.connect(self.validate)
        self.layout.addWidget(self.tree)

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        self.btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.layout.addWidget(self.btn_box)

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
            index is not None and index.isValid())
