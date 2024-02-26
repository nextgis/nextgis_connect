import platform
from typing import Union, cast, Tuple
from itertools import islice
from functools import lru_cache

from qgis.PyQt.QtCore import Qt, QUrl, QByteArray, QMimeData
from qgis.PyQt.QtGui import QDesktopServices, QClipboard
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProject,
    QgsMessageLog,
    QgsRasterLayer,
)
from qgis.gui import QgisInterface
from qgis.utils import iface

iface = cast(QgisInterface, iface)

PLUGIN_NAME = "NextGIS Connect"


def log_to_qgis(
    message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Info
) -> None:
    QgsMessageLog.logMessage(message, tag=PLUGIN_NAME, level=level)


def show_error_message(msg):
    iface.messageBar().pushMessage(
        PLUGIN_NAME, msg, level=Qgis.MessageLevel.Critical
    )


def add_wms_layer(name, url, layer_keys, creds, *, ask_choose_layers=False):
    url = f"url={url}"

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

    if creds[0] and creds[1]:
        url += f"&username={creds[0]}&password={creds[1]}"

    rlayer = QgsRasterLayer(url, name, "wms")

    if not rlayer.isValid():
        show_error_message('Invalid wms url "%s"' % url)
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

        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok, Qt.Horizontal, self
        )
        ok_button = self.btn_box.button(QDialogButtonBox.Ok)
        assert ok_button is not None
        ok_button.clicked.connect(self.accept)
        self.layout().addWidget(self.btn_box)

        self.seleced_options = []

    def accept(self):
        self.seleced_options = [
            item.text() for item in self.list.selectedItems()
        ]
        super().accept()


def open_plugin_help():
    QDesktopServices.openUrl(
        QUrl("https://docs.nextgis.com/docs_ngconnect/source/toc.html")
    )


def set_clipboard_data(
    mime_type: str, data: Union[QByteArray, bytes, bytearray], text: str
):
    mime_data = QMimeData()
    mime_data.setData(mime_type, data)
    if len(text) > 0:
        mime_data.setText(text)

    clipboard = QgsApplication.clipboard()
    assert clipboard is not None
    if platform.system() == "Linux":
        selection_mode = QClipboard.Mode.Selection
        clipboard.setMimeData(mime_data, selection_mode)
    clipboard.setMimeData(
        mime_data, QClipboard.Mode.Clipboard
    )


@lru_cache
def is_version_supported(current_version: str, supported_version: str) -> bool:
    def version_to_tuple(version: str) -> Tuple[int, int]:
        minor, major = islice(map(int, version.split(".")), 2)
        return minor, major

    def version_shift(version: Tuple[int, int], shift: int) -> Tuple[int, int]:
        version_number = version[0] * 10 + version[1]
        shifted_version = version_number + shift
        return shifted_version // 10, shifted_version % 10

    current = version_to_tuple(current_version)
    supported = version_to_tuple(supported_version)
    all_supported = (
        version_shift(supported, -2),
        version_shift(supported, -1),
        supported,
        version_shift(supported, 1),
    )

    return current in all_supported
