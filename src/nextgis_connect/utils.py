import platform
from enum import Enum, auto
from functools import lru_cache
from itertools import islice
from typing import Tuple, Union, cast

from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QByteArray, QMimeData, Qt, QUrl
from qgis.PyQt.QtGui import QClipboard, QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)
from qgis.utils import iface

from nextgis_connect.exceptions import NgConnectError
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_connection.ngw_connection import NgwConnection
from nextgis_connect.settings import NgConnectSettings

iface = cast(QgisInterface, iface)


class SupportStatus(Enum):
    OLD_NGW = auto()
    OLD_CONNECT = auto()
    SUPPORTED = auto()


def add_wms_layer(
    name,
    url,
    layer_keys,
    connection: NgwConnection,
    *,
    ask_choose_layers=False,
):
    if ask_choose_layers:
        layersChooser = ChooserDialog(layer_keys)
        result = layersChooser.exec_()
        if result != ChooserDialog.DialogCode.Accepted:
            return
        layer_keys = layersChooser.seleced_options

    provider_regstry = QgsProviderRegistry.instance()
    assert provider_regstry is not None
    wms_metadata = provider_regstry.providerMetadata("wms")
    assert wms_metadata is not None
    uri_params = {
        "url": url,
        "format": "image/png",
        "crs": "EPSG:3857",
        "layers": ",".join(layer_keys),
        "styles": "",
    }
    if url.startswith(connection.url):
        uri_params["authcfg"] = connection.auth_config_id
    uri = wms_metadata.encodeUri(uri_params)

    rlayer = QgsRasterLayer(uri, name, "wms")
    if not rlayer.isValid():
        message = QgsApplication.translate(
            "Utils", 'Invalid wms url for layer "{name}"'
        ).format(uri=uri, name=name)

        error = NgConnectError("WMS error", user_message=message)
        error.add_note(f"Url: {uri}")

        NgConnectInterface.instance().show_error(error)
        return

    project = QgsProject.instance()
    assert project is not None
    project.addMapLayer(rlayer)


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
    clipboard.setMimeData(mime_data, QClipboard.Mode.Clipboard)


@lru_cache(maxsize=128)
def is_version_supported(current_version_string: str) -> SupportStatus:
    def version_to_tuple(version: str) -> Tuple[int, int]:
        minor, major = islice(map(int, version.split(".")), 2)
        return minor, major

    def version_shift(version: Tuple[int, int], shift: int) -> Tuple[int, int]:
        version_number = version[0] * 10 + version[1]
        shifted_version = version_number + shift
        return shifted_version // 10, shifted_version % 10

    current_version = version_to_tuple(current_version_string)

    supported_version_string = NgConnectSettings().supported_ngw_version
    supported_version = version_to_tuple(supported_version_string)

    oldest_version = version_shift(supported_version, -2)
    newest_version = version_shift(supported_version, 1)

    if current_version < oldest_version:
        return SupportStatus.OLD_NGW

    if current_version > newest_version:
        return SupportStatus.OLD_CONNECT

    return SupportStatus.SUPPORTED
