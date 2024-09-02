import platform
from enum import Enum, auto
from itertools import islice
from typing import Optional, Tuple, Union, cast

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

from nextgis_connect.exceptions import ErrorCode, NgConnectError, NgwError
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_connection.ngw_connection import NgwConnection
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings

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
    resource_id=None,
) -> Optional[QgsRasterLayer]:
    if len(layer_keys) == 0:
        user_message = QgsApplication.translate(
            "Utils", "The WMS service does not contain any layers"
        )
        raise NgwError(
            "Layers list is empty",
            user_message=user_message,
            code=ErrorCode.InvalidResource,
        )

    if ask_choose_layers:
        layersChooser = ChooserDialog(layer_keys)
        result = layersChooser.exec()
        if result != ChooserDialog.DialogCode.Accepted:
            return
        layer_keys = layersChooser.seleced_options

    provider_regstry = QgsProviderRegistry.instance()
    assert provider_regstry is not None
    wms_metadata = provider_regstry.providerMetadata("wms")
    assert wms_metadata is not None
    uri_params = {
        "format": "image/png",
        "crs": "EPSG:3857",
        "url": url,
    }
    if url.startswith(connection.url):
        uri_params["authcfg"] = connection.auth_config_id

    uri = wms_metadata.encodeUri(uri_params)

    for layer in layer_keys:
        uri += f"&layers={layer}&styles="

    rlayer = QgsRasterLayer(uri, name, "wms")
    if not rlayer.isValid():
        message = QgsApplication.translate(
            "Utils", 'Invalid wms url for layer "{name}"'
        ).format(uri=uri, name=name)

        error = NgConnectError("WMS error", user_message=message)
        error.add_note(f"Url: {uri}")

        NgConnectInterface.instance().show_error(error)
        return None

    rlayer.setCustomProperty("ngw_connection_id", connection.id)
    rlayer.setCustomProperty("ngw_resource_id", resource_id)

    project = QgsProject.instance()
    assert project is not None
    project.addMapLayer(rlayer)

    return rlayer


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
            QDialogButtonBox.Ok, Qt.Orientation.Horizontal, self
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
    domain = "ru" if QgsApplication.instance().locale() == "ru" else "com"
    QDesktopServices.openUrl(
        QUrl(f"https://docs.nextgis.{domain}/docs_ngconnect/source/toc.html")
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


def is_version_supported(current_version_string: str) -> SupportStatus:
    def version_to_tuple(version: str) -> Tuple[int, int]:
        minor, major = islice(map(int, version.split(".")), 2)
        return minor, major

    def version_shift(version: Tuple[int, int], shift: int) -> Tuple[int, int]:
        version_number = version[0] * 10 + version[1]
        shifted_version = version_number + shift
        return shifted_version // 10, shifted_version % 10

    current_version = version_to_tuple(current_version_string)

    settings = NgConnectSettings()
    if settings.is_developer_mode:
        return SupportStatus.SUPPORTED

    supported_version_string = settings.supported_ngw_version
    supported_version = version_to_tuple(supported_version_string)

    oldest_version = version_shift(supported_version, -2)
    newest_version = version_shift(supported_version, 1)

    if current_version < oldest_version:
        return SupportStatus.OLD_NGW

    if current_version > newest_version:
        return SupportStatus.OLD_CONNECT

    return SupportStatus.SUPPORTED
