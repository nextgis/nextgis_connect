import importlib.util
import json
import os.path
import re
import uuid
from typing import Optional
from urllib.parse import urljoin, urlparse

from qgis.core import Qgis, QgsApplication, QgsNetworkAccessManager
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QMetaObject,
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QToolButton,
    QWidget,
)

from nextgis_connect.exceptions import ErrorCode, NgwError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_connection.auth_config_edit_dialog import (
    AuthConfigEditDialog,
)

from .ngw_connection import NgwConnection
from .ngw_connections_manager import NgwConnectionsManager

HAS_NGSTD = importlib.util.find_spec("ngstd") is not None
NGAccess = None
NGRequest = None
if HAS_NGSTD:
    from ngstd.core import NGRequest  # type: ignore
    from ngstd.framework import NGAccess  # type: ignore


pluginPath = os.path.dirname(__file__)

WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, "ngw_connection_edit_dialog_base.ui")
)


class NgwConnectionEditDialog(QDialog, WIDGET):
    NEXTGIS_DOMAIN = ".nextgis.com"

    __is_edit: bool
    __connection_id: str
    __is_save_clicked: bool
    __url_completer_model: QStringListModel
    __name_completer_model: QStringListModel
    __name_was_manually_changed: bool

    __network_manager: QgsNetworkAccessManager
    __reply: Optional[QNetworkReply]
    __timer: Optional[QTimer]

    def __init__(
        self, parent: Optional[QWidget], connection_id: Optional[str] = None
    ) -> None:
        super().__init__(parent)
        self.setupUi(self)

        warning_icon = QgsApplication.getThemeIcon("mIconWarning.svg")
        size = int(max(24.0, self.authWidget.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.authWarningLabel.setPixmap(pixmap)
        self.authWarningLabel.setToolTip(
            self.tr(
                "NextGIS authentication is not supported for my.nextgis.com"
                " yet. Please choose Basic authentication or change"
                " authentication endpoint."
            )
        )
        self.authWarningLabel.hide()

        self.progressBar.hide()

        self.__network_manager = QgsNetworkAccessManager()
        self.__reply = None
        self.__timer = None

        self.__is_edit = connection_id is not None
        if self.__is_edit:
            self.setWindowTitle(self.tr("Edit the NextGIS Web Connection"))
            assert connection_id is not None
            self.__connection_id = connection_id
            self.__name_was_manually_changed = True
            self.__populate_by_existed(connection_id)
        else:
            self.__connection_id = str(uuid.uuid4())

        self.__is_save_clicked = False
        self.__name_was_manually_changed = False
        help_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Help
        )
        help_button.clicked.connect(self.__open_help)

        # Url field settings
        self.urlRequiredLabel.hide()
        self.urlLineEdit.textChanged.connect(self.__on_url_changed)
        self.urlLineEdit.setShowClearButton(False)
        self.__url_completer_model = QStringListModel(self)
        url_completer = QCompleter(self.__url_completer_model)
        url_completer.setCompletionMode(
            QCompleter.CompletionMode.InlineCompletion
        )
        self.urlLineEdit.setCompleter(url_completer)

        # Name field settings
        self.nameRequiredLabel.hide()
        self.nameLineEdit.textChanged.connect(self.__on_name_changed)
        self.__name_completer_model = QStringListModel(self)
        name_completer = QCompleter(self.__name_completer_model)
        name_completer.setCompletionMode(
            QCompleter.CompletionMode.InlineCompletion
        )
        self.nameLineEdit.setCompleter(name_completer)

        # Auth settings
        self.authWidget.selectedConfigIdChanged.connect(self.__validate)
        self.authWidget.selectedConfigIdRemoved.connect(self.__validate)
        self.testConnectionButton.clicked.connect(self.__test_connection)

        save_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Save
        )
        assert save_button is not None
        save_button.clicked.connect(self.__save_clicked)
        self.buttonBox.rejected.connect(self.reject)

        self.authWidget.selectedConfigIdChanged.connect(
            self.__patch_auth_config_selector
        )
        self.authWidget.selectedConfigIdRemoved.connect(
            self.__patch_auth_config_selector
        )
        self.__patch_auth_config_selector()

        add_config_button: Optional[QToolButton] = self.authWidget.findChild(
            QToolButton, "btnConfigAdd"
        )
        if add_config_button is not None:
            add_config_button.clicked.disconnect()
            add_config_button.clicked.connect(self.__on_add_config_clicked)

        edit_config_button: Optional[QToolButton] = self.authWidget.findChild(
            QToolButton, "btnConfigEdit"
        )
        if edit_config_button is not None:
            edit_config_button.clicked.disconnect()
            edit_config_button.clicked.connect(self.__on_edit_config_clicked)

        self.__validate()

    def connection_id(self):
        return self.__connection_id

    def set_message(
        self,
        text: str,
        level: Qgis.MessageLevel = Qgis.MessageLevel.Info,
        duration: int = -1,
    ) -> None:
        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(text, level, duration)

    def reject(self) -> None:
        if self.__timer is not None and self.__timer.isActive():
            self.__timer.stop()
            del self.__timer
            self.__timer = None
        if self.__reply is not None and self.__reply.isRunning():
            self.__reply.finished.disconnect()
            self.__reply.abort()
            del self.__reply
            self.__reply = None

        super().reject()

    def __populate_by_existed(self, connection_id: str):
        connection = NgwConnectionsManager().connection(connection_id)
        if connection is None:
            return

        self.urlLineEdit.setText(connection.url)
        self.nameLineEdit.setText(connection.name)
        if connection.auth_config_id is not None:
            self.authWidget.setConfigId(connection.auth_config_id)

    def __save_clicked(self):
        self.__is_save_clicked = True
        self.__send_test_request()

    def __on_url_changed(self, text: str) -> None:
        curent_cursor_position = self.urlLineEdit.cursorPosition()
        lower_text = text.lower()
        self.urlLineEdit.setText(lower_text)
        self.urlLineEdit.setCursorPosition(curent_cursor_position)

        is_empty = len(lower_text) == 0
        self.urlLineEdit.setHighlighted(is_empty)
        self.urlRequiredLabel.setVisible(is_empty)

        self.__update_url_completer(lower_text)
        self.__update_name(lower_text)

        self.__validate()

    def __update_url_completer(self, value: str):
        if any(char in value for char in [":", "\\", "/"]):
            self.__url_completer_model.setStringList([])
            return

        suffix = self.NEXTGIS_DOMAIN

        first_point_pos = value.find(".")
        if first_point_pos != -1:
            text_after_point = value[first_point_pos:]
            if not self.NEXTGIS_DOMAIN.startswith(text_after_point):
                self.__url_completer_model.setStringList([])
                return

            suffix = self.NEXTGIS_DOMAIN[len(text_after_point) :]

        self.__url_completer_model.setStringList([value + suffix])

    def __update_name(self, url: str):
        url = self.__make_valid_url(url)

        parse_result = urlparse(url)
        connection_name = parse_result.netloc
        connection_name = connection_name.split(".")[0]

        if not self.__is_edit and not self.__name_was_manually_changed:
            self.nameLineEdit.textChanged.disconnect(self.__on_name_changed)
            self.nameLineEdit.setText(connection_name)
            self.nameLineEdit.textChanged.connect(self.__on_name_changed)

            self.nameLineEdit.setHighlighted(False)
            self.nameRequiredLabel.setVisible(False)

        self.nameLineEdit.setPlaceholderText(connection_name)
        self.__name_completer_model.setStringList([connection_name])

    def __on_name_changed(self, text: str) -> None:
        is_empty = len(text) == 0
        self.nameLineEdit.setHighlighted(is_empty)
        self.nameRequiredLabel.setVisible(is_empty)

        self.__name_was_manually_changed = not is_empty

        self.__validate()

    def __validate(self):
        is_url_valid = len(self.urlLineEdit.text()) != 0
        is_name_valid = len(self.nameLineEdit.text()) != 0
        is_auth_valid = True

        if HAS_NGSTD:
            method = QgsApplication.authManager().configAuthMethodKey(
                self.authWidget.configId()
            )

            endpoint = NGAccess.instance().endPoint()  # type: ignore
            domain = urlparse(endpoint).netloc
            is_my = method == "NextGIS" and domain.startswith("my.nextgis")

            is_auth_valid = not is_my
            self.authWarningLabel.setVisible(not is_auth_valid)

        is_valid = is_url_valid and is_name_valid and is_auth_valid

        save_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Save
        )
        save_button.setEnabled(is_valid)
        self.testConnectionButton.setEnabled(is_valid)

    def __test_connection(self):
        self.__send_test_request()

    def __send_test_request(self):
        self.__lock_gui()

        self.__temp_connection = NgwConnection(
            str(uuid.uuid4()),
            "TEST_CONNECTION",
            self.__make_valid_url(self.urlLineEdit.text()),
            self.authWidget.configId(),
        )

        if HAS_NGSTD and self.__temp_connection.auth_config_id == "NextGIS":
            NGRequest.addAuthURL(
                NGAccess.instance().endPoint(), self.__temp_connection.url
            )

        url = urljoin(
            self.__temp_connection.url, "api/component/auth/current_user"
        )
        request = QNetworkRequest(QUrl(url))
        try:
            self.__temp_connection.update_network_request(request)
        except Exception:
            self.messageBar.clearWidgets()
            self.messageBar.pushMessage(
                self.tr("Connection failed"),
                self.tr("Authentication error"),
                Qgis.MessageLevel.Warning,
            )
            return

        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(15000)

        self.__reply = self.__network_manager.get(request)
        assert self.__reply is not None
        self.__timer.timeout.connect(self.__reply.abort)
        self.__reply.finished.connect(self.__process_test_instance_reply)
        self.__timer.start()

    def __process_test_instance_reply(self):
        assert self.__timer is not None
        assert self.__reply is not None

        is_timeout = not self.__timer.isActive()
        self.__timer.stop()
        self.__timer = None

        if self.__reply.error() != QNetworkReply.NetworkError.NoError:
            self.__process_request_error(is_timeout)
            self.__reply = None
            return

        url = urljoin(self.__temp_connection.url, "api/resource/0")
        request = QNetworkRequest(QUrl(url))
        self.__temp_connection.update_network_request(request)

        self.__timer = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(15000)

        self.__reply = self.__network_manager.get(request)
        assert self.__reply is not None
        self.__timer.timeout.connect(self.__reply.abort)
        self.__reply.finished.connect(self.__process_test_user_reply)
        self.__timer.start()

    def __process_test_user_reply(self):
        assert self.__timer is not None
        assert self.__reply is not None

        is_timeout = not self.__timer.isActive()
        self.__timer.stop()
        self.__timer = None

        if self.__reply.error() != QNetworkReply.NetworkError.NoError:
            self.__process_request_error(is_timeout, True)
            self.__reply = None
            return

        if self.__is_save_clicked:
            self.__save_connection()
            self.__reply = None
            self.accept()
            return

        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(
            self.tr("Connection successful"), Qgis.MessageLevel.Success
        )

        self.__unlock_gui()

        self.__reply = None

    def __process_request_error(
        self, is_timeout: bool = False, is_user_check: bool = False
    ):
        assert self.__reply is not None

        self.__is_save_clicked = False

        message_title = self.tr("Connection failed")
        message = None

        if is_timeout:
            message = self.tr("Request timeout")
        else:
            error = None

            content = self.__reply.readAll().data()
            if len(content) > 0:
                try:
                    json_content = json.loads(content)
                    error = NgwError.from_json(json_content)
                except Exception:
                    logger.exception(
                        "An error occurred while testing connection"
                    )

            if error is not None:
                if not is_user_check:
                    message = error.user_message
                elif error.code != ErrorCode.PermissionsError:
                    message = error.user_message
                    logger.exception(
                        "An error occurred while testing connection",
                        exc_info=error,
                    )
                else:
                    message = self.tr("Web GIS access was not granted for the")
                    if not self.__temp_connection.auth_config_id:
                        message += self.tr(" guest users.")
                    else:
                        message += self.tr(
                            " selected authentication parameters."
                        )

        arguments = (
            (message_title,) if message is None else (message_title, message)
        )
        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(*arguments, Qgis.MessageLevel.Warning)
        self.__unlock_gui()

    def __save_connection(self):
        url = self.__make_valid_url(self.urlLineEdit.text())
        name = self.nameLineEdit.text()

        connection_id = self.__connection_id
        auth_config_id = self.authWidget.configId()
        auth_config_id = auth_config_id if len(auth_config_id) > 0 else None

        connection = NgwConnection(connection_id, name, url, auth_config_id)
        NgwConnectionsManager().save(connection)

    def __lock_gui(self):
        self.urlLineEdit.setEnabled(False)
        self.nameLineEdit.setEnabled(False)
        self.authWidget.setEnabled(False)
        self.testConnectionButton.setEnabled(False)
        save_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Save
        )
        save_button.setEnabled(False)
        self.testConnectionButton.hide()
        self.progressBar.show()
        self.messageBar.clearWidgets()

    def __unlock_gui(self):
        self.urlLineEdit.setEnabled(True)
        self.nameLineEdit.setEnabled(True)
        self.authWidget.setEnabled(True)
        self.testConnectionButton.setEnabled(True)
        save_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Save
        )
        save_button.setEnabled(True)
        self.testConnectionButton.show()
        self.progressBar.hide()

    def __make_valid_url(self, url: str) -> str:
        url = url.strip()

        # Always remove trailing slashes (this is only a base url which will
        # not be used standalone anywhere).
        while url.endswith("/"):
            url = url[:-1]

        # Replace common ending when user copy-pastes from browser URL
        url = re.sub("/resource/[0-9]+", "", url)

        parse_result = urlparse(url)
        hostname = parse_result.hostname

        # Select https if protocol has not been defined by user
        if hostname is None:
            url = f"https://{url}"

        # Force https regardless of what user has selected, but only for cloud
        # connections.
        if url.startswith("http://") and url.endswith(self.NEXTGIS_DOMAIN):
            url = url.replace("http://", "https://")

        return url

    @pyqtSlot()
    def __on_add_config_clicked(self) -> None:
        if not QgsApplication.authManager().setMasterPassword(True):
            return

        dialog = AuthConfigEditDialog("", self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.set_connection_name(
            self.nameLineEdit.text()
            if len(self.nameLineEdit.text()) > 0
            else "NextGIS Web"
        )

        is_added = dialog.exec()
        if is_added:
            self.authWidget.setConfigId(dialog.config_id)

    @pyqtSlot()
    def __on_edit_config_clicked(self) -> None:
        if not QgsApplication.authManager().setMasterPassword(True):
            return

        method = QgsApplication.authManager().configAuthMethodKey(
            self.authWidget.configId()
        )
        if method != "Basic":
            QMetaObject.invokeMethod(self.authWidget, "btnConfigEdit_clicked")
            return

        dialog = AuthConfigEditDialog(self.authWidget.configId(), self)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        is_edited = dialog.exec()
        if is_edited:
            self.authWidget.setConfigId(dialog.config_id)

    @pyqtSlot()
    def __patch_auth_config_selector(self) -> None:
        combobox: Optional[QComboBox] = self.authWidget.findChild(QComboBox)
        if combobox is None:
            return
        index = combobox.findData("0")
        if index == -1:
            return
        combobox.setItemText(index, self.tr("As guest"))

    @pyqtSlot()
    def __open_help(self) -> None:
        QDesktopServices.openUrl(
            QUrl(
                "https://docs.nextgis.com/docs_ngcom/source/ngqgis_connect.html#ngcom-ngqgis-connect-connection"
            )
        )
