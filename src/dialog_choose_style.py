from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtCore import *

from .ngw_api.qgis.compat_qgis import CompatQt
from .ngw_api.qt.qt_ngw_resource_item import QNGWResourceItem
from .ngw_api.core.ngw_qgis_style import NGWQGISVectorStyle
from .ngw_api.core.ngw_qgis_style import NGWQGISRasterStyle
from .ngw_api.core.ngw_group_resource import NGWGroupResource
from .ngw_api.core.ngw_vector_layer import NGWVectorLayer
from .ngw_api.core.ngw_raster_layer import NGWRasterLayer

class NGWResourcesTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        QTreeView.__init__(self, parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.header().setStretchLastSection(False)
        CompatQt.set_section_resize_mod(self.header(), QHeaderView.ResizeToContents)


class StyleFilterProxyModel(QSortFilterProxyModel):

    def __init__(self, parent=None):
        super(StyleFilterProxyModel, self).__init__(parent)

    def filterAcceptsRow(self, sourceRow, sourceParent):
        index = self.sourceModel().index(sourceRow, 0, sourceParent)
        if index is None or not index.isValid():
            return False
        resource = index.data(QNGWResourceItem.NGWResourceRole)
        if resource is None:
            return False
        if (resource.type_id == NGWQGISVectorStyle.type_id or resource.type_id == NGWQGISRasterStyle.type_id
            or resource.type_id == NGWVectorLayer.type_id or resource.type_id == NGWRasterLayer.type_id): # must also be included here so styles could be displayed
            return True
        return False


class NGWLayerStyleChooserDialog(QDialog):

    def __init__(self, title, ngw_resources_model_index, model, filter_styles, parent=None):
        """
        """
        super(NGWLayerStyleChooserDialog, self).__init__(parent)

        self.setWindowTitle(
            title
        )

        self.layout = QVBoxLayout(self)

        # self.chbCreateNewStyle = QCheckBox(self.tr("Create new style"), self)
        # self.chbCreateNewStyle.stateChanged.connect(self.setCreatingNewStyle)
        # self.chbCreateNewStyle.clicked.connect(self.validate)
        # self.layout.addWidget(
        #     self.chbCreateNewStyle
        # )

        # self.layout.addWidget(
        #     QLabel(self.tr("Select layer style:"))
        # )

        self.tree = NGWResourcesTreeView(self)
        sort_model = StyleFilterProxyModel() # TODO: understand is it ok to leave this proxy model without parent? When it will be deleted?
        sort_model.setSourceModel(model)
        self.tree.setModel(sort_model)
        self.tree.setRootIndex(sort_model.mapFromSource(ngw_resources_model_index))
        self.tree.selectionModel().selectionChanged.connect(self.validate)
        self.layout.addWidget(
            self.tree
        )

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        self.btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.layout.addWidget(
            self.btn_box
        )

        self.validate()

    # def setCreatingNewStyle(self, state):
    #     self.tree.setDisabled(state == Qt.Checked)

    # def needCreateNewStyle(self):
    #     return self.chbCreateNewStyle.checkState() == Qt.Checked

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
        # if self.chbCreateNewStyle.checkState() == Qt.Checked:
        #     self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)
        #     return

        index = self.selectedStyleIndex()
        if index is None or not index.isValid():
            self.btn_box.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)



