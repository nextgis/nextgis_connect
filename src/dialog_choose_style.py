from PyQt4.QtGui import *
from PyQt4.QtCore import *


class Filter(QSortFilterProxyModel):
    def __init__(self, parent):
        QSortFilterProxyModel.__init__(self, parent)


class NGWResourcesTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        QTreeView.__init__(self, parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.header().setStretchLastSection(False)
        self.header().setResizeMode(QHeaderView.ResizeToContents)


class DialogWebMapCreation(QDialog):
    def __init__(self, ngw_resources_model_index, model, parent=None):
        """
        """
        super(QDialog, self).__init__(parent)

        self.setWindowTitle(
            self.tr("Create Web Map for layer")
        )

        self.layout = QVBoxLayout(self)

        self.chbCreateNewStyle = QCheckBox(self.tr("Create new style"), self)
        self.chbCreateNewStyle.stateChanged.connect(self.setCreatingNewStyle)
        self.chbCreateNewStyle.clicked.connect(self.validate)
        self.layout.addWidget(
            self.chbCreateNewStyle
        )

        self.layout.addWidget(
            QLabel(self.tr("Or select layer style:"))
        )

        self.tree = NGWResourcesTreeView(self)

        fmodel = Filter(self)
        fmodel.setSourceModel(model)

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

    def needCreateNewStyle(self):
        return self.chbCreateNewStyle.checkState() == Qt.Checked

    def selectedStyle(self):
        selected_index = self.tree.selectionModel().currentIndex()

        if not selected_index.isValid():
            return None

        item = selected_index.internalPointer()

        return item.ngw_resource_id()

    def validate(self):
        if self.chbCreateNewStyle.checkState() == Qt.Checked:
            self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)
            return

        if self.tree.selectionModel().currentIndex().isValid():
            self.btn_box.button(QDialogButtonBox.Ok).setEnabled(True)
            return

        self.btn_box.button(QDialogButtonBox.Ok).setEnabled(False)
