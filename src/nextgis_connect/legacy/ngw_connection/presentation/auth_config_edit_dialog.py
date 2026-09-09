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

from pathlib import Path
from typing import Dict, Optional, Tuple, cast

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw_connection.presentation.auth_config_id_edit import (
    AuthConfigIdEdit,
)
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.utils import utm_tags
from nextgis_connect.ui_kit.icons import qgis_icon

from .dialog_header_widget import NextgisDialogHeaderWidget

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "forms" / "auth_config_edit_dialog.ui")
)


class AuthConfigEditorWidget(QWidget, WIDGET):
    validityChanged = pyqtSignal(bool)
    saved = pyqtSignal()
    deleted = pyqtSignal(str)
    layoutChanged = pyqtSignal()

    __auth_config_id_edit: AuthConfigIdEdit
    __config_id: str
    __config_map: Dict[str, str]
    __auth_method_key: str
    __is_embedded: bool
    __is_valid: bool
    __clean_state: Tuple[str, str, str, str, str, str]
    __resource_realm_visible: bool
    __username_completer_model: QStringListModel
    __delete_button: QPushButton

    def __init__(
        self,
        config_id: str = "",
        parent: Optional[QWidget] = None,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.__config_id = config_id
        self.__config_map = {}
        self.__auth_method_key = "Basic"
        self.__is_embedded = embedded
        self.__is_valid = False
        self.__clean_state = ("", "", "", "", "", "")
        self.__resource_realm_visible = True

        self.setupUi(self)
        self.__init_ui()
        self.set_embedded_mode(embedded)
        self.set_config_id(config_id)

    @property
    def config_id(self) -> str:
        return self.__config_id

    @property
    def auth_method_key(self) -> str:
        return self.__auth_method_key

    @property
    def resource(self) -> str:
        return self.resource_lineedit.text()

    def is_valid(self) -> bool:
        return self.__is_valid

    def set_connection_name(
        self,
        connection_name: str,
        *,
        force: bool = False,
    ) -> None:
        if not force and (
            len(self.__config_id) != 0 or len(self.name_lineedit.text()) != 0
        ):
            return

        self.name_lineedit.setText(connection_name)

    def set_connection_url(
        self,
        connection_url: str,
        *,
        force: bool = False,
    ) -> None:
        if not force and (
            len(self.__config_id) != 0
            or len(self.resource_lineedit.text()) != 0
        ):
            return

        self.resource_lineedit.setText(connection_url)

    def prepare_new_config(
        self,
        connection_name: str,
        connection_url: str,
    ) -> None:
        default_name = (
            connection_name
            if len(connection_name) != 0
            else self.tr("NextGIS Web")
        )
        self.set_config_id("")
        self.set_connection_name(default_name, force=True)
        self.set_connection_url(connection_url, force=True)
        self.__mark_clean()

    def mark_clean(self) -> None:
        self.__mark_clean()

    def set_additional_params_visible(self, is_visible: bool) -> None:
        self.additional_groupbox.setVisible(is_visible)
        self.__sync_additional_content_visibility()
        self.__schedule_resize()

    def set_resource_realm_visible(self, is_visible: bool) -> None:
        self.__resource_realm_visible = is_visible
        self.label_6.setVisible(is_visible)
        self.resource_lineedit.setVisible(is_visible)
        self.label.setVisible(is_visible)
        self.realm_lineedit.setVisible(is_visible)
        self.formLayout_2.setVerticalSpacing(-1 if is_visible else 0)
        self.__update_group_box_minimum_heights()
        self.__schedule_resize()

    def has_unsaved_changes(self) -> bool:
        return self.__current_state() != self.__clean_state

    def set_embedded_mode(self, embedded: bool) -> None:
        self.__is_embedded = embedded
        self.__header_widget.setVisible(not embedded)
        self.button_box.setVisible(not embedded)

        body_layout = cast(QVBoxLayout, self.body.layout())
        body_layout.setContentsMargins(0, 0 if embedded else 3, 0, 0)
        auth_params_margins = (0, 0, 0, 0) if embedded else (4, 4, 4, 4)
        self.auth_params_groupbox.layout().setContentsMargins(
            *auth_params_margins
        )
        self.additional_groupbox.layout().setContentsMargins(4, 4, 4, 4)
        self.__update_auth_config_id_visibility()
        self.layoutChanged.emit()

    def set_config_id(self, config_id: str) -> None:
        self.__config_id = config_id
        self.__auth_method_key = "Basic"
        self.__config_map = {}
        self.__clear_error()
        self.__clear_all()

        is_empty = len(config_id) == 0
        self.__auth_config_id_edit.reset_auth_config_id(
            config_id,
            allow_empty=is_empty,
        )
        if is_empty:
            self.__update_auth_config_id_visibility()
            self.__validate_auth()
            self.__mark_clean()
            return

        if not self.__load_config():
            self.__validate_auth()
            self.__mark_clean()
            return

        self.__update_auth_config_id_visibility()
        self.__validate_auth()
        self.__mark_clean()

    @pyqtSlot()
    def reset_config(self) -> None:
        self.set_config_id(self.__config_id)

    @pyqtSlot(result=bool)
    def save_config(self) -> bool:
        if not self.is_valid():
            return False

        auth_manager = QgsApplication.authManager()
        if not auth_manager.setMasterPassword(True):
            return False

        auth_method = auth_manager.authMethod(self.__auth_method_key)
        if auth_method is None:
            logger.error(
                f"Save auth config FAILED: method {self.__auth_method_key} is not available"
            )
            return False

        method_config = QgsAuthMethodConfig()
        method_config.setName(self.name_lineedit.text())
        method_config.setUri(self.resource_lineedit.text())
        method_config.setMethod(auth_method.key())
        method_config.setVersion(auth_method.version())
        method_config.setConfigMap(self.__auth_config_map())

        if not method_config.isValid():
            logger.error("Save auth config FAILED: config invalid")
            return False

        requested_config_id = self.__auth_config_id_edit.config_id()
        if not self.__store_auth_config(method_config, requested_config_id):
            return False

        self.__mark_clean()
        self.saved.emit()
        return True

    def save_temporary_config(self) -> Optional[str]:
        if not self.is_valid():
            return None

        auth_manager = QgsApplication.authManager()
        if not auth_manager.setMasterPassword(True):
            return None

        auth_method = auth_manager.authMethod(self.__auth_method_key)
        if auth_method is None:
            logger.error(
                f"Save temporary auth config FAILED: method {self.__auth_method_key} is not available"
            )
            return None

        method_config = QgsAuthMethodConfig()
        method_config.setName(self.name_lineedit.text())
        method_config.setUri(self.resource_lineedit.text())
        method_config.setMethod(auth_method.key())
        method_config.setVersion(auth_method.version())
        method_config.setConfigMap(self.__auth_config_map())

        if not method_config.isValid():
            logger.error("Save temporary auth config FAILED: config invalid")
            return None

        if not auth_manager.storeAuthenticationConfig(method_config):
            logger.error("Storing temporary auth config FAILED")
            return None

        return method_config.id()

    def __init_ui(self) -> None:
        root_layout = cast(QVBoxLayout, self.layout())
        header_index = root_layout.indexOf(self.header)

        self.__header_widget = NextgisDialogHeaderWidget(self)
        self.__header_widget.set_title(self.tr("Authentication"))
        self.__header_widget.set_subtitle(
            self.tr("Manage saved sign-in settings for this connection.")
        )
        root_layout.insertWidget(header_index, self.__header_widget)
        root_layout.removeWidget(self.header)
        self.header.hide()

        body_layout = cast(QVBoxLayout, self.body.layout())
        self.__error_label = QLabel(self)
        self.__error_label.setWordWrap(True)
        self.__error_label.hide()
        body_layout.insertWidget(0, self.__error_label)
        self.__stabilize_layout_spacing()

        self.forgot_label.linkActivated.connect(self.__forgot_password_clicked)
        self.__setup_username_completer()

        self.__auth_config_id_edit = AuthConfigIdEdit(self)
        self.id_layout.addWidget(self.__auth_config_id_edit)
        self.__auth_config_id_edit.validityChanged.connect(
            self.__validate_auth
        )
        self.__setup_delete_button()
        self.__stabilize_field_heights()

        additional_groupbox = cast(
            QgsCollapsibleGroupBox,
            self.additional_groupbox,
        )
        additional_groupbox.layout().setContentsMargins(4, 4, 4, 4)
        additional_groupbox.collapsedStateChanged.connect(
            self.__on_additional_collapsed_state_changed
        )
        additional_groupbox.setCollapsed(True)
        self.__set_additional_content_visible(False)

        self.name_lineedit.textChanged.connect(self.__validate_auth)
        self.username_lineedit.textChanged.connect(self.__validate_auth)
        self.password_lineedit.textChanged.connect(self.__validate_auth)
        self.realm_lineedit.textChanged.connect(self.__validate_auth)

        reset_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Reset
        )
        save_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        if reset_button is not None:
            reset_button.clicked.connect(self.reset_config)
        if save_button is not None:
            save_button.clicked.connect(self.save_config)

        self.username_lineedit.setFocus()
        self.__schedule_resize()

    def __update_auth_config_id_visibility(self) -> None:
        is_visible = (
            not self.__is_embedded or len(self.__config_id) != 0
        ) and not self.__is_additional_collapsed()
        self.label_5.setVisible(is_visible)
        self.__auth_config_id_edit.setVisible(is_visible)
        self.__delete_button.setVisible(
            len(self.__config_id) != 0 and not self.__is_additional_collapsed()
        )

    def __setup_delete_button(self) -> None:
        self.__delete_button = QPushButton(self.tr("Delete"), self)
        self.__delete_button.setIcon(qgis_icon("mActionDeleteSelected.svg"))
        self.__delete_button.setToolTip(
            self.tr("Delete these authentication settings")
        )
        self.__delete_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.__delete_button.clicked.connect(self.__delete_config)
        delete_widget = QWidget(self.additional_groupbox)
        delete_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        delete_layout = QHBoxLayout()
        delete_layout.setContentsMargins(0, 8, 0, 0)
        delete_layout.setSpacing(0)
        delete_layout.addWidget(self.__delete_button)
        delete_widget.setLayout(delete_layout)
        self.additional_groupbox.layout().addRow(delete_widget)

    def __stabilize_field_heights(self) -> None:
        fields = (
            self.name_lineedit,
            self.username_lineedit,
            self.password_lineedit,
            self.resource_lineedit,
            self.realm_lineedit,
            self.__auth_config_id_edit,
        )
        height = max(field.sizeHint().height() for field in fields)
        for field in fields:
            field.setMinimumHeight(height)
            field.setSizePolicy(
                field.sizePolicy().horizontalPolicy(),
                QSizePolicy.Policy.Preferred,
            )

    def __setup_username_completer(self) -> None:
        self.__username_completer_model = QStringListModel(self)
        completer = QCompleter(self.__username_completer_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.InlineCompletion)
        self.username_lineedit.setCompleter(completer)
        self.username_lineedit.textEdited.connect(
            self.__update_username_completions
        )
        self.__update_username_completions(self.username_lineedit.text())

    @pyqtSlot(str)
    def __update_username_completions(self, text: str) -> None:
        completions = []
        stripped_text = text.strip()
        if len(stripped_text) != 0 and "administrator".startswith(
            stripped_text.lower()
        ):
            completions.append("administrator")

        if "@" in stripped_text:
            local_part, domain_part = stripped_text.rsplit("@", 1)
            domain_part = domain_part.lower()
            if len(local_part) != 0 and len(domain_part) >= 2:
                for domain in ("nextgis.com", "gmail.com"):
                    if domain.startswith(domain_part):
                        completions.append(f"{local_part}@{domain}")

        self.__username_completer_model.setStringList(completions)

    def __stabilize_layout_spacing(self) -> None:
        if hasattr(self, "verticalSpacer"):
            self.verticalSpacer.changeSize(
                0,
                0,
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )
        self.auth_params_groupbox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.additional_groupbox.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )

    @pyqtSlot(bool)
    def __on_additional_collapsed_state_changed(self, collapsed: bool) -> None:
        self.__set_additional_content_visible(not collapsed)
        self.__update_group_box_minimum_heights()
        self.__delayed_resize()

    def __set_additional_content_visible(self, is_visible: bool) -> None:
        layout = self.additional_groupbox.layout()
        if layout is None:
            return

        self.__set_layout_content_visible(layout, is_visible)
        self.__update_auth_config_id_visibility()
        self.__update_group_box_minimum_heights()

    def __sync_additional_content_visibility(self) -> None:
        layout = self.additional_groupbox.layout()
        if layout is None:
            return

        self.__set_layout_content_visible(
            layout,
            not self.__is_additional_collapsed(),
        )
        self.__update_auth_config_id_visibility()

    def __is_additional_collapsed(self) -> bool:
        if hasattr(self.additional_groupbox, "isCollapsed"):
            return self.additional_groupbox.isCollapsed()

        return True

    def __set_layout_content_visible(
        self,
        layout: QLayout,
        is_visible: bool,
    ) -> None:
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child_layout = item.layout()
            widget = item.widget()

            if child_layout is not None:
                self.__set_layout_content_visible(child_layout, is_visible)

            if widget is not None:
                if widget in (self.label_5, self.__auth_config_id_edit):
                    continue
                if widget is self.__delete_button:
                    widget.setVisible(
                        is_visible and len(self.__config_id) != 0
                    )
                    continue
                if widget in (
                    self.label_6,
                    self.resource_lineedit,
                    self.label,
                    self.realm_lineedit,
                ):
                    widget.setVisible(
                        is_visible and self.__resource_realm_visible
                    )
                    continue
                widget.setVisible(is_visible)

    def __update_group_box_minimum_heights(self) -> None:
        for group_box in (self.auth_params_groupbox, self.additional_groupbox):
            if not group_box.isVisible():
                group_box.setMinimumHeight(0)
                continue

            group_box.setMinimumHeight(0)
            group_box.layout().invalidate()
            group_box.layout().activate()
            group_box.setMinimumHeight(group_box.sizeHint().height())
            group_box.updateGeometry()

    @pyqtSlot()
    def __delayed_resize(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

        self.__update_group_box_minimum_heights()

        if self.__is_embedded:
            self.updateGeometry()
            self.layoutChanged.emit()
            return

        minimum_size = self.minimumSizeHint()
        preferred_size = (
            layout.sizeHint() if layout is not None else self.sizeHint()
        )
        target_width = max(self.width(), minimum_size.width())
        target_height = preferred_size.height()
        if layout is not None and layout.hasHeightForWidth():
            target_height = layout.heightForWidth(target_width)

        self.resize(
            QSize(
                target_width,
                max(target_height, minimum_size.height()),
            )
        )
        self.layoutChanged.emit()

    @pyqtSlot(bool)
    def __schedule_resize(self, _: bool = False) -> None:
        QTimer.singleShot(0, self.__delayed_resize)
        if self.__is_embedded:
            return

        QTimer.singleShot(25, self.__delayed_resize)

    def __load_config(self) -> bool:
        auth_manager = QgsApplication.authManager()
        if auth_manager.isDisabled():
            self.__set_error(auth_manager.disabledMessage())
            return False

        method = auth_manager.configAuthMethodKey(self.__config_id)
        if method != "Basic":
            logger.error(
                f"Loading FAILED for authcfg ({self.__config_id}): unsupported method {method}"
            )
            self.__set_error(
                self.tr(
                    "Only Basic authentication settings can be edited here."
                )
            )
            return False

        if not auth_manager.setMasterPassword(True):
            self.__set_error(
                self.tr(
                    "Unlock the QGIS authentication database to edit saved credentials."
                )
            )
            return False

        method_config = QgsAuthMethodConfig()
        is_loaded = auth_manager.loadAuthenticationConfig(
            self.__config_id,
            method_config,
            True,
        )
        if not is_loaded:
            logger.error(f"Loading FAILED for authcfg: {self.__config_id}")
            self.__set_error(
                self.tr(
                    "Authentication settings could not be loaded: {}"
                ).format(self.__config_id)
            )
            return False

        if not method_config.isValid():
            logger.error(
                f"Loading FAILED for authcfg ({self.__config_id}): invalid config"
            )
            self.__set_error(
                self.tr("The saved authentication settings are invalid.")
            )
            return False

        self.__auth_method_key = method
        self.name_lineedit.setText(method_config.name())
        self.resource_lineedit.setText(method_config.uri())
        self.__auth_config_id_edit.reset_auth_config_id(
            method_config.id(),
            allow_empty=False,
        )
        self.__load_auth_config(method_config.configMap())
        return True

    def __load_auth_config(self, config_map: Dict[str, str]) -> None:
        self.__config_map = dict(config_map)
        self.username_lineedit.setText(config_map.get("username", ""))
        self.password_lineedit.setText(config_map.get("password", ""))
        self.realm_lineedit.setText(config_map.get("realm", ""))

    def __auth_config_map(self) -> Dict[str, str]:
        return {
            "username": self.username_lineedit.text(),
            "password": self.password_lineedit.text(),
            "realm": self.realm_lineedit.text(),
        }

    def __current_state(self) -> Tuple[str, str, str, str, str, str]:
        return (
            self.name_lineedit.text(),
            self.username_lineedit.text(),
            self.password_lineedit.text(),
            self.resource_lineedit.text(),
            self.realm_lineedit.text(),
            self.__auth_config_id_edit.auth_config_id_text(),
        )

    def __mark_clean(self) -> None:
        self.__clean_state = self.__current_state()

    def __store_auth_config(
        self,
        method_config: QgsAuthMethodConfig,
        requested_config_id: str,
    ) -> bool:
        auth_manager = QgsApplication.authManager()
        original_config_id = self.__config_id

        if len(original_config_id) == 0:
            if len(requested_config_id) != 0:
                method_config.setId(requested_config_id)

            is_added = auth_manager.storeAuthenticationConfig(method_config)
            if not is_added:
                if len(requested_config_id) != 0:
                    logger.error(
                        "Storing new auth config with user-created unique ID FAILED"
                    )
                else:
                    logger.error("Storing new auth config FAILED")
                return False

            self.__config_id = method_config.id()
            self.__auth_config_id_edit.reset_auth_config_id(
                self.__config_id,
                allow_empty=False,
            )
            return True

        if original_config_id == requested_config_id:
            method_config.setId(requested_config_id)
            is_updated = auth_manager.updateAuthenticationConfig(method_config)
            if not is_updated:
                logger.error(
                    f"Updating auth config FAILED for authcfg: {requested_config_id}"
                )
            return is_updated

        method_config.setId(requested_config_id)
        is_added = auth_manager.storeAuthenticationConfig(method_config)
        if not is_added:
            logger.error(
                "Storing new auth config with user-created unique ID FAILED"
            )
            return False

        is_deleted = auth_manager.removeAuthenticationConfig(
            original_config_id
        )
        if not is_deleted:
            logger.error("Removal of older auth config FAILED")

        self.__config_id = requested_config_id
        self.__auth_config_id_edit.reset_auth_config_id(
            self.__config_id,
            allow_empty=False,
        )
        return True

    def __clear_all(self) -> None:
        self.name_lineedit.clear()
        self.resource_lineedit.clear()
        self.__auth_config_id_edit.reset_auth_config_id("")
        self.username_lineedit.clear()
        self.password_lineedit.clear()
        self.realm_lineedit.clear()

    def __set_error(self, message: str) -> None:
        self.__error_label.setText(message)
        self.__error_label.setVisible(len(message) != 0)
        self.auth_params_groupbox.setVisible(len(message) == 0)
        self.additional_groupbox.setVisible(len(message) == 0)

    def __clear_error(self) -> None:
        self.__error_label.clear()
        self.__error_label.hide()
        self.auth_params_groupbox.show()
        self.additional_groupbox.show()
        self.__sync_additional_content_visibility()

    @pyqtSlot()
    def __validate_auth(self) -> None:
        is_valid = (
            not self.__error_label.isVisible()
            and len(self.name_lineedit.text()) != 0
            and len(self.username_lineedit.text()) != 0
            and self.__auth_config_id_edit.validate()
        )

        save_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        if save_button is not None:
            save_button.setEnabled(is_valid)

        if self.__is_valid != is_valid:
            self.__is_valid = is_valid
            self.validityChanged.emit(is_valid)

    @pyqtSlot()
    def __delete_config(self) -> None:
        if len(self.__config_id) == 0:
            return

        config_id = self.__config_id
        message_box = QMessageBox(
            QMessageBox.Icon.Warning,
            self.tr("Delete authentication settings?"),
            self.tr(
                "Authentication settings will be deleted permanently. "
                "Do you want to continue?"
            ),
            QMessageBox.StandardButton.Cancel,
            self,
        )
        delete_button = message_box.addButton(
            self.tr("Delete"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        message_box.exec()
        if message_box.clickedButton() is not delete_button:
            return

        if not QgsApplication.authManager().removeAuthenticationConfig(
            config_id
        ):
            logger.error(f"Removal of auth config FAILED: {config_id}")
            return

        self.set_config_id("")
        self.deleted.emit(config_id)

    @pyqtSlot(str)
    def __forgot_password_clicked(self, url: str) -> None:
        if url != "#forgot":
            logger.error(f"Unexpected ID for forgot password: {url}")
            return

        username = self.username_lineedit.text()
        if "@" not in username:
            username = ""
        utm = utm_tags("authentication")
        url = f"https://my.nextgis.com/password/reset/?email={username}&{utm}"
        logger.debug(f"Open reset link: {url}")
        QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot()
    def __sign_up(self) -> None:
        utm = utm_tags("authentication")
        signup_url = f"https://my.nextgis.com/signup/?{utm}"
        QDesktopServices.openUrl(QUrl(signup_url))


class AuthConfigEditDialog(QDialog):
    def __init__(
        self,
        config_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Authentication"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.__editor = AuthConfigEditorWidget(config_id, self)
        layout.addWidget(self.__editor)

        self.__editor.saved.connect(self.accept)
        self.__editor.button_box.rejected.connect(self.reject)
        self.__editor.layoutChanged.connect(self.__schedule_resize)

        QTimer.singleShot(0, self.__schedule_resize)

    @property
    def config_id(self) -> str:
        return self.__editor.config_id

    def set_connection_name(self, connection_name: str) -> None:
        self.__editor.set_connection_name(connection_name, force=True)

    def set_connection_url(self, connection_url: str) -> None:
        self.__editor.set_connection_url(connection_url, force=True)

    def editor(self) -> AuthConfigEditorWidget:
        return self.__editor

    @pyqtSlot()
    def __schedule_resize(self) -> None:
        QTimer.singleShot(0, self.__delayed_resize)
        QTimer.singleShot(25, self.__delayed_resize)

    @pyqtSlot()
    def __delayed_resize(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

        minimum_size = self.minimumSizeHint()
        preferred_size = (
            layout.sizeHint() if layout is not None else self.sizeHint()
        )
        target_width = max(self.width(), minimum_size.width())
        target_height = preferred_size.height()
        if layout is not None and layout.hasHeightForWidth():
            target_height = layout.heightForWidth(target_width)

        self.resize(
            QSize(
                target_width,
                max(target_height, minimum_size.height()),
            )
        )
