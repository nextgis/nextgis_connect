from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout
from qgis.PyQt.QtCore import Qt


class DialogImportQGISProj(QDialog):
    def __init__(self, default_project_name, parent=None):
        super().__init__(parent)

        self.setWindowTitle(self.tr("Import parameters"))

        self.layout = QVBoxLayout(self)
        self.layout.addWidget(
            QLabel(self.tr("Project name"))
        )
        self.leProjectName = QLineEdit(default_project_name)
        self.layout.addWidget(
            self.leProjectName
        )

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.layout.addWidget(
            btn_box
        )

    def getProjName(self):
        return self.leProjectName.text()
