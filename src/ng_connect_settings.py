import os
from typing import Optional, List

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel
)

from qgis.utils import iface
from qgis.core import Qgis
from qgis.gui import (
    QgsOptionsPageWidget, QgsOptionsWidgetFactory
)

from .ng_connect_dock import NgConnectDock
from .plugin_settings import NgConnectSettings

from .ngw_api.utils import setDebugEnabled
from .ngw_api.qgis.ngw_plugin_settings import NgwPluginSettings

from .ngw_connection.ngw_connection import NgwConnection
from .ngw_connection.ngw_connections_manager import NgwConnectionsManager
from .ngw_connection.ngw_connections_widget import NgwConnectionsWidget

from . import utils


class NgConnectOptionsPageWidget(QgsOptionsPageWidget):
    """NextGIS Connect settings page"""

    __widget: QWidget
    __current_connection: Optional[NgwConnection]
    __connections: List[NgwConnection]
    __is_accepted: bool
    __is_cancelled: bool

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        plugin_path = os.path.dirname(__file__)
        widget: Optional[QWidget] = None
        try:
            widget = uic.loadUi(
                os.path.join(plugin_path, 'settings_dialog_base.ui')
            )  # type: ignore
        except FileNotFoundError:
            message = self.tr("Can't load settings UI")
            utils.log_to_qgis(message, Qgis.MessageLevel.Critical)
            raise RuntimeError(message)
        if widget is None:
            message = self.tr("Errors in settings UI")
            utils.log_to_qgis(message, Qgis.MessageLevel.Critical)
            raise RuntimeError(message)

        self.__widget = widget
        self.__widget.setParent(self)

        self.connections_widget = NgwConnectionsWidget(self.__widget)
        self.__widget.connectionsGroupBox.layout().addWidget(
            self.connections_widget
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setMargin(0)  # type: ignore
        self.setLayout(layout)
        layout.addWidget(self.__widget)

        self.__init_settings()

    def apply(self) -> None:
        self.__is_accepted = True

        settings = NgConnectSettings()

        # Connections settings
        self.__save_current_connection()

        # Sanitize settings
        NgwPluginSettings.set_sanitize_rename_fields(
            self.__widget.renameFieldsCheckBox.isChecked()
        )
        NgwPluginSettings.set_sanitize_fix_geometry(
            self.__widget.fixGeometryCheckBox.isChecked()
        )

        # Creation settings
        settings.open_web_map_after_creation = \
            self.__widget.openWebMapAfterCreationCheckBox.isChecked()
        settings.add_layer_after_service_creation = \
            self.__widget.addWfsLayerAfterServiceCreationCheckBox.isChecked()

        # Other settings
        NgwPluginSettings.set_upload_cog_rasters(
            self.__widget.cogCheckBox.isChecked()
        )
        old_debug_enabled = settings.is_debug_enabled
        new_debug_enabled = self.__widget.debugEnabledCheckBox.isChecked()
        settings.is_debug_enabled = new_debug_enabled
        if old_debug_enabled != new_debug_enabled:
            debug_state = 'enabled' if new_debug_enabled else 'disabled'
            utils.log_to_qgis(f'Debug messages are now {debug_state}')
            # TODO refactoring
            setDebugEnabled(new_debug_enabled)

    def __del__(self):
        # Workaround
        if not self.__is_accepted and not self.__is_cancelled:
            self.cancel()

    def cancel(self) -> None:
        self.__is_cancelled = True
        connections_manager = NgwConnectionsManager()
        current_connections = connections_manager.connections()

        # Remove new
        delta = set(current_connections) - set(self.__connections)
        for connection in delta:
            connections_manager.remove(connection.id)

        # Restore old
        for connection in self.__connections:
            connections_manager.save(connection)

    def __init_settings(self) -> None:
        settings = NgConnectSettings()
        self.__is_accepted = False
        self.__is_cancelled = False
        self.__init_connections(settings)
        self.__init_sanitize_settings(settings)
        self.__init_creation_settings(settings)
        self.__init_other_settings(settings)

    def __init_connections(self, settings: NgConnectSettings) -> None:
        connections_manager = NgwConnectionsManager()
        self.__current_connection = connections_manager.current_connection
        self.__connections = connections_manager.connections()

    def __init_sanitize_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.renameFieldsCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_rename_fields()
        )
        self.__widget.fixGeometryCheckBox.setChecked(
            NgwPluginSettings.get_sanitize_fix_geometry()
        )
        self.__widget.fixGeometryCheckBox.hide()  # Rely on NGW

    def __init_creation_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.openWebMapAfterCreationCheckBox.setChecked(
            settings.open_web_map_after_creation
        )
        self.__widget.addWfsLayerAfterServiceCreationCheckBox.setChecked(
            settings.add_layer_after_service_creation
        )

    def __init_other_settings(self, settings: NgConnectSettings) -> None:
        self.__widget.cogCheckBox.setChecked(
            NgwPluginSettings.get_upload_cog_rasters()
        )
        self.__widget.debugEnabledCheckBox.setChecked(
            settings.is_debug_enabled
        )

    def __save_current_connection(self):
        connections_manager = NgwConnectionsManager()
        old_connection = self.__current_connection
        new_connection_id = self.connections_widget.connection_id()

        need_reinint = False

        if (
            old_connection is not None and new_connection_id is None
            or old_connection is None and new_connection_id is not None
        ):
            need_reinint = True
            connections_manager.current_connection_id = new_connection_id
        elif old_connection is not None and new_connection_id is not None:
            new_connection = connections_manager.connection(new_connection_id)
            if old_connection != new_connection:
                need_reinint = True
                connections_manager.current_connection_id = new_connection_id

        if need_reinint:
            dock = iface.mainWindow().findChild(NgConnectDock, 'NGConnectDock')
            dock.reinit_tree(force=True)


class NgConnectOptionsErrorPageWidget(QgsOptionsPageWidget):
    widget: QWidget

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.widget = QLabel(self.tr('Settings dialog was crashed'), self)
        self.widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.addWidget(self.widget)

    def apply(self) -> None:
        pass

    def cancel(self) -> None:
        pass


class NgConnectOptionsWidgetFactory(QgsOptionsWidgetFactory):
    def __init__(self):
        ICONS_PATH = os.path.join(os.path.dirname(__file__), 'icons/')
        super().__init__(
            'NextGIS Connect', QIcon(os.path.join(ICONS_PATH, 'logo.svg'))
        )

    def path(self) -> List[str]:
        return ['NextGIS']

    def createWidget(
        self, parent: Optional[QWidget] = None
    ) -> Optional[QgsOptionsPageWidget]:
        try:
            return NgConnectOptionsPageWidget(parent)
        except Exception as error:
            utils.log_to_qgis(
                'Settings dialog was crashed', Qgis.MessageLevel.Critical
            )
            utils.log_to_qgis(str(error), Qgis.MessageLevel.Critical)
            return NgConnectOptionsErrorPageWidget(parent)
