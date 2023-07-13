import os
from typing import Optional, List

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QMessageBox

from qgis.utils import iface
from qgis.core import Qgis, QgsMessageLog
from qgis.gui import (
    QgsOptionsPageWidget, QgsOptionsWidgetFactory
)

from .ng_connect_dock import NgConnectDock
from .plugin_settings import NgConnectSettings

from .ngw_api.utils import setDebugEnabled
from .ngw_api.qgis.ngw_connection_edit_dialog import NGWConnectionEditDialog
from .ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings


class NgConnectOptionsPageWidget(QgsOptionsPageWidget):
    """NextGIS Connect settings page"""

    widget: QWidget

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        pluginPath = os.path.dirname(__file__)
        self.widget = uic.loadUi(
            os.path.join(pluginPath, 'settings_dialog_base.ui')
        )  # type: ignore
        if self.widget is None:
            # TODO log
            return

        self.widget.setParent(self)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)
        self.setLayout(layout)
        layout.addWidget(self.widget)

        self.__init_settings()

    def apply(self) -> None:
        NgwPluginSettings.set_sanitize_rename_fields(
            self.widget.renameFieldsCheckBox.isChecked()
        )
        NgwPluginSettings.set_sanitize_fix_geometry(
            self.widget.fixGeometryCheckBox.isChecked()
        )

        settings = NgConnectSettings()
        settings.set_open_web_map_after_creation(
            self.widget.openWebMapAfterCreationCheckBox.isChecked()
        )
        settings.set_add_wfs_layer_after_service_creation(
            self.widget.addWfsLayerAfterServiceCreationCheckBox.isChecked()
        )
        NgwPluginSettings.set_upload_cog_rasters(
            self.widget.cogCheckBox.isChecked()
        )

        old_debug_enabled = settings.is_debug_enabled()
        new_debug_enabled = self.widget.debugEnabledCheckBox.isChecked()
        settings.set_debug_enabled(
            new_debug_enabled
        )
        if old_debug_enabled != new_debug_enabled:
            debug_state = 'enabled' if new_debug_enabled else 'disabled'
            QgsMessageLog.logMessage(
                f'Debug messages are now {debug_state}',
                tag='NextGIS Connect',
                level=Qgis.MessageLevel.Info
            )
            # TODO refactoring
            setDebugEnabled(new_debug_enabled)

        self.__save_connections()

    def cancel(self) -> None:
        self.__save_connections()

    def __init_settings(self) -> None:
        settings = NgConnectSettings()
        self.__init_connections(settings)
        self.__init_sanitize_settings(settings)
        self.__init_creation_settings(settings)
        self.__init_other_settings(settings)

    def __init_connections(self, settings: NgConnectSettings) -> None:
        # TODO This should be changed soon. Just moved old code
        self.__connections_were_changed = False
        self.widget.btnNew.clicked.connect(self.new_connection)
        self.widget.btnEdit.clicked.connect(self.edit_connection)
        self.widget.btnDelete.clicked.connect(self.delete_connection)
        self.populate_connection_list()

    def __init_sanitize_settings(self, settings: NgConnectSettings) -> None:
        self.widget.renameFieldsCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_rename_fields()
        )
        self.widget.fixGeometryCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_fix_geometry()
        )
        self.widget.fixGeometryCheckBox.hide()  # Rely on NGW

    def __init_creation_settings(self, settings: NgConnectSettings) -> None:
        self.widget.openWebMapAfterCreationCheckBox.setChecked(
            settings.open_web_map_after_creation()
        )
        self.widget.addWfsLayerAfterServiceCreationCheckBox.setChecked(
            settings.add_wfs_layer_after_service_creation()
        )

    def __init_other_settings(self, settings: NgConnectSettings) -> None:
        self.widget.cogCheckBox.setChecked(
            NgwPluginSettings.get_upload_cog_rasters()
        )
        self.widget.debugEnabledCheckBox.setChecked(
            settings.is_debug_enabled()
        )

    def new_connection(self):
        # TODO This should be changed soon. Just moved old code
        dlg = NGWConnectionEditDialog()
        if dlg.exec_():
            conn_sett = dlg.ngw_connection_settings
            NgwPluginSettings.save_ngw_connection(conn_sett)
            NgwPluginSettings.set_selected_ngw_connection_name(conn_sett.connection_name)
            self.populate_connection_list()
        del dlg
        self.__connections_were_changed = True

    def edit_connection(self):
        # TODO This should be changed soon. Just moved old code
        conn_name = self.widget.cmbConnections.currentText()
        conn_sett = None

        if conn_name is not None:
            conn_sett = NgwPluginSettings.get_ngw_connection(conn_name)

        dlg = NGWConnectionEditDialog(ngw_connection_settings=conn_sett)
        dlg.setWindowTitle(self.tr("Edit connection"))
        if dlg.exec_():
            new_conn_sett = dlg.ngw_connection_settings
            # if conn was renamed - remove old
            if conn_name is not None and conn_name != new_conn_sett.connection_name:
                NgwPluginSettings.remove_ngw_connection(conn_name)
            # save new
            NgwPluginSettings.save_ngw_connection(new_conn_sett)
            NgwPluginSettings.set_selected_ngw_connection_name(new_conn_sett.connection_name)

            self.populate_connection_list()
        del dlg
        self.__connections_were_changed = True

    def delete_connection(self):
        # TODO This should be changed soon. Just moved old code
        reply = QMessageBox.question(
            iface.mainWindow(),
            self.tr('Deletion confirmation'),
            self.tr('Are you sure you want to delete this connection?')
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        NgwPluginSettings.remove_ngw_connection(
            self.widget.cmbConnections.currentText()
        )
        self.populate_connection_list()
        self.__connections_were_changed = True

    def populate_connection_list(self):
        self.widget.cmbConnections.clear()
        self.widget.cmbConnections.addItems(
            NgwPluginSettings.get_ngw_connection_names()
        )

        last_connection = NgwPluginSettings.get_selected_ngw_connection_name()

        idx = self.widget.cmbConnections.findText(last_connection)
        if idx == -1 and self.widget.cmbConnections.count() > 0:
            self.widget.cmbConnections.setCurrentIndex(0)
        else:
            self.widget.cmbConnections.setCurrentIndex(idx)

        if self.widget.cmbConnections.count() == 0:
            self.widget.btnEdit.setEnabled(False)
            self.widget.btnDelete.setEnabled(False)
        else:
            self.widget.btnEdit.setEnabled(True)
            self.widget.btnDelete.setEnabled(True)

    def __save_connections(self):
        old_connection = NgwPluginSettings.get_selected_ngw_connection_name()
        new_connection = self.widget.cmbConnections.currentText()
        if self.__connections_were_changed or old_connection != new_connection:
            NgwPluginSettings.set_selected_ngw_connection_name(
                new_connection
            )
            dock = iface.mainWindow().findChild(NgConnectDock, 'NGConnectDock')
            dock.reinit_tree()


class NgConnectOptionsWidgetFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        super().__init__('NextGIS Connect', QIcon(), 'ngconnect')

    def icon(self) -> QIcon:
        ICONS_PATH = os.path.join(os.path.dirname(__file__), 'icons/')
        return QIcon(os.path.join(ICONS_PATH, 'logo.svg'))

    def path(self) -> List[str]:
        return ['NextGIS']

    def createWidget(
        self, parent: Optional[QWidget] = None
    ) -> QgsOptionsPageWidget:
        return NgConnectOptionsPageWidget(parent)
