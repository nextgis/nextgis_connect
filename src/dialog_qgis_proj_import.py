from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout
from qgis.PyQt.QtCore import Qt


class UploadQGISProjectDialog(QDialog):
    def __init__(self, default_project_name, parent=None):
        super().__init__(parent)

        self.setWindowTitle(self.tr("Import parameters"))

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(QLabel(self.tr("Resource group name:")))

        self.projectNameLineEdit = QLineEdit(default_project_name)
        self.layout.addWidget(self.projectNameLineEdit)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.layout.addWidget(btn_box)

        self._adjustSizeToContent()

    def projectName(self):
        return self.projectNameLineEdit.text()

    def _adjustSizeToContent(self):
        font_metrics = self.projectNameLineEdit.fontMetrics()
        extra_space = 40
        needed_width = font_metrics.width(self.projectName()) + extra_space
        self.projectNameLineEdit.setMinimumWidth(needed_width)
        self.adjustSize()
