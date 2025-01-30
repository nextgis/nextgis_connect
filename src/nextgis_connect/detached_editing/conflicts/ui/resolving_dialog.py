from pathlib import Path
from typing import List, Optional

from qgis.PyQt import uic
from qgis.PyQt.QtCore import pyqtSlot
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QWidget

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
    ResolutionType,
)

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "resolving_dialog_base.ui")
)


class ResolvingDialog(QDialog, WIDGET):
    __conflicts: List[VersioningConflict]
    __resolutions: List[ConflictResolution]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.__conflicts = []
        self.__resolutions = []
        self.__init_ui()

    def set_conflicts(self, conflicts: List[VersioningConflict]) -> None:
        self.__conflicts = conflicts

    @property
    def resolutions(self) -> List[ConflictResolution]:
        return self.__resolutions

    def __init_ui(self) -> None:
        self.setupUi(self)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Local"
        )
        self.button_box.button(
            QDialogButtonBox.StandardButton.Ok
        ).clicked.connect(self.__accept_all_local)
        self.button_box.button(QDialogButtonBox.StandardButton.Save).setText(
            "Remote"
        )
        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).clicked.connect(self.__accept_all_remote)
        self.button_box.rejected.connect(self.reject)

    @pyqtSlot()
    def __accept_all_local(self) -> None:
        self.__resolutions = [
            ConflictResolution(ResolutionType.Local, conflict)
            for conflict in self.__conflicts
        ]

        self.accept()

    @pyqtSlot()
    def __accept_all_remote(self) -> None:
        self.__resolutions = [
            ConflictResolution(ResolutionType.Remote, conflict)
            for conflict in self.__conflicts
        ]
        self.accept()
