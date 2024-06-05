import json
import os
from typing import cast

from nextgis_connect.ngw_api.core.ngw_resource import NGWResource
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from qgis.PyQt import QtWidgets, uic
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.Qsci import QsciLexerJSON, QsciScintilla
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QLabel, QToolButton
from qgis.core import QgsApplication

class LayerPropertyDialog(QtWidgets.QDialog):
    def __init__(self, resource: NGWResource, parent=None):
        super().__init__(parent)
        ui_file = os.path.join(os.path.dirname(__file__), "layer_property.ui")
        uic.loadUi(ui_file, self)

        self.json_field = cast(QsciScintilla, self.json_field)
        lexer = QsciLexerJSON()
        self.json_field.setLexer(lexer)
        self.json_field.setText(json.dumps(resource._json, indent=2))

        icon = QIcon(resource.icon_path)
        pixmap = icon.pixmap(icon.actualSize(QSize(23, 23)))
        cast(QLabel, self.layer_type_icon).setPixmap(pixmap)

        index = self.layer_property_tabs.indexOf(self.json_tab)
        self.layer_property_tabs.setTabVisible(
            index,
            NgConnectSettings().is_developer_mode
            )

        self.resource_name_label.setText(f"<h2>{resource.display_name}</h2>")

        add_icon = QIcon(":images/themes/default/mActionEditPaste.svg")
        copy_icon = QIcon(":images/themes/default/mActionEditCopy.svg")

        self.add_toolbutton.setIcon(add_icon)
        self.add_toolbutton.setIconSize(QSize(23, 23))
        self.add_toolbutton.setToolButtonStyle(Qt.ToolButtonIconOnly)

        self.copy_toolbutton.setIcon(copy_icon)
        self.copy_toolbutton.setIconSize(QSize(23, 23))
        self.copy_toolbutton.setToolButtonStyle(Qt.ToolButtonIconOnly)
