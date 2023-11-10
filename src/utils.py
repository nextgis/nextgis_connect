import platform
from typing import Union, cast

from qgis.PyQt.QtCore import Qt, QUrl, QByteArray, QMimeData
from qgis.PyQt.QtGui import QDesktopServices, QClipboard
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QVBoxLayout,
)

from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsMessageLog, QgsRasterLayer
)
from qgis.gui import QgisInterface
from qgis.utils import iface

iface = cast(QgisInterface, iface)

PLUGIN_NAME = 'NextGIS Connect'


def log_to_qgis(
    message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Info
) -> None:
    QgsMessageLog.logMessage(message, tag=PLUGIN_NAME, level=level)


def show_error_message(msg):
    iface.messageBar().pushMessage(
        PLUGIN_NAME,
        msg,
        level=Qgis.MessageLevel.Critical
    )


def add_wms_layer(name, url, layer_keys, ask_choose_layers=False):
    url = "url=%s" % url

    if ask_choose_layers:
        layersChooser = ChooserDialog(layer_keys)
        result = layersChooser.exec_()
        if result == ChooserDialog.Accepted:
            layer_keys = layersChooser.seleced_options
        else:
            return

    for layer_key in layer_keys:
        url += "&layers=%s&styles=" % layer_key

    url += "&format=image/png&crs=EPSG:3857"

    rlayer = QgsRasterLayer(url, name, 'wms')

    if not rlayer.isValid():
        show_error_message("Invalid wms url \"%s\"" % url)
        return

    QgsProject.instance().addMapLayer(rlayer)


class ChooserDialog(QDialog):
    def __init__(self, options):
        super().__init__()
        self.options = options

        self.setLayout(QVBoxLayout())

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.MultiSelection)
        self.list.setSelectionBehavior(QListWidget.SelectItems)
        self.layout().addWidget(self.list)

        for option in options:
            item = QListWidgetItem(option)
            self.list.addItem(item)

        self.list.setCurrentRow(0)

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Ok, Qt.Horizontal, self)
        self.btn_box.button(QDialogButtonBox.Ok).clicked.connect(self.accept)
        self.layout().addWidget(
            self.btn_box
        )

        self.seleced_options = []

    def accept(self):
        self.seleced_options = [item.text() for item in self.list.selectedItems()]
        super().accept()


def open_plugin_help():
    QDesktopServices.openUrl(
        QUrl('https://docs.nextgis.com/docs_ngconnect/source/toc.html')
    )


def set_clipboard_data(
    mime_type: str,
    data: Union[QByteArray, bytes, bytearray],
    text: str
):
    mime_data = QMimeData()
    mime_data.setData(mime_type, data)
    if len(text) > 0:
        mime_data.setText(text)
    if platform.system() == 'Linux':
        selection_mode = QClipboard.Mode.Selection
        QgsApplication.clipboard().setMimeData(mime_data, selection_mode)
    QgsApplication.clipboard().setMimeData(
        mime_data, QClipboard.Mode.Clipboard
    )
