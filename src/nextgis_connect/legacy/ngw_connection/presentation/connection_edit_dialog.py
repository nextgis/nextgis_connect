# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import importlib.util
import uuid
from dataclasses import dataclass
from enum import Enum
from math import ceil
from pathlib import Path
from typing import List, Optional, Tuple, cast
from urllib.parse import urlparse

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
)
from qgis.gui import QgsMessageBar
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAction,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.application.diagnostics.runner import (
    NgwConnectionVerifier,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionIssue,
    ConnectionIssueSource,
    ConnectionVerificationResult,
)
from nextgis_connect.legacy.ngw_connection.domain.parsers import (
    suggested_connection_name,
)
from nextgis_connect.legacy.ngw_connection.presentation.auth_config_edit_dialog import (
    AuthConfigEditorWidget,
)
from nextgis_connect.legacy.ngw_connection.presentation.dialog_header_widget import (
    NextgisDialogHeaderWidget,
)
from nextgis_connect.platform.qgis.utils import nextgis_domain
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.buttons.loading import (
    LoadingPushButton,
    LoadingToolButton,
)
from nextgis_connect.ui_kit.icons import material_icon, plugin_icon, qgis_icon

HAS_NGSTD = importlib.util.find_spec("ngstd") is not None
NGAccess = None
NGRequest = None
if HAS_NGSTD:
    from ngstd.core import NGRequest  # type: ignore
    from ngstd.framework import NGAccess  # type: ignore


PLUGIN_PATH = Path(__file__).parent

WIDGET, _ = uic.loadUiType(
    str(PLUGIN_PATH / "forms" / "connection_edit_dialog.ui")
)


class LoginChoiceKind(Enum):
    GUEST = "guest"
    EXISTING = "existing"
    OTHER = "other"


@dataclass(frozen=True)
class LoginChoice:
    kind: LoginChoiceKind
    title: str
    method: str = ""
    auth_config_id: Optional[str] = None
    tooltip: str = ""


class NextgisQgisUserAvailability:
    AUTH_CONFIG_ID = "NextGIS"
    AUTH_METHOD = "NextGIS"
    UNSUPPORTED_ENDPOINT_PREFIX = "my.nextgis"

    @classmethod
    def is_available(cls) -> bool:
        if not HAS_NGSTD or NGAccess is None:
            return False

        auth_manager = QgsApplication.authManager()
        if auth_manager.isDisabled():
            return False

        if (
            auth_manager.configAuthMethodKey(cls.AUTH_CONFIG_ID)
            != cls.AUTH_METHOD
        ):
            return False

        access = NGAccess.instance()
        if not access.isUserAuthorized():
            return False

        endpoint_host = urlparse(access.endPoint()).hostname
        if endpoint_host is None:
            return False

        return not endpoint_host.lower().startswith(
            cls.UNSUPPORTED_ENDPOINT_PREFIX
        )


@dataclass(frozen=True)
class LoginChoiceLabels:
    nextgis_qgis_account: str
    saved_basic_sign_in: str
    basic_sign_in_tooltip_format: str


class LoginChoiceResolver:
    def __init__(
        self,
        connection_url: str,
        *,
        is_edit: bool,
        filter_by_resource: bool,
        labels: LoginChoiceLabels,
    ) -> None:
        self.__connection_url = connection_url
        self.__is_edit = is_edit
        self.__filter_by_resource = filter_by_resource
        self.__labels = labels

    def existing_choices(
        self,
        current_auth_config_id: str,
    ) -> Tuple[List[LoginChoice], List[LoginChoice]]:
        auth_manager = QgsApplication.authManager()
        configs = auth_manager.availableAuthMethodConfigs()

        nextgis_choices = []
        basic_choices = []
        for config_id, config in configs.items():
            method = config.method() or auth_manager.configAuthMethodKey(
                config_id
            )
            if method not in ("Basic", "NextGIS"):
                continue

            if not self.__should_show_auth_config(
                config_id,
                config,
                method,
                current_auth_config_id,
            ):
                continue

            title, tooltip = self.__choice_details(config_id, config)
            choice = LoginChoice(
                LoginChoiceKind.EXISTING,
                title,
                method,
                config_id,
                tooltip,
            )
            if method == "NextGIS":
                nextgis_choices.append(choice)
            else:
                basic_choices.append(choice)

        if len(current_auth_config_id) != 0 and all(
            choice.auth_config_id != current_auth_config_id
            for choice in nextgis_choices + basic_choices
        ):
            method = auth_manager.configAuthMethodKey(current_auth_config_id)
            if current_auth_config_id == "NextGIS":
                method = "NextGIS"
            if (
                method in ("Basic", "NextGIS")
                or current_auth_config_id == "NextGIS"
            ) and self.__should_show_missing_auth_config(
                current_auth_config_id,
                method,
            ):
                title, tooltip = self.__choice_details(current_auth_config_id)
                choice = LoginChoice(
                    LoginChoiceKind.EXISTING,
                    title,
                    method,
                    current_auth_config_id,
                    tooltip,
                )
                if method == "NextGIS" or current_auth_config_id == "NextGIS":
                    nextgis_choices.append(choice)
                else:
                    basic_choices.append(choice)

        basic_choices.sort(key=lambda choice: choice.title.lower())
        return nextgis_choices, basic_choices

    def __should_show_auth_config(
        self,
        config_id: str,
        config: QgsAuthMethodConfig,
        method: str,
        current_auth_config_id: str,
    ) -> bool:
        if method == "NextGIS":
            return self.__should_show_nextgis_qgis_user(
                config_id,
                current_auth_config_id,
            )

        if not self.__filter_by_resource:
            return True

        return self.__is_auth_config_resource_current(config)

    def __should_show_missing_auth_config(
        self,
        config_id: str,
        method: str,
    ) -> bool:
        if method == "NextGIS" or config_id == "NextGIS":
            return self.__should_show_nextgis_qgis_user(
                config_id,
                config_id,
            )

        if not self.__filter_by_resource:
            return True

        if method != "Basic":
            return False

        is_loaded, config = (
            QgsApplication.authManager().loadAuthenticationConfig(
                config_id,
                QgsAuthMethodConfig(),
                full=True,
            )
        )
        if not is_loaded:
            return False

        return self.__is_auth_config_resource_current(config)

    def __should_show_nextgis_qgis_user(
        self,
        config_id: str,
        current_auth_config_id: str,
    ) -> bool:
        if NextgisQgisUserAvailability.is_available():
            return True

        return (
            self.__is_edit
            and len(current_auth_config_id) != 0
            and config_id == current_auth_config_id
        )

    def __is_auth_config_resource_current(
        self,
        config: QgsAuthMethodConfig,
    ) -> bool:
        resource = config.uri().strip()
        if len(resource) == 0:
            return False

        return NgwConnection.normalize_url(
            resource
        ) == NgwConnection.normalize_url(self.__connection_url)

    def __choice_details(
        self,
        config_id: str,
        config: Optional[QgsAuthMethodConfig] = None,
    ) -> Tuple[str, str]:
        if config_id == "NextGIS":
            return self.__labels.nextgis_qgis_account, ""

        method = ""
        if config is not None:
            method = config.method()
        if len(method) == 0:
            method = QgsApplication.authManager().configAuthMethodKey(
                config_id
            )

        if method == "NextGIS":
            return self.__labels.nextgis_qgis_account, ""

        username = ""
        if config is not None:
            username = config.configMap().get("username", "").strip()
            if len(username) == 0:
                username = config.name().strip()
                if " / " in username:
                    username = username.rsplit(" / ", 1)[-1].strip()

        if len(username) == 0:
            loaded_username = self.__load_username(config_id)
            if loaded_username is not None:
                username = loaded_username

        if len(username) == 0:
            username = self.__labels.saved_basic_sign_in

        return (
            username,
            self.__labels.basic_sign_in_tooltip_format.format(username),
        )

    def __load_username(self, config_id: str) -> Optional[str]:
        auth_manager = QgsApplication.authManager()
        method = auth_manager.configAuthMethodKey(config_id)
        if method not in ("Basic", "NextGIS"):
            return None

        is_loaded, config = auth_manager.loadAuthenticationConfig(
            config_id,
            QgsAuthMethodConfig(),
            full=True,
        )
        if not is_loaded:
            return None

        username = config.configMap().get("username", None)
        if not username:
            return None

        return username


class NgwConnectionEditDialog(QDialog, WIDGET):
    NEXTGIS_DOMAIN = ".nextgis.com"
    PREFERRED_WIDTH = 460

    __is_edit: bool
    __connection_id: str
    __url_completer_model: QStringListModel
    __name_completer_model: QStringListModel
    __name_was_manually_changed: bool
    __connections_manager: NgwConnectionsManager
    __result_connection: Optional[NgwConnection]
    __save_on_accept: bool
    __temp_connection: Optional[NgwConnection]
    __verifier: Optional[NgwConnectionVerifier]
    __name_loader: Optional[NgwConnectionVerifier]
    __save_button: LoadingPushButton
    __name_loader_button: LoadingToolButton
    __auth_filter_button: QToolButton
    __filter_auth_by_resource: bool
    __created_auth_config_id: Optional[str]
    __temporary_auth_config_id: Optional[str]
    __temporary_previous_auth_config_id: Optional[str]
    __accept_on_verification_success: bool
    __auth_editor: AuthConfigEditorWidget
    __current_user_index: int
    __missing_auth_config_reason: Optional[str]
    __confirmed_external_auth_credentials: Optional[Tuple[str, str, str]]

    def __init__(
        self,
        parent: Optional[QWidget],
        connection_id: Optional[str] = None,
        *,
        connection: Optional[NgwConnection] = None,
        connections_manager: Optional[NgwConnectionsManager] = None,
        save_on_accept: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.__stabilize_layout_spacing()
        self.messageBar.hide()
        self.messageBar.widgetAdded.connect(self.__sync_message_bar_visibility)
        self.messageBar.widgetRemoved.connect(
            self.__sync_message_bar_visibility
        )

        root_layout = cast(QVBoxLayout, self.layout())
        original_margins = root_layout.contentsMargins()
        original_spacing = root_layout.spacing()
        content_widget = QWidget(self)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(
            original_margins.left(),
            original_spacing + 4,
            original_margins.right(),
            original_margins.bottom(),
        )
        content_layout.setSpacing(original_spacing)

        while root_layout.count() != 0:
            item = root_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            spacer_item = item.spacerItem()
            if widget is not None:
                content_layout.addWidget(widget)
            elif child_layout is not None:
                content_layout.addLayout(child_layout)
            elif spacer_item is not None:
                content_layout.addItem(spacer_item)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.__header_widget = NextgisDialogHeaderWidget(self)
        self.__header_widget.set_subtitle(
            self.tr("Set the server URL and choose how to sign in.")
        )
        self.__header_widget.logoClicked.connect(self.__open_nextgis_site)
        root_layout.addWidget(self.__header_widget)
        content_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        root_layout.addWidget(
            content_widget,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        self.__connections_manager = (
            NgwConnectionsManager()
            if connections_manager is None
            else connections_manager
        )
        self.__result_connection = None
        self.__save_on_accept = save_on_accept

        warning_icon = qgis_icon("mIconWarning.svg")
        size = int(max(24.0, self.userComboBox.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.authWarningLabel.setPixmap(pixmap)
        self.authWarningLabel.setFixedWidth(pixmap.width())
        self.authWarningLabel.setContentsMargins(0, 0, 0, 0)
        self.authWarningLabel.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.authWarningLabel.setToolTip(
            self.tr(
                "NextGIS authentication is not supported for my.nextgis.com"
                " yet. Please choose Basic authentication or change"
                " authentication endpoint."
            )
        )
        self.authWarningLabel.hide()

        self.progressBar.hide()
        self.__temp_connection = None
        self.__verifier = None
        self.__name_loader = None
        self.__filter_auth_by_resource = True
        self.__created_auth_config_id = None
        self.__temporary_auth_config_id = None
        self.__temporary_previous_auth_config_id = None
        self.__accept_on_verification_success = False
        self.__current_user_index = -1
        self.__missing_auth_config_reason = None
        self.__confirmed_external_auth_credentials = None

        self.__auth_editor = AuthConfigEditorWidget(parent=self, embedded=True)
        self.__auth_editor.validityChanged.connect(self.__validate)
        self.__auth_editor.deleted.connect(self.__on_auth_config_deleted)
        self.__auth_editor.layoutChanged.connect(self.__schedule_resize)
        self.__prepare_auth_group_box()
        self.authGroupBox.layout().addWidget(self.__auth_editor)

        self.__is_edit = connection_id is not None or connection is not None
        if self.__is_edit:
            self.setWindowTitle(self.tr("Edit Connection"))
            if connection is not None:
                self.__connection_id = connection.id
            else:
                assert connection_id is not None
                self.__connection_id = connection_id
            self.__name_was_manually_changed = True
            if connection is None:
                connection = self.__connections_manager.connection(
                    self.__connection_id
                )
            self.__missing_auth_config_reason = (
                self.__connections_manager.invalid_reason(self.__connection_id)
            )
            self.__populate(connection)
        else:
            self.setWindowTitle(self.tr("New Connection"))
            self.__connection_id = str(uuid.uuid4())
            self.__set_name_field_visible(False)
            self.__name_was_manually_changed = False
            self.authWidget.setConfigId("")

        self.__header_widget.set_title(self.windowTitle())

        if connections_manager is None and save_on_accept:
            self.__connections_manager.connection_updated.connect(
                NgConnectInterface.instance().connection_updated.emit,
            )

        help_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Help
        )
        if help_button is not None:
            help_button.setIcon(plugin_icon("branding/nextgis_logo.svg"))
            help_button.clicked.connect(self.__open_help)

        # Url field settings
        self.urlRequiredLabel.hide()
        self.urlLineEdit.textChanged.connect(self.__on_url_changed)
        self.urlLineEdit.editingFinished.connect(
            self.__select_guest_for_demo_if_new_user_empty
        )
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
        self.__setup_name_loader_button()
        self.__setup_auth_filter_button()
        self.__stabilize_field_heights()
        self.__set_name_field_visible(self.__is_edit)
        self.__name_completer_model = QStringListModel(self)
        name_completer = QCompleter(self.__name_completer_model)
        name_completer.setCompletionMode(
            QCompleter.CompletionMode.InlineCompletion
        )
        self.nameLineEdit.setCompleter(name_completer)

        # Auth settings
        self.userComboBox.currentIndexChanged.connect(self.__on_user_changed)
        self.authWidget.selectedConfigIdChanged.connect(self.__validate)
        self.authWidget.selectedConfigIdRemoved.connect(self.__validate)
        self.__setup_test_connection_button()
        self.setTabOrder(
            self.userComboBox, self.__auth_editor.username_lineedit
        )
        self.setTabOrder(
            self.__auth_editor.username_lineedit,
            self.__auth_editor.password_lineedit,
        )
        self.setTabOrder(
            self.__auth_editor.password_lineedit,
            self.testConnectionButton,
        )

        self.__setup_save_button()
        self.buttonBox.rejected.connect(self.reject)

        self.__populate_user_choices()

        self.__validate()
        self.__schedule_resize()

    def connection_id(self):
        return self.__connection_id

    def connection(self) -> NgwConnection:
        if self.__result_connection is not None:
            return self.__result_connection

        return self.__build_connection()

    def set_url(self, url: str) -> None:
        self.urlLineEdit.setText(url)
        self.urlLineEdit.setFocus()

    def set_message(
        self,
        text: str,
        level: Qgis.MessageLevel = Qgis.MessageLevel.Info,
        duration: int = -1,
    ) -> None:
        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(text, level, duration)
        self._expand_message_bar()

    def reject(self) -> None:
        if self.__verifier is not None:
            self.__verifier.cancel()
        if self.__name_loader is not None:
            self.__name_loader.cancel()
        self.__remove_temporary_auth_config()

        super().reject()

    def __populate(self, connection: Optional[NgwConnection]) -> None:
        if connection is None:
            return

        self.urlLineEdit.setText(connection.url)
        self.nameLineEdit.setText(connection.name)
        if connection.auth_config_id is not None:
            self.authWidget.setConfigId(connection.auth_config_id)
        else:
            self.authWidget.setConfigId("")

    def __save_clicked(self):
        if self.__is_duplicate_connection_url():
            return

        self.__start_verification(accept_on_success=True, fetch_title=False)

    def __on_url_changed(self, text: str) -> None:
        curent_cursor_position = self.urlLineEdit.cursorPosition()
        lower_text = text.lower()
        self.urlLineEdit.setText(lower_text)
        self.urlLineEdit.setCursorPosition(curent_cursor_position)

        is_url_empty = len(lower_text) != 0
        self.urlLineEdit.setHighlighted(not is_url_empty)
        self.urlRequiredLabel.setVisible(not is_url_empty)

        self.__update_url_completer(lower_text)
        self.__update_name(lower_text)
        choice = self.__current_login_choice()
        updates_new_auth = (
            choice is not None and choice.kind == LoginChoiceKind.OTHER
        )
        new_auth_was_clean = (
            updates_new_auth and not self.__auth_editor.has_unsaved_changes()
        )
        self.__auth_editor.set_connection_url(
            self.__default_auth_resource(),
            force=updates_new_auth,
        )
        if new_auth_was_clean:
            self.__auth_editor.mark_clean()
        self.__populate_user_choices()

        self.__validate()
        self.__schedule_resize()

    def showEvent(self, a0) -> None:
        super().showEvent(a0)
        self.__schedule_resize()

    @pyqtSlot()
    def __schedule_resize(self) -> None:
        QTimer.singleShot(0, self.__delayed_resize)
        QTimer.singleShot(25, self.__delayed_resize)

    @pyqtSlot()
    def __delayed_resize(self) -> None:
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)

        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

        self.__update_group_box_minimum_heights()

        minimum_size = self.minimumSizeHint()
        preferred_size = (
            layout.sizeHint() if layout is not None else self.sizeHint()
        )
        target_width = max(
            minimum_size.width(),
            min(self.width(), self.PREFERRED_WIDTH),
        )
        target_height = preferred_size.height()
        if layout is not None and layout.hasHeightForWidth():
            target_height = layout.heightForWidth(target_width)

        target_size = QSize(
            target_width,
            max(target_height, minimum_size.height()),
        )

        self.resize(target_size)
        self.setFixedHeight(target_size.height())

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

        suggestions = []
        if len(value) >= 2 and "demo".startswith(value):
            suggestions.append(nextgis_domain("demo")[8:])
        if len(value) >= 2 and "sandbox".startswith(value):
            suggestions.append(nextgis_domain("sandbox")[8:])

        suggestions.append(value + suffix)

        self.__url_completer_model.setStringList(suggestions)

    def __update_name(self, url: str):
        connection_name = self.__suggested_connection_name(url)
        if not self.__name_was_manually_changed:
            self.nameLineEdit.textChanged.disconnect(self.__on_name_changed)
            self.nameLineEdit.setText(connection_name)
            self.nameLineEdit.textChanged.connect(self.__on_name_changed)

            self.nameLineEdit.setHighlighted(False)
            self.nameRequiredLabel.setVisible(False)

        self.nameLineEdit.setPlaceholderText(connection_name)
        self.__name_completer_model.setStringList([connection_name])

    def __suggested_connection_name(self, url: str) -> str:
        normalized_url = self.__make_valid_url(url)
        host = urlparse(normalized_url).netloc.lower()
        raw_value = url.strip().lower()

        if host == "demo.nextgis.com" or raw_value == "demo":
            return self.tr("Demo Examples")

        if host == "sandbox.nextgis.com" or raw_value == "sandbox":
            return self.tr("Sandbox")

        return suggested_connection_name(url)

    def __on_name_changed(self, text: str) -> None:
        is_empty = len(text) == 0
        self.nameLineEdit.setHighlighted(is_empty)
        self.nameRequiredLabel.setVisible(is_empty)

        self.__name_was_manually_changed = not is_empty
        self.__auth_editor.set_connection_name(
            self.__default_auth_config_name(),
        )

        self.__validate()
        self.__schedule_resize()

    def __validate(self):
        is_url_valid = len(self.urlLineEdit.text()) != 0
        is_name_valid = True
        if self.__is_edit:
            is_name_valid = len(self.nameLineEdit.text()) != 0
        choice = self.__current_login_choice()

        is_auth_valid = choice is not None
        if choice is not None and choice.kind != LoginChoiceKind.GUEST:
            if self.__login_choice_method(choice) == "NextGIS":
                is_auth_valid = NextgisQgisUserAvailability.is_available()
            else:
                is_auth_valid = self.__auth_editor.is_valid()

        warning_text = self.__missing_auth_config_reason or ""
        if warning_text != "":
            is_auth_valid = False
        elif (
            HAS_NGSTD
            and choice is not None
            and choice.kind != LoginChoiceKind.GUEST
        ):
            endpoint = NGAccess.instance().endPoint()  # type: ignore
            domain = urlparse(endpoint).netloc
            is_my = self.__login_choice_method(
                choice
            ) == "NextGIS" and domain.startswith("my.nextgis")

            if is_my:
                warning_text = self.tr(
                    "NextGIS authentication is not supported for my.nextgis.com"
                    " yet. Please choose Basic authentication or change"
                    " authentication endpoint."
                )
                is_auth_valid = False

        self.authWarningLabel.setToolTip(warning_text)
        self.authWarningLabel.setVisible(warning_text != "")

        is_valid = is_url_valid and is_name_valid and is_auth_valid

        self.__save_button.setEnabled(
            is_valid and self.__name_loader is None and self.__verifier is None
        )
        self.testConnectionButton.setEnabled(is_valid)
        self.__name_loader_button.setEnabled(
            is_url_valid and self.__name_loader is None
        )

    def __setup_name_loader_button(self) -> None:
        self.__name_loader_button = LoadingToolButton(
            icon=material_icon("sync"),
            parent=self,
        )
        self.__name_loader_button.setAutoRaise(True)
        self.__name_loader_button.setToolTip(
            self.tr("Load Web GIS name from server")
        )
        self.__name_loader_button.clicked.connect(self.__load_connection_name)

        self.gridLayout.removeWidget(self.nameLineEdit)
        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(2)
        name_layout.addWidget(self.nameLineEdit)
        name_layout.addWidget(self.__name_loader_button)
        self.gridLayout.addLayout(name_layout, 0, 1)
        self.__name_loader_button.setVisible(self.nameLineEdit.isVisible())

    def __setup_save_button(self) -> None:
        original_button = self.buttonBox.button(
            QDialogButtonBox.StandardButton.Save
        )
        assert original_button is not None

        self.__save_button = LoadingPushButton(
            icon=original_button.icon(),
            parent=self.buttonBox,
        )
        self.__save_button.setText(original_button.text())
        self.__save_button.setAutoDefault(original_button.autoDefault())
        self.__save_button.setDefault(original_button.isDefault())
        self.__save_button.clicked.connect(self.__save_clicked)

        self.buttonBox.removeButton(original_button)
        original_button.hide()
        original_button.deleteLater()
        self.buttonBox.addButton(
            self.__save_button,
            QDialogButtonBox.ButtonRole.AcceptRole,
        )

    def __stabilize_field_heights(self) -> None:
        fields = (
            self.urlLineEdit,
            self.nameLineEdit,
            self.userComboBox,
        )
        height = max(field.sizeHint().height() for field in fields)
        for field in fields:
            field.setMinimumHeight(height)
            field.setSizePolicy(
                field.sizePolicy().horizontalPolicy(),
                QSizePolicy.Policy.Preferred,
            )

        self.__name_loader_button.setFixedSize(QSize(height, height))
        self.__name_loader_button.setIconSize(QSize(16, 16))
        self.__auth_filter_button.setFixedSize(QSize(height, height))
        self.__auth_filter_button.setIconSize(QSize(16, 16))
        self.authWarningLabel.setFixedHeight(height)

    def __setup_auth_filter_button(self) -> None:
        self.loginLayout.setContentsMargins(0, 0, 0, 0)
        self.loginLayout.setSpacing(2)
        self.__auth_filter_button = QToolButton(self)
        self.__auth_filter_button.setAutoRaise(True)
        self.__auth_filter_button.setCheckable(True)
        self.__auth_filter_button.setChecked(self.__filter_auth_by_resource)
        self.__update_auth_filter_button_tooltip()
        self.__auth_filter_button.toggled.connect(
            self.__set_auth_resource_filter_enabled
        )
        self.loginLayout.insertWidget(1, self.__auth_filter_button)

    def __setup_test_connection_button(self) -> None:
        original_button = self.testConnectionButton
        index = self.buttonsLayout.indexOf(original_button)

        test_button = LoadingToolButton(parent=self)
        test_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        test_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

        test_action = QAction(
            material_icon("stethoscope"),
            original_button.text(),
            test_button,
        )
        test_action.triggered.connect(self.__test_connection)
        test_button.setDefaultAction(test_action)

        diagnostics_menu = QMenu(test_button)
        diagnostics_action = QAction(
            material_icon("troubleshoot"),
            self.tr("Diagnostics"),
            diagnostics_menu,
        )
        diagnostics_action.triggered.connect(
            self.__open_current_connection_diagnostics
        )
        diagnostics_menu.addAction(diagnostics_action)
        test_button.setMenu(diagnostics_menu)

        self.buttonsLayout.removeWidget(original_button)
        original_button.hide()
        original_button.deleteLater()
        self.buttonsLayout.insertWidget(index, test_button)
        self.testConnectionButton = test_button

    def __stabilize_layout_spacing(self) -> None:
        if hasattr(self, "verticalSpacer"):
            self.verticalSpacer.changeSize(
                0,
                0,
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )
        self.informationGroupBox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.authGroupBox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

    def __update_group_box_minimum_heights(self) -> None:
        for group_box in (self.informationGroupBox, self.authGroupBox):
            if not group_box.isVisible():
                group_box.setMinimumHeight(0)
                continue

            group_box.setMinimumHeight(0)
            group_box.layout().invalidate()
            group_box.layout().activate()
            group_box.setMinimumHeight(group_box.sizeHint().height())
            group_box.updateGeometry()

    def __prepare_auth_group_box(self) -> None:
        auth_layout = cast(QVBoxLayout, self.authGroupBox.layout())
        information_layout = self.informationGroupBox.layout()
        if information_layout is not None:
            information_margins = information_layout.contentsMargins()
            auth_layout.setContentsMargins(
                information_margins.left(),
                information_margins.top(),
                information_margins.right(),
                information_margins.bottom(),
            )
            auth_layout.setSpacing(information_layout.spacing())
        self.authWidget.hide()
        self.__clear_layout(auth_layout)

    def __clear_layout(self, layout: QLayout) -> None:
        while layout.count() != 0:
            item = layout.takeAt(0)
            child_layout = item.layout()
            widget = item.widget()

            if child_layout is not None:
                self.__clear_layout(child_layout)
                continue

            if widget is None:
                continue

            if widget is self.authWidget:
                widget.hide()
                continue

            widget.hide()
            widget.deleteLater()

    def __login_choice_method(self, choice: LoginChoice) -> str:
        if choice.method != "":
            return choice.method

        if choice.auth_config_id == "NextGIS":
            return "NextGIS"

        if choice.auth_config_id is None:
            return "Basic" if choice.kind == LoginChoiceKind.OTHER else ""

        return QgsApplication.authManager().configAuthMethodKey(
            choice.auth_config_id
        )

    def __test_connection(self):
        self.__start_verification(accept_on_success=False, fetch_title=False)

    def __load_connection_name(self) -> None:
        if self.__name_loader is not None or self.__verifier is not None:
            return

        if not self.__prepare_auth_config_for_use(persist_auth=False):
            self.__validate()
            return

        self.__name_loader = NgwConnectionVerifier(
            NgwConnection(
                str(uuid.uuid4()),
                "LOAD_CONNECTION_NAME",
                self.__make_valid_url(self.urlLineEdit.text()),
                self.__normalized_auth_config_id(),
            ),
            fetch_title=True,
            parent=self,
        )
        self.__name_loader.succeeded.connect(self.__handle_name_loader_success)
        self.__name_loader.failed.connect(self.__handle_name_loader_failure)
        self.__name_loader.finished.connect(self.__handle_name_loader_finished)
        self.nameLineEdit.setReadOnly(True)
        self.__save_button.setEnabled(False)
        self.__name_loader_button.start()
        self.__name_loader.start()
        self.nameLineEdit.setFocus(Qt.FocusReason.OtherFocusReason)

    def __handle_name_loader_success(
        self,
        verification_result: ConnectionVerificationResult,
    ) -> None:
        self.nameLineEdit.setText(verification_result.resolved_name)

    def __handle_name_loader_failure(
        self,
        issue: Optional[ConnectionIssue],
    ) -> None:
        self.__handle_verifier_failure_message(issue)

    def __handle_name_loader_finished(self) -> None:
        self.__name_loader = None
        self.nameLineEdit.setReadOnly(False)
        self.__name_loader_button.stop()
        self.__remove_temporary_auth_config()
        self.__validate()
        self.nameLineEdit.setFocus(Qt.FocusReason.OtherFocusReason)

    def __start_verification(
        self,
        *,
        accept_on_success: bool,
        fetch_title: bool,
    ) -> None:
        if self.__verifier is not None:
            return

        if not self.__prepare_auth_config_for_use(persist_auth=False):
            self.__validate()
            return

        self.__accept_on_verification_success = accept_on_success
        self.__temp_connection = NgwConnection(
            str(uuid.uuid4()),
            "TEST_CONNECTION",
            self.__make_valid_url(self.urlLineEdit.text()),
            self.__normalized_auth_config_id(),
        )

        if HAS_NGSTD and self.__temp_connection.auth_config_id == "NextGIS":
            NGRequest.addAuthURL(
                NGAccess.instance().endPoint(), self.__temp_connection.url
            )

        self.__verifier = NgwConnectionVerifier(
            self.__temp_connection,
            fetch_title=fetch_title,
            parent=self,
        )
        self.__verifier.succeeded.connect(self.__handle_verifier_success)
        self.__verifier.failed.connect(self.__handle_verifier_failure)
        self.__verifier.finished.connect(self.__handle_verifier_finished)
        self.__lock_gui()
        self.__verifier.start()

    def __handle_verifier_success(
        self,
        verification_result: ConnectionVerificationResult,
    ) -> None:
        if self.__accept_on_verification_success:
            if not self.__prepare_auth_config_for_use(persist_auth=True):
                self.__accept_on_verification_success = False
                self.__validate()
                return

            self.__rename_created_auth_config(verification_result)
            self.__save_connection()
            self.accept()
            return

        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(
            self.tr("Connection successful"), Qgis.MessageLevel.Success
        )
        self._expand_message_bar()

    def __handle_verifier_failure(
        self,
        issue: Optional[ConnectionIssue],
    ) -> None:
        if self.__accept_on_verification_success:
            self.__ask_save_failed_connection(issue)
            return

        self.__handle_verifier_failure_message(issue)

    def __ask_save_failed_connection(
        self,
        issue: Optional[ConnectionIssue],
    ) -> None:
        message = self.tr(
            "Connection verification failed. Do you want to save this connection anyway?"
        )
        if issue is not None and issue.details:
            message = f"{message}\n\n{issue.details}"

        message_box = QMessageBox(
            QMessageBox.Icon.Warning,
            self.tr("Connection Failed"),
            message,
            QMessageBox.StandardButton.Cancel,
            self,
        )
        save_anyway_button = message_box.addButton(
            self.tr("Save Anyway"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        message_box.exec()
        if message_box.clickedButton() is not save_anyway_button:
            self.__accept_on_verification_success = False
            self.__handle_verifier_failure_message(issue)
            return

        if not self.__prepare_auth_config_for_use(persist_auth=True):
            self.__accept_on_verification_success = False
            self.__validate()
            return

        self.__save_connection()
        self.accept()

    def __handle_verifier_failure_message(
        self,
        issue: Optional[ConnectionIssue],
    ) -> None:
        if issue is None:
            self.set_message(
                self.tr("Connection verification failed."),
                Qgis.MessageLevel.Warning,
            )
            return

        message = issue.details
        if issue.resolution:
            message = f"{message} {issue.resolution}".strip()

        if issue.source == ConnectionIssueSource.CLIENT and len(message) == 0:
            message = self.tr("Connection verification failed.")

        message = self.__add_authentication_hint(message)

        if issue.source in (
            ConnectionIssueSource.NETWORK,
            ConnectionIssueSource.SERVER,
        ):
            self.__push_connection_failed_message_with_diagnostics(message)
        else:
            self.messageBar.clearWidgets()
            self.messageBar.pushMessage(
                self.tr("Connection failed"),
                message,
                Qgis.MessageLevel.Warning,
            )
        self._expand_message_bar()

    def __push_connection_failed_message_with_diagnostics(
        self,
        message: str,
    ) -> None:
        message_bar = cast(QgsMessageBar, self.messageBar)
        message_bar.clearWidgets()
        widget = message_bar.createMessage(
            self.tr("Connection failed"),
            message,
        )
        diagnostics_button = QPushButton(self.tr("Run diagnostics"), self)
        diagnostics_button.setIcon(material_icon("troubleshoot"))
        diagnostics_button.clicked.connect(
            self.__open_current_connection_diagnostics
        )
        widget.layout().addWidget(diagnostics_button)
        message_bar.pushWidget(widget, Qgis.MessageLevel.Warning)

    @pyqtSlot()
    def __open_current_connection_diagnostics(self) -> None:
        from nextgis_connect.legacy.ngw_connection.presentation.diagnostics.dialog import (
            NgwConnectionDiagnosticsDialog,
        )

        if not self.__prepare_auth_config_for_use(persist_auth=False):
            self.__validate()
            return

        try:
            dialog = NgwConnectionDiagnosticsDialog(
                self.__build_connection(), self
            )
            dialog.exec()
        finally:
            self.__remove_temporary_auth_config()

    def __handle_verifier_finished(self) -> None:
        self.__verifier = None
        self.__unlock_gui()
        if not self.__accept_on_verification_success:
            self.__remove_temporary_auth_config()
        self.__validate()

    def __save_connection(self):
        connection = self.__build_connection()
        self.__result_connection = connection
        if self.__save_on_accept:
            self.__connections_manager.upsert(connection)
            self.__connections_manager.save()

    def __is_duplicate_connection_url(self) -> bool:
        if self.__is_edit:
            return False

        existing_connection = self.__find_connection_by_url(
            self.__make_valid_url(self.urlLineEdit.text())
        )
        if existing_connection is None:
            return False

        connection_name = existing_connection.name or existing_connection.url
        message = self.tr(
            "A connection to this Web GIS already exists: <b>{}</b>. If"
            " you need to sign in as another user, edit the existing"
            " connection and create new authentication settings."
        ).format(connection_name)
        self.messageBar.clearWidgets()
        self.messageBar.pushMessage(
            self.tr("Connection already exists"),
            message,
            Qgis.MessageLevel.Warning,
        )
        self._expand_message_bar()

        return True

    def __build_connection(self) -> NgwConnection:
        url = self.__make_valid_url(self.urlLineEdit.text())
        if not self.__is_edit:
            self.__connection_id = self.__suggest_connection_id(url)

        name = self.nameLineEdit.text()
        auth_config_id = self.authWidget.configId()
        auth_config_id = auth_config_id if len(auth_config_id) > 0 else None

        return NgwConnection(self.__connection_id, name, url, auth_config_id)

    def __suggest_connection_id(self, url: str) -> str:
        existing_connection_ids = [
            connection.id
            for connection in self.__connections_manager.connections
            if connection.id != self.__connection_id
        ]
        return NgwConnection.suggested_id_for_url(
            url,
            existing_connection_ids,
            fallback_id=self.__connection_id,
        )

    def __find_connection_by_url(self, url: str) -> Optional[NgwConnection]:
        return self.__connections_manager.find_connection_by_url(
            url,
            exclude_connection_id=self.__connection_id,
        )

    def __lock_gui(self):
        if self.__accept_on_verification_success:
            self.__save_button.start()
        else:
            self.testConnectionButton.start()

        self.urlLineEdit.setEnabled(False)
        self.nameLineEdit.setEnabled(False)
        self.userComboBox.setEnabled(False)
        self.__auth_editor.setEnabled(False)
        self.authWidget.setEnabled(False)
        if self.__accept_on_verification_success:
            self.testConnectionButton.setEnabled(False)
        else:
            self.__save_button.setEnabled(False)
        self.__name_loader_button.setEnabled(False)
        self.__auth_filter_button.setEnabled(False)
        self.messageBar.clearWidgets()

    def __unlock_gui(self):
        if self.__save_button.is_loading():
            self.__save_button.stop()
        if self.testConnectionButton.is_loading():
            self.testConnectionButton.stop()

        self.urlLineEdit.setEnabled(True)
        self.nameLineEdit.setEnabled(True)
        self.userComboBox.setEnabled(True)
        self.__auth_editor.setEnabled(True)
        self.authWidget.setEnabled(True)
        self.testConnectionButton.setEnabled(True)
        self.__name_loader_button.setEnabled(True)
        self.__auth_filter_button.setEnabled(True)
        self.__save_button.setEnabled(True)

    def __normalized_auth_config_id(self) -> Optional[str]:
        auth_config_id = self.authWidget.configId()
        if len(auth_config_id) == 0:
            return None

        return auth_config_id

    def __set_name_field_visible(self, is_visible: bool) -> None:
        self.nameLabel.setVisible(is_visible)
        self.nameLineEdit.setVisible(is_visible)
        if hasattr(self, "_NgwConnectionEditDialog__name_loader_button"):
            self.__name_loader_button.setVisible(is_visible)
        self.nameRequiredLabel.setVisible(False)

    def __make_valid_url(self, url: str) -> str:
        return NgwConnection.normalize_url(url)

    @pyqtSlot(int)
    def __on_user_changed(self, index: int = -1) -> None:
        if not self.__confirm_auth_editor_reset(index):
            return

        choice = self.__current_login_choice()
        if choice is None:
            self.userComboBox.setToolTip("")
            self.__auth_editor.set_external_config_protection(False)
            self.authGroupBox.hide()
            self.__validate()
            self.__current_user_index = -1
            self.__schedule_resize()
            return

        self.__missing_auth_config_reason = None
        self.userComboBox.setToolTip(choice.tooltip)

        self.__auth_editor.set_resource_realm_visible(False)
        if choice.kind == LoginChoiceKind.GUEST:
            self.__auth_editor.set_external_config_protection(False)
            self.authWidget.setConfigId("")
            self.authGroupBox.hide()
            self.authWarningLabel.hide()
        elif self.__login_choice_method(choice) == "NextGIS":
            self.__auth_editor.set_external_config_protection(False)
            assert choice.auth_config_id is not None
            self.authWidget.setConfigId(choice.auth_config_id)
            self.authGroupBox.hide()
        elif choice.kind == LoginChoiceKind.EXISTING:
            assert choice.auth_config_id is not None
            self.authWidget.setConfigId(choice.auth_config_id)
            self.__auth_editor.set_config_id(choice.auth_config_id)
            self.__auth_editor.set_external_config_protection(
                self.__is_external_auth_config(choice.auth_config_id)
            )
            self.__auth_editor.set_additional_params_visible(True)
            self.__auth_editor.set_resource_realm_visible(False)
            self.authGroupBox.show()
        else:
            self.__auth_editor.set_external_config_protection(False)
            self.authWidget.setConfigId("")
            self.__auth_editor.prepare_new_config(
                self.__default_auth_config_name(),
                self.__default_auth_resource(),
            )
            self.__auth_editor.set_additional_params_visible(False)
            self.authGroupBox.show()

        self.__validate()
        self.__current_user_index = self.userComboBox.currentIndex()
        self.__schedule_resize()

    def __confirm_auth_editor_reset(self, new_index: int) -> bool:
        if self.__current_user_index < 0:
            return True

        if new_index == self.__current_user_index:
            return True

        previous_choice = cast(
            Optional[LoginChoice],
            self.userComboBox.itemData(self.__current_user_index),
        )
        if previous_choice is None:
            return True

        if not self.__choice_uses_auth_editor(previous_choice):
            return True

        if not self.__auth_editor.has_unsaved_changes():
            return True

        result = QMessageBox.question(
            self,
            self.tr("Discard authentication changes?"),
            self.tr(
                "Authentication settings contain unsaved changes. "
                "Discard them and change the sign-in type?"
            ),
            QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Discard:
            return True

        self.userComboBox.blockSignals(True)
        self.userComboBox.setCurrentIndex(self.__current_user_index)
        self.userComboBox.blockSignals(False)
        return False

    def __choice_uses_auth_editor(self, choice: LoginChoice) -> bool:
        return choice.kind == LoginChoiceKind.OTHER or (
            choice.kind == LoginChoiceKind.EXISTING
            and self.__login_choice_method(choice) != "NextGIS"
        )

    @pyqtSlot()
    def __open_help(self) -> None:
        domain = nextgis_domain("docs")
        QDesktopServices.openUrl(
            QUrl(f"{domain}/docs_ngconnect/source/ngc_install.html#new-config")
        )

    @pyqtSlot()
    def __open_nextgis_site(self) -> None:
        QDesktopServices.openUrl(QUrl(nextgis_domain()))

    def __load_username(self, config_id: str) -> Optional[str]:
        auth_manager = QgsApplication.authManager()
        method = auth_manager.configAuthMethodKey(config_id)
        if method not in ("Basic", "NextGIS"):
            return None

        is_loaded, config = auth_manager.loadAuthenticationConfig(
            config_id,
            QgsAuthMethodConfig(),
            full=True,
        )
        if not is_loaded:
            return None

        username = config.configMap().get("username", None)
        if not username:
            return None

        return username

    def __populate_user_choices(
        self,
        *,
        selected_auth_config_id: Optional[str] = None,
    ) -> None:
        selected_id = (
            self.authWidget.configId()
            if selected_auth_config_id is None
            else selected_auth_config_id or ""
        )
        previous_choice = self.__current_login_choice()

        if self.__is_external_auth_config(selected_id):
            self.__filter_auth_by_resource = False
            self.__auth_filter_button.blockSignals(True)
            self.__auth_filter_button.setChecked(False)
            self.__auth_filter_button.blockSignals(False)
            self.__update_auth_filter_button_tooltip()

        self.userComboBox.blockSignals(True)
        self.userComboBox.clear()

        guest_choice = LoginChoice(
            LoginChoiceKind.GUEST,
            self.tr("Guest access"),
        )
        self.userComboBox.addItem(guest_choice.title, guest_choice)
        self.__set_login_choice_item_tooltip(guest_choice)
        selected_index = -1
        if len(selected_id) == 0 and self.__should_keep_guest_selected(
            previous_choice
        ):
            selected_index = self.userComboBox.count() - 1

        nextgis_choices, basic_choices = self.__login_choices(selected_id)
        for choice in nextgis_choices:
            self.userComboBox.addItem(choice.title, choice)
            self.__set_login_choice_item_tooltip(choice)
            if choice.auth_config_id == selected_id:
                selected_index = self.userComboBox.count() - 1

        other_choice = LoginChoice(
            LoginChoiceKind.OTHER,
            self.tr("New sign-in option..."),
        )
        self.userComboBox.addItem(other_choice.title, other_choice)
        self.__set_login_choice_item_tooltip(other_choice)
        other_index = self.userComboBox.count() - 1
        if selected_index < 0 and not self.__is_edit and len(selected_id) == 0:
            selected_index = other_index

        for choice in basic_choices:
            self.userComboBox.addItem(choice.title, choice)
            self.__set_login_choice_item_tooltip(choice)
            if choice.auth_config_id == selected_id:
                selected_index = self.userComboBox.count() - 1

        if self.__missing_auth_config_reason is not None:
            selected_index = -1
        elif selected_index < 0:
            selected_index = other_index

        self.userComboBox.setCurrentIndex(selected_index)
        self.userComboBox.blockSignals(False)
        current_choice = self.__current_login_choice()
        if current_choice is None:
            self.authGroupBox.hide()
            self.__current_user_index = -1
            self.__validate()
            self.__schedule_resize()
            return

        if self.__is_same_login_choice(previous_choice, current_choice):
            self.__current_user_index = selected_index
            self.__validate()
            return

        self.__current_user_index = -1
        self.__on_user_changed(selected_index)

    def __set_login_choice_item_tooltip(self, choice: LoginChoice) -> None:
        if len(choice.tooltip) == 0:
            return

        self.userComboBox.setItemData(
            self.userComboBox.count() - 1,
            choice.tooltip,
            Qt.ItemDataRole.ToolTipRole,
        )

    def __should_keep_guest_selected(
        self,
        previous_choice: Optional[LoginChoice],
    ) -> bool:
        if self.__is_edit:
            return True

        return (
            previous_choice is not None
            and previous_choice.kind == LoginChoiceKind.GUEST
        )

    def __is_demo_connection_url(self) -> bool:
        raw_url = self.urlLineEdit.text().strip().lower()
        if raw_url == "demo":
            return True

        host = urlparse(self.__make_valid_url(raw_url)).netloc.lower()
        return host.startswith("demo.nextgis.")

    def __select_guest_for_demo_if_new_user_empty(self) -> None:
        if self.__is_edit or not self.__is_demo_connection_url():
            return

        choice = self.__current_login_choice()
        if choice is None or choice.kind != LoginChoiceKind.OTHER:
            return

        if self.__auth_editor.has_unsaved_changes():
            return

        self.__select_login_choice(LoginChoiceKind.GUEST)

    def __select_login_choice(self, kind: LoginChoiceKind) -> None:
        for index in range(self.userComboBox.count()):
            choice = cast(
                Optional[LoginChoice], self.userComboBox.itemData(index)
            )
            if choice is not None and choice.kind == kind:
                self.userComboBox.setCurrentIndex(index)
                return

    def __login_choices(
        self,
        current_auth_config_id: str,
    ) -> Tuple[List[LoginChoice], List[LoginChoice]]:
        resolver = LoginChoiceResolver(
            self.urlLineEdit.text(),
            is_edit=self.__is_edit,
            filter_by_resource=self.__filter_auth_by_resource,
            labels=LoginChoiceLabels(
                nextgis_qgis_account=self.tr("NextGIS QGIS account"),
                saved_basic_sign_in=self.tr("Saved sign-in"),
                basic_sign_in_tooltip_format=self.tr(
                    "{} - username and password"
                ),
            ),
        )
        return resolver.existing_choices(current_auth_config_id)

    def __is_external_auth_config(self, auth_config_id: str) -> bool:
        if not self.__is_edit:
            return False
        if len(auth_config_id) == 0 or auth_config_id == "NextGIS":
            return False

        config = QgsAuthMethodConfig()
        if not QgsApplication.authManager().loadAuthenticationConfig(
            auth_config_id, config, True
        ):
            return False

        resource = config.uri().strip()
        return len(resource) != 0 and NgwConnection.normalize_url(
            resource
        ) != NgwConnection.normalize_url(self.urlLineEdit.text())

    def __is_same_login_choice(
        self,
        left: Optional[LoginChoice],
        right: Optional[LoginChoice],
    ) -> bool:
        if left is None or right is None:
            return left is right

        return (
            left.kind == right.kind
            and left.method == right.method
            and left.auth_config_id == right.auth_config_id
        )

    @pyqtSlot(bool)
    def __set_auth_resource_filter_enabled(self, is_enabled: bool) -> None:
        self.__filter_auth_by_resource = is_enabled
        self.__update_auth_filter_button_tooltip()
        self.__populate_user_choices()

    @pyqtSlot(str)
    def __on_auth_config_deleted(self, config_id: str) -> None:
        if self.authWidget.configId() == config_id:
            self.authWidget.setConfigId("")

        if self.__is_edit:
            self.__connections_manager.set_connection_auth_config_id(
                self.__connection_id,
                None,
                persist=True,
            )

        self.__populate_user_choices(selected_auth_config_id="")

    def __update_auth_filter_button_tooltip(self) -> None:
        if self.__filter_auth_by_resource:
            self.__auth_filter_button.setIcon(material_icon("visibility"))
            self.__auth_filter_button.setToolTip(self.tr("Show all users"))
            return

        self.__auth_filter_button.setIcon(material_icon("visibility_off"))
        self.__auth_filter_button.setToolTip(
            self.tr("Show users for this Web GIS")
        )

    def __current_login_choice(self) -> Optional[LoginChoice]:
        return cast(Optional[LoginChoice], self.userComboBox.currentData())

    def __prepare_auth_config_for_use(self, *, persist_auth: bool) -> bool:
        choice = self.__current_login_choice()
        self.__created_auth_config_id = None
        self.__remove_temporary_auth_config()
        if choice is None or choice.kind == LoginChoiceKind.GUEST:
            self.authWidget.setConfigId("")
            return True

        if self.__login_choice_method(choice) == "NextGIS":
            if not NextgisQgisUserAvailability.is_available():
                return False

            self.authWidget.setConfigId(choice.auth_config_id or "NextGIS")
            return True

        if not self.__auth_editor.is_valid():
            return False

        if choice.kind == LoginChoiceKind.OTHER:
            self.__auth_editor.set_connection_url(
                self.__default_auth_resource(),
                force=True,
            )
            if persist_auth and not self.__confirm_duplicate_auth_user():
                return False
        elif len(self.__auth_editor.resource.strip()) == 0:
            self.__auth_editor.set_connection_url(
                self.__default_auth_resource(),
                force=True,
            )

        if not self.__confirm_external_auth_credentials_update_if_needed(
            choice
        ):
            return False

        if persist_auth:
            if not self.__auth_editor.save_config():
                return False

            config_id = self.__auth_editor.config_id
        else:
            config_id = self.__auth_editor.save_temporary_config()
            if config_id is None:
                return False

        if len(config_id) == 0:
            return False

        if choice.kind == LoginChoiceKind.OTHER and persist_auth:
            self.__created_auth_config_id = config_id
        elif not persist_auth:
            self.__temporary_auth_config_id = config_id
            self.__temporary_previous_auth_config_id = (
                self.authWidget.configId()
            )

        self.authWidget.setConfigId(config_id)
        if persist_auth and choice.kind != LoginChoiceKind.OTHER:
            self.__populate_user_choices(selected_auth_config_id=config_id)
        return True

    def __confirm_external_auth_credentials_update_if_needed(
        self,
        choice: LoginChoice,
    ) -> bool:
        auth_config_id = choice.auth_config_id or ""
        if (
            choice.kind != LoginChoiceKind.EXISTING
            or not self.__is_external_auth_config(auth_config_id)
            or not self.__auth_editor.credentials_changed()
        ):
            return True

        credentials = (
            auth_config_id,
            self.__auth_editor.username_lineedit.text(),
            self.__auth_editor.password_lineedit.text(),
        )
        if credentials == self.__confirmed_external_auth_credentials:
            return True

        if not self.__confirm_external_auth_credentials_update(auth_config_id):
            return False

        self.__confirmed_external_auth_credentials = credentials
        return True

    def __confirm_external_auth_credentials_update(
        self,
        auth_config_id: str,
    ) -> bool:
        affected_web_gis_count = (
            self.__connections_manager.other_web_gis_count_for_auth_config(
                auth_config_id,
                self.urlLineEdit.text(),
            )
        )
        result = QMessageBox.question(
            self,
            self.tr("Update shared sign-in settings?"),
            self.tr(
                "Changing the login or password will affect {count} other Web GIS. Continue?"
            ).format(count=affected_web_gis_count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    def __remove_temporary_auth_config(self) -> None:
        if self.__temporary_auth_config_id is None:
            self.__temporary_previous_auth_config_id = None
            return

        temporary_auth_config_id = self.__temporary_auth_config_id
        previous_auth_config_id = self.__temporary_previous_auth_config_id
        self.__temporary_auth_config_id = None
        self.__temporary_previous_auth_config_id = None
        QgsApplication.authManager().removeAuthenticationConfig(
            temporary_auth_config_id
        )
        if self.authWidget.configId() == temporary_auth_config_id:
            self.authWidget.setConfigId(previous_auth_config_id or "")

    def __confirm_duplicate_auth_user(self) -> bool:
        duplicate_auth_ids = self.__duplicate_basic_auth_ids_for_current_user()
        if len(duplicate_auth_ids) == 0:
            return True

        result = QMessageBox.question(
            self,
            self.tr("Create duplicate user?"),
            self.tr(
                "A saved user with the same NextGIS ID already exists for this Web GIS. "
                "Do you want to create another one?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result != QMessageBox.StandardButton.Yes:
            return False

        self.__auth_editor.set_connection_name(
            self.__unique_duplicate_auth_name(),
            force=True,
        )
        return True

    def __duplicate_basic_auth_ids_for_current_user(self) -> List[str]:
        username = self.__auth_editor.username_lineedit.text().strip()
        resource = NgwConnection.normalize_url(self.__auth_editor.resource)
        if len(username) == 0 or len(resource) == 0:
            return []

        duplicates = []
        auth_manager = QgsApplication.authManager()
        for (
            config_id,
            config,
        ) in auth_manager.availableAuthMethodConfigs().items():
            method = config.method() or auth_manager.configAuthMethodKey(
                config_id
            )
            if method != "Basic":
                continue

            loaded_config = config
            if len(config.configMap().get("username", "")) == 0:
                is_loaded, loaded_config = (
                    auth_manager.loadAuthenticationConfig(
                        config_id,
                        QgsAuthMethodConfig(),
                        full=True,
                    )
                )
                if not is_loaded:
                    continue

            if (
                loaded_config.configMap().get("username", "").strip()
                != username
            ):
                continue

            if NgwConnection.normalize_url(loaded_config.uri()) != resource:
                continue

            duplicates.append(config_id)

        return duplicates

    def __unique_duplicate_auth_name(self) -> str:
        base_name = self.__auth_editor.name_lineedit.text().strip()
        if len(base_name) == 0:
            base_name = self.__default_auth_config_name()
        existing_names = {
            config.name()
            for config in QgsApplication.authManager()
            .availableAuthMethodConfigs()
            .values()
        }
        if base_name not in existing_names:
            return base_name

        index = 2
        while True:
            name = f"{base_name} ({index})"
            if name not in existing_names:
                return name
            index += 1

    def __default_auth_config_name(self) -> str:
        suggested_name = self.__suggested_connection_name(
            self.urlLineEdit.text()
        )
        if len(suggested_name) != 0:
            return suggested_name

        if len(self.nameLineEdit.text()) != 0:
            return self.nameLineEdit.text()

        return self.tr("NextGIS Web")

    def __rename_created_auth_config(
        self,
        verification_result: ConnectionVerificationResult,
    ) -> None:
        if self.__created_auth_config_id is None:
            return

        if self.__auth_editor.config_id != self.__created_auth_config_id:
            return

        display_name = verification_result.current_user.display_name
        if len(display_name) == 0:
            display_name = verification_result.current_user.keyname

        auth_name = self.tr("{user_name} ({connection_name})").format(
            connection_name=self.__suggested_connection_name(
                self.urlLineEdit.text()
            ),
            user_name=display_name,
        )
        self.__auth_editor.set_connection_name(auth_name, force=True)
        self.__auth_editor.save_config()
        self.__created_auth_config_id = None

    def __default_auth_resource(self) -> str:
        raw_url = self.urlLineEdit.text().strip()
        if len(raw_url) == 0:
            return ""

        return NgwConnection.normalize_url(raw_url)

    def __current_username(self) -> str:
        choice = self.__current_login_choice()
        if choice is None or choice.kind == LoginChoiceKind.GUEST:
            return ""

        if self.__login_choice_method(choice) == "NextGIS":
            return ""

        if self.__choice_uses_auth_editor(choice):
            username = self.__auth_editor.username_lineedit.text().strip()
            if len(username) != 0:
                return username

        if choice.auth_config_id is None:
            return ""

        return self.__load_username(choice.auth_config_id) or ""

    def __add_authentication_hint(self, message: str) -> str:
        username = self.__current_username()
        if "@gmail.com" not in username:
            return message

        docs_link = (
            nextgis_domain("docs")
            + "/docs_ngconnect/source/ngc_install.html#new-config"
        )
        hint = self.tr(
            "If you signed up for NextGIS via <i>Google</i>, "
            "you need a separate password for NextGIS Connect. "
            "Use <i>Forgot password</i> to set one. See "
            "<a href='{}'>documentation</a> for more details."
        ).format(docs_link)
        if len(message) == 0:
            return hint

        return f"{message} {hint}"

    def _expand_message_bar(self) -> None:
        QTimer.singleShot(0, self._expand_message_bar_later)

    def _expand_message_bar_later(self) -> None:
        message_bar = cast(QgsMessageBar, self.messageBar)
        message_bar.setSizePolicy(
            message_bar.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Preferred,
        )
        if len(message_bar.items()) == 0:
            self.__sync_message_bar_visibility()
            return

        item = message_bar.items()[-1]
        browser = item.findChild(QTextBrowser)
        if browser is None:
            self.__schedule_resize()
            return

        browser.setSizePolicy(
            browser.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Fixed,
        )
        browser.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        margins = browser.contentsMargins()
        text_width = browser.viewport().width()
        if text_width <= 0:
            text_width = browser.width() - 2 * browser.frameWidth()

        browser.document().setTextWidth(max(1, text_width))
        text_height = browser.document().size().height()
        text_browser_height = ceil(
            text_height
            + margins.top()
            + margins.bottom()
            + 2 * browser.frameWidth()
            + 2
        )
        browser.setFixedHeight(text_browser_height)
        self.__schedule_resize()

    def __sync_message_bar_visibility(self, *_) -> None:
        self.messageBar.setVisible(len(self.messageBar.items()) != 0)
        self.__schedule_resize()
