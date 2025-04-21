import json
from pathlib import Path

from qgis.gui import QgsCodeEditorJson
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QTabWidget,
)

from nextgis_connect.ngw_api.core.ngw_resource import NGWResource
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings


class ResourcePropertiesDialog(QDialog):
    tab_widget: QTabWidget
    json_editor: QgsCodeEditorJson
    resource_icon: QLabel
    info_layout: QFormLayout
    button_box: QDialogButtonBox

    def __init__(self, resource: NGWResource, parent=None):
        super().__init__(parent)

        ui_file = Path(__file__).parent / "resource_properties_dialog_base.ui"
        uic.loadUi(str(ui_file), self)
        self.tab_widget.setCurrentIndex(0)

        self.__resource = resource

        self.progress_bar.hide()
        self.external_access_group.hide()
        self.json_editor.setReadOnly(True)
        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).setDisabled(True)

        icon = QIcon(resource.icon_path)
        pixmap = icon.pixmap(icon.actualSize(QSize(32, 32)))
        self.resource_icon.setPixmap(pixmap)

        index = self.tab_widget.indexOf(self.json_tab)
        self.tab_widget.setTabVisible(
            index, NgConnectSettings().is_developer_mode
        )
        self.tab_widget.setTabVisible(
            self.tab_widget.indexOf(self.description_tab), False
        )
        self.tab_widget.setTabVisible(
            self.tab_widget.indexOf(self.metadata_tab), False
        )

        self.resource_name_label.setText(f"<h2>{resource.display_name}</h2>")

        add_icon = QIcon(":images/themes/default/mActionEditPaste.svg")
        copy_icon = QIcon(":images/themes/default/mActionEditCopy.svg")

        self.add_toolbutton.setIcon(add_icon)
        self.add_toolbutton.setIconSize(QSize(23, 23))
        self.add_toolbutton.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )

        self.copy_toolbutton.setIcon(copy_icon)
        self.copy_toolbutton.setIconSize(QSize(23, 23))
        self.copy_toolbutton.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )

        self.__fill_information()
        self.__fill_json()

    def __fill_information(self) -> None:
        fields = [("Resource id", "resource_id")]
        for field_name, field in fields:
            row_count = self.info_layout.rowCount()

            self.info_layout.setWidget(
                row_count,
                QFormLayout.ItemRole.LabelRole,
                QLabel(field_name),
            )
            self.info_layout.setWidget(
                row_count,
                QFormLayout.ItemRole.FieldRole,
                QLabel(str(self.__resource.__getattribute__(field))),
            )

    def __fill_json(self) -> None:
        self.json_editor.setText(json.dumps(self.__resource._json, indent=2))
