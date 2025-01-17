import re
from pathlib import Path
from typing import Optional

from qgis.core import QgsApplication
from qgis.PyQt import uic
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import QWidget

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "auth_config_id_edit.ui")
)


class AuthConfigIdEdit(QWidget, WIDGET):
    """
    Custom widget for editing an authentication configuration ID

    Validates the input against the database and checks for ID's 7-character alphanumeric syntax.
    """

    validityChanged = pyqtSignal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        authcfg: str = "",
        allow_empty: bool = True,
    ) -> None:
        """
        Widget to unlock and edit an authentication configuration ID.

        :param parent: Parent widget
        :param authcfg: Authentication configuration ID
        :param allow_empty: Whether to allow no ID to be set, even when editing
        """
        super().__init__(parent)
        self.mAuthCfgOrig = authcfg
        self.mAllowEmpty = allow_empty
        self.mValid = False

        self.setupUi(self)
        self.leAuthCfg.setReadOnly(True)
        self.leAuthCfg.setText(authcfg)

        lock_icon = QIcon(":/images/themes/default/locked.svg")
        lock_icon.addFile(
            ":/images/themes/default/locked.svg", state=QIcon.State.Off
        )
        lock_icon.addFile(
            ":/images/themes/default/unlocked.svg", state=QIcon.State.On
        )
        self.btnLock.setIcon(lock_icon)

        self.btnLock.toggled.connect(self.btnLock_toggled)
        self.leAuthCfg.textChanged.connect(self.leAuthCfg_textChanged)
        self.validityChanged.connect(self.updateValidityStyle)

        self.updateValidityStyle(self.validate())

    def configId(self) -> str:
        """
        Returns the authentication configuration ID if valid, otherwise an empty string.

        :return: Authentication configuration ID
        """
        if not self.validate():
            return ""
        return self.leAuthCfg.text()

    def allowEmptyId(self) -> bool:
        """
        Whether to allow no ID to be set.

        :return: True if empty IDs are allowed, False otherwise
        """
        return self.mAllowEmpty

    def validate(self) -> bool:
        """
        Validates the widget state and ID.

        :return: True if valid, False otherwise
        """
        authcfg = self.leAuthCfg.text()
        curvalid = (authcfg == self.mAuthCfgOrig and len(authcfg) == 7) or (
            self.mAllowEmpty and len(authcfg) == 0
        )

        auth_manager = QgsApplication.authManager()
        if (
            not auth_manager.isDisabled()
            and not curvalid
            and len(authcfg) == 7
            and self.isAlphaNumeric(authcfg)
        ):
            curvalid = auth_manager.configIdUnique(authcfg)

        if self.mValid != curvalid:
            self.mValid = curvalid
            self.validityChanged.emit(curvalid)

        return curvalid

    def setAuthConfigId(self, authcfg: str) -> None:
        """
        Sets the authentication configuration ID, storing it, and validating the passed value.

        :param authcfg: Authentication configuration ID
        """
        if len(self.mAuthCfgOrig) == 0:
            self.mAuthCfgOrig = authcfg
        self.leAuthCfg.setText(authcfg)
        self.validate()

    def setAllowEmptyId(self, allowed: bool) -> None:
        """
        Sets whether to allow no ID to be set.

        :param allowed: True to allow empty ID, False otherwise
        """
        self.mAllowEmpty = allowed
        self.validate()

    def clear(self) -> None:
        """
        Clears all of the widget's editing state and contents.
        """
        self.leAuthCfg.setText(self.mAuthCfgOrig)
        self.updateValidityStyle(True)

    def updateValidityStyle(self, valid: bool) -> None:
        """
        Updates the style of the widget based on validity.

        :param valid: True if valid, False otherwise
        """
        red = QColor(200, 0, 0).name()
        yellow = QColor(255, 255, 125).name()

        stylesheet = "QLineEdit{"
        if not valid:
            stylesheet += f"color: {red};"
        if self.btnLock.isChecked():
            stylesheet += f"background-color: {yellow};"
        stylesheet += "}"

        self.leAuthCfg.setStyleSheet(stylesheet)

    def btnLock_toggled(self, checked: bool) -> None:
        """
        Handles toggling of the lock button.

        :param checked: True if toggled on, False otherwise
        """
        self.leAuthCfg.setReadOnly(not checked)
        if checked:
            self.leAuthCfg.setFocus()
        self.updateValidityStyle(self.validate())

    def leAuthCfg_textChanged(self, txt: str) -> None:
        """
        Handles text change in the line edit.

        :param txt: The new text in the line edit
        """
        self.validate()

    def isAlphaNumeric(self, authcfg: str) -> bool:
        """
        Checks if the given authentication configuration ID is alphanumeric.

        :param authcfg: Authentication configuration ID
        :return: True if alphanumeric, False otherwise
        """
        return re.fullmatch(r"[a-zA-Z0-9]{7}", authcfg) is not None
