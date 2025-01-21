from pathlib import Path
from typing import Dict, Optional, cast

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings
from qgis.gui import QgsCollapsibleGroupBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QLocale, QSize, QTimer, QUrl, pyqtSlot
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.logging import logger
from nextgis_connect.ngw_connection.auth_config_id_edit import AuthConfigIdEdit
from nextgis_connect.ngw_connection.ngw_button import NgwButton

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "auth_config_edit_dialog.ui")
)


class AuthConfigEditDialog(QDialog, WIDGET):
    """
    Note: Based on QgsAuthBasicEdit
    """

    __auth_config_id_edit: AuthConfigIdEdit

    __config_id: str
    __config_map: Dict[str, str]
    __is_credentials_valid: bool

    def __init__(
        self, config_id: str, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.__config_id = config_id
        self.__config_map = {}
        self.__is_credentials_valid = False

        if not self.__can_load_config():
            self.__init_error_ui()
            return

        self.__init_ui()
        self.__load_config()
        self.__validate_auth()

    @property
    def config_id(self) -> str:
        return self.__config_id

    def set_connection_name(self, connection_name: str) -> None:
        self.name_lineedit.setText(connection_name)

    def set_connection_url(self, connection_url: str) -> None:
        self.resource_lineedit.setText(connection_url)

    @pyqtSlot()
    def reset_config(self) -> None:
        self.__clear_all()
        self.__load_config()
        self.__validate_auth()

    @pyqtSlot()
    def save_config(self) -> None:
        if not QgsApplication.authManager().setMasterPassword(True):
            return

        auth_method = QgsApplication.authManager().authMethod("Basic")
        assert auth_method is not None

        method_config = QgsAuthMethodConfig()
        method_config.setName(self.name_lineedit.text())
        method_config.setUri(self.resource_lineedit.text())
        method_config.setMethod(auth_method.key())
        method_config.setVersion(auth_method.version())
        method_config.setConfigMap(self.__basic_map())

        if not method_config.isValid():
            logger.error("Save auth config FAILED: config invalid")
            return

        config_id = self.__auth_config_id_edit.configId()
        if len(self.__config_id) == 0:
            if len(config_id) != 0:
                method_config.setId(config_id)

            is_added = QgsApplication.authManager().storeAuthenticationConfig(
                method_config
            )
            if is_added:
                self.__config_id = method_config.id()
            elif len(config_id) != 0:
                logger.error(
                    "Storing new auth config with user-created unique ID FAILED"
                )
            else:
                logger.error("Storing new auth config FAILED")
        else:
            if self.__config_id == config_id:  # update
                method_config.setId(config_id)
                is_updated = (
                    QgsApplication.authManager().updateAuthenticationConfig(
                        method_config
                    )
                )
                if not is_updated:
                    logger.error(
                        f"Updating auth config FAILED for authcfg: {config_id}"
                    )
            else:  # store new with unique ID, then delete previous
                method_config.setId(config_id)
                is_added = (
                    QgsApplication.authManager().storeAuthenticationConfig(
                        method_config
                    )
                )
                if is_added:
                    is_deleted = QgsApplication.authManager().removeAuthenticationConfig(
                        self.__config_id
                    )
                    if not is_deleted:
                        logger.error("Removal of older auth config FAILED")
                    self.__config_id = config_id
                else:
                    logger.error(
                        "Storing new auth config with user-created unique ID FAILED"
                    )

        self.accept()

    def __init_ui(self) -> None:
        self.setupUi(self)
        self.setWindowTitle(self.tr("Authentication"))

        # Logo
        icon_path = (
            Path(__file__).parents[1] / "icons" / "nextgis_full_logo.svg"
        )
        logo = QIcon(str(icon_path))
        logo_size = QSvgRenderer(str(icon_path)).defaultSize()
        height = 24
        width = int(height * logo_size.width() / logo_size.height())
        pixmap = logo.pixmap(logo.actualSize(QSize(width, height)))
        self.logo_label.setPixmap(pixmap)

        # Sign up button
        ngw_button = NgwButton(self.tr("Sign Up"), self)
        ngw_button.clicked.connect(self.__sign_up)
        self.header.layout().addWidget(ngw_button)

        # Auth id widget
        self.__auth_config_id_edit = AuthConfigIdEdit(self)
        self.id_layout.addWidget(self.__auth_config_id_edit)
        self.__auth_config_id_edit.validityChanged.connect(
            self.__validate_auth
        )

        # Additional settings
        cast(QgsCollapsibleGroupBox, self.additional_groupbox).setCollapsed(
            True
        )

        # Button box
        self.name_lineedit.textChanged.connect(self.__validate_auth)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.save_config)
        self.username_lineedit.textChanged.connect(
            self.__validate_basic_config
        )
        self.button_box.button(
            QDialogButtonBox.StandardButton.Reset
        ).clicked.connect(self.reset_config)

        # Focus
        self.username_lineedit.setFocus()

        # Resize
        QTimer.singleShot(0, self.__delayed_resize)

    def __can_load_config(self) -> bool:
        if QgsApplication.authManager().isDisabled():
            return False

        if (
            len(self.__config_id) > 0
            and self.__config_id
            not in QgsApplication.authManager().configIds()
        ):
            return False

        return True

    def __init_error_ui(self) -> None:
        self.setLayout(QVBoxLayout())

        message = ""
        if QgsApplication.authManager().isDisabled():
            message += QgsApplication.authManager().disabledMessage()

        if len(self.__config_id) > 0:
            if len(message) > 0:
                message += "\n\n"

            message += self.tr(
                "Authentication config id is not loaded: {}"
            ).format(self.__config_id)

        self.layout().addWidget(QLabel(message, self))

    @pyqtSlot()
    def __delayed_resize(self) -> None:
        self.resize(
            QSize(self.size().width(), self.minimumSizeHint().height())
        )

    def __load_config(self) -> None:
        is_empty = len(self.__config_id) == 0
        self.__auth_config_id_edit.setAllowEmptyId(is_empty)
        if is_empty:
            return

        # edit mode requires master password to have been set and verified against auth db
        if not QgsApplication.authManager().setMasterPassword(True):
            self.__config_id = ""
            return

        method_config = QgsAuthMethodConfig()
        if not QgsApplication.authManager().loadAuthenticationConfig(
            self.__config_id, method_config, True
        ):
            logger.error(f"Loading FAILED for authcfg: {self.__config_id}")
            return

        if not method_config.isValid():
            logger.error(
                f"Loading FAILED for authcfg ({self.__config_id}): invalid config"
            )
            return

        method = QgsApplication.authManager().configAuthMethodKey(
            self.__config_id
        )
        if method != "Basic":
            logger.error(
                f"Loading FAILED for authcfg ({self.__config_id}): not basic"
            )
            return

        self.name_lineedit.setText(method_config.name())
        self.resource_lineedit.setText(method_config.uri())
        self.__auth_config_id_edit.setAuthConfigId(method_config.id())

        self.__load_basic_config(method_config.configMap())

    def __load_basic_config(self, config_map: Dict[str, str]) -> None:
        self.__clear_basic_config()

        self.__config_map = config_map
        self.username_lineedit.setText(config_map["username"])
        self.password_lineedit.setText(config_map["password"])
        self.realm_lineedit.setText(config_map["realm"])

        self.__validate_basic_config()

    def __basic_map(self) -> Dict[Optional[str], Optional[str]]:
        return {
            "username": self.username_lineedit.text(),
            "password": self.password_lineedit.text(),
            "realm": self.realm_lineedit.text(),
        }

    def __clear_all(self) -> None:
        self.name_lineedit.clear()
        self.resource_lineedit.clear()
        self.__auth_config_id_edit.clear()
        self.__clear_basic_config()
        self.__validate_auth()

    @pyqtSlot()
    def __validate_auth(self) -> None:
        save_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        save_button.setEnabled(
            len(self.name_lineedit.text()) != 0
            and self.__validate_basic_config()
            and self.__auth_config_id_edit.validate()
        )

    @pyqtSlot()
    def __validate_basic_config(self) -> bool:
        is_credentials_valid = len(self.username_lineedit.text()) != 0
        if is_credentials_valid != self.__is_credentials_valid:
            self.__is_credentials_valid = is_credentials_valid
            self.__validate_auth()
        return is_credentials_valid

    @pyqtSlot()
    def __reset_basic_config(self) -> None:
        self.__load_basic_config(self.__config_map)

    @pyqtSlot()
    def __clear_basic_config(self) -> None:
        self.username_lineedit.clear()
        self.password_lineedit.clear()
        self.realm_lineedit.clear()

    @pyqtSlot()
    def __sign_up(self) -> None:
        override_locale = QgsSettings().value(
            "locale/overrideFlag", defaultValue=False, type=bool
        )
        if not override_locale:
            locale_full_name = QLocale.system().name()
        else:
            locale_full_name = QgsSettings().value("locale/userLocale", "")
        locale = locale_full_name[0:2]

        utm = (
            "utm_source=qgis_plugin&utm_medium=auth_config"
            "&utm_campaign=constant&utm_term=nextgis_connect"
            f"&utm_content={locale}"
        )
        signup_url = f"https://my.nextgis.com/signup/?{utm}"
        QDesktopServices.openUrl(QUrl(signup_url))
