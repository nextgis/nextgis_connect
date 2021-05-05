from qgis.PyQt.QtCore import *
from qgis.PyQt.QtWidgets import *

from qgis.core import *
from qgis.gui import *
from qgis.utils import iface

from .ngw_api.qgis.compat_qgis import CompatQgis, CompatQgisMsgLogLevel, CompatQgisMsgBarLevel, CompatQgisGeometryType

def show_error_message(msg):
    iface.messageBar().pushMessage(
        'NextGIS Connect',
        msg,
        level=CompatQgisMsgBarLevel.Critical
    )

# def add_wfs_layer(wfs_url, layer_keys, ask_choose_layers=False):
    # toc_root = QgsProject.instance().layerTreeRoot()
 #    layers_group = toc_root.insertGroup(0, )


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

    CompatQgis.layers_registry().addMapLayer(rlayer)


class ChooserDialog(QDialog):
    """docstring for ChooserDialog"""
    def __init__(self, options):
        super(ChooserDialog, self).__init__()
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
        super(ChooserDialog, self).accept()
