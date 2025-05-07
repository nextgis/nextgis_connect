import sys
from pathlib import Path
from typing import Union

from osgeo import gdal
from qgis.core import Qgis, QgsApplication, QgsTaskManager
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import (
    QT_VERSION_STR,
    QAbstractItemModel,
    QItemSelectionModel,
    QSysInfo,
    QTranslator,
    QUrl,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QPushButton, QToolBar
from qgis.utils import iface

from nextgis_connect.exceptions import ErrorCode, NgConnectError
from nextgis_connect.logging import logger, unload_logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from nextgis_connect.utils import nextgis_domain, utm_tags

assert isinstance(iface, QgisInterface)


class NgConnectPluginStub(NgConnectInterface):
    """NextGIS Connect Plugin stub for exceptions processing"""

    def __init__(self) -> None:
        super().__init__()
        plugin_dir = Path(__file__).parent

        logger.debug("<b>✓ Plugin stub object created</b>")
        logger.debug(f"<b>ⓘ OS:</b> {QSysInfo().prettyProductName()}")
        logger.debug(f"<b>ⓘ Qt version:</b> {QT_VERSION_STR}")
        logger.debug(f"<b>ⓘ QGIS version:</b> {Qgis.version()}")
        logger.debug(f"<b>ⓘ Python version:</b> {sys.version}")
        logger.debug(f"<b>ⓘ GDAL version:</b> {gdal.__version__}")
        logger.debug(f"<b>ⓘ Plugin version:</b> {self.version}")
        logger.debug(
            f"<b>ⓘ Plugin path:</b> {plugin_dir}"
            + (
                f" -> {plugin_dir.resolve()}"
                if plugin_dir.is_symlink()
                else ""
            )
        )

    def initGui(self) -> None:
        logger.debug("<b>Start stub initialization</b>")

        self.__init_translator()

        logger.debug("<b>End stub initialization</b>")

    def unload(self) -> None:
        logger.debug("<b>Start stub unloading</b>")

        self.__unload_translations()

        logger.debug("<b>End stub unloading</b>")

        unload_logger()

    def show_error(self, error: Exception) -> str:
        settings = NgConnectSettings()

        pretend_is_not_a_error = False
        if not settings.did_last_launch_fail and isinstance(
            error, ImportError
        ):
            old_error = error
            error = NgConnectError(code=ErrorCode.BigUpdateError)
            error.__cause__ = old_error
            pretend_is_not_a_error = True

        settings.did_last_launch_fail = True

        if not isinstance(error, NgConnectError):
            old_error = error
            error = NgConnectError()
            error.__cause__ = old_error
            del old_error

        message = error.user_message
        if not message.endswith("."):
            message += "."
        if message.endswith(".."):
            message = message.rstrip(".") + "."

        message_bar = iface.messageBar()
        assert message_bar is not None

        widget = message_bar.createMessage(
            NgConnectInterface.PLUGIN_NAME, message
        )

        def contact_us():
            utm = utm_tags("error")
            QDesktopServices.openUrl(
                QUrl(f"{nextgis_domain()}/contact/?{utm}")
            )

        if not pretend_is_not_a_error:
            button = QPushButton(self.tr("Open logs"))
            button.pressed.connect(iface.openMessageLog)
            widget.layout().addWidget(button)

            button = QPushButton(self.tr("Let us know"))
            button.pressed.connect(contact_us)
            widget.layout().addWidget(button)

        message_bar.pushWidget(
            widget,
            Qgis.MessageLevel.Success
            if pretend_is_not_a_error
            else Qgis.MessageLevel.Critical,
            duration=0,
        )

        logger.exception(error.log_message, exc_info=error)

        return error.error_id

    def close_error(self, error: Union[Exception, str]) -> None:
        raise NotImplementedError

    @property
    def toolbar(self) -> QToolBar:
        raise NotImplementedError

    @property
    def resource_model(self) -> QAbstractItemModel:
        raise NotImplementedError

    @property
    def resource_selection_model(self) -> QItemSelectionModel:
        raise NotImplementedError

    @property
    def task_manager(self) -> QgsTaskManager:
        raise NotImplementedError

    def synchronize_layers(self) -> None:
        raise NotImplementedError

    def enable_synchronization(self) -> None:
        raise NotImplementedError

    def disable_synchronization(self) -> None:
        raise NotImplementedError

    def __init_translator(self) -> None:
        application = QgsApplication.instance()
        assert application is not None
        locale = application.locale()
        self.__translators = list()

        def add_translator(locale_path: Path) -> None:
            translator = QTranslator()

            is_loaded = translator.load(str(locale_path))
            if not is_loaded:
                return

            is_installed = QgsApplication.installTranslator(translator)
            if not is_installed:
                return

            # Should be kept in memory
            self.__translators.append(translator)

        add_translator(
            Path(__file__).parent / "i18n" / f"nextgis_connect_{locale}.qm",
        )

    def __unload_translations(self) -> None:
        for translator in self.__translators:
            QgsApplication.removeTranslator(translator)

        self.__translators.clear()
