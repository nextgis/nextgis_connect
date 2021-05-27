from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtCore import *

from .ngw_api.qgis.compat_qgis import CompatQt


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


class NGWLayerStyleChooserDialog(QDialog):
    def __init__(self, title, ngw_resources_model_index, model, parent=None):
        """
        """
        super(QDialog, self).__init__(parent)

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

        self.layout.addWidget(
            QLabel(self.tr("Or select layer style:"))
        )

        self.tree = NGWResourcesTreeView(self)

        self.tree.setModel(model)
        self.tree.setRootIndex(ngw_resources_model_index)
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

    def setCreatingNewStyle(self, state):
        self.tree.setDisabled(state == Qt.Checked)

    # def needCreateNewStyle(self):
    #     return self.chbCreateNewStyle.checkState() == Qt.Checked

    def selectedStyle(self):
        selected_index = self.tree.selectionModel().currentIndex()

        if not selected_index.isValid():
            return None

        item = selected_index.internalPointer()

        return item.ngw_resource_id()

    def validate(self):
        # if self.chbCreateNewStyle.checkState() == Qt.Checked:
        #     self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)
        #     return

        if self.tree.selectionModel().currentIndex().isValid():
            self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)
            return

        self.btn_box.button(QDialogButtonBox.Ok).setEnabled(False)
