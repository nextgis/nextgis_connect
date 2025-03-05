from enum import IntEnum, auto
from pathlib import Path
from typing import List, Optional, cast

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QItemSelection, pyqtSlot
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QWidget

from nextgis_connect.detached_editing.actions import ActionType
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    ConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts_model import (
    ConflictsResolvingModel,
)
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.utils import material_icon

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "resolving_dialog_base.ui")
)


class ResolvingDialog(QDialog, WIDGET):
    class Page(IntEnum):
        WELCOME = 0
        UPDATE_UPDATE = auto()
        UPDATE_DELETE = auto()
        DELETE_UPDATE = auto()

    __container_path: Path
    __container_metadata: DetachedContainerMetaData
    __conflicts: List[VersioningConflict]
    __resolving_model: ConflictsResolvingModel
    __resolutions: List[ConflictResolution]

    def __init__(
        self,
        container_path: Path,
        metadata: DetachedContainerMetaData,
        conflicts: List[VersioningConflict],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.__container_path = container_path
        self.__container_metadata = metadata
        self.__conflicts = conflicts
        self.__resolutions = []
        self.__setup_ui()

    @property
    def resolutions(self) -> List[ConflictResolution]:
        return self.__resolutions

    def accept(self) -> None:
        self.__resolutions = self.__resolving_model.resulutions
        return super().accept()

    def __setup_ui(self) -> None:
        self.setupUi(self)
        self.__setup_left_side()

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.__validate()

    def __setup_left_side(self) -> None:
        self.__resolving_model = ConflictsResolvingModel(
            self.__container_path,
            self.__container_metadata,
            self.__conflicts,
            self,
        )
        self.__resolving_model.dataChanged.connect(self.__validate)
        self.features_view.setModel(self.__resolving_model)
        self.features_view.selectionModel().selectionChanged.connect(
            self.__on_selection_changed
        )
        self.features_view.selectionModel().clear()

        self.__on_selection_changed(QItemSelection(), QItemSelection())

        self.apply_local_button.setIcon(material_icon("computer"))
        self.apply_local_button.clicked.connect(self.__resolve_as_local)
        self.apply_remote_button.setIcon(material_icon("cloud"))
        self.apply_remote_button.clicked.connect(self.__resolve_as_remote)

    @pyqtSlot(QItemSelection, QItemSelection)
    def __on_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection
    ) -> None:
        selected_count = len(selected.indexes())
        is_empty = selected_count == 0

        self.apply_local_button.setEnabled(not is_empty)
        self.apply_remote_button.setEnabled(not is_empty)

        if selected_count != 1:
            self.stacked_widget.setCurrentIndex(self.Page.WELCOME)
            return

        item = cast(
            ConflictResolvingItem,
            self.__resolving_model.data(
                selected.indexes()[0],
                ConflictsResolvingModel.Roles.RESOLVING_ITEM,
            ),
        )
        if item.conflict.local_action.action == ActionType.FEATURE_DELETE:
            self.stacked_widget.setCurrentIndex(self.Page.DELETE_UPDATE)
        elif item.conflict.remote_action.action == ActionType.FEATURE_DELETE:
            self.stacked_widget.setCurrentIndex(self.Page.UPDATE_DELETE)
        else:
            self.stacked_widget.setCurrentIndex(self.Page.UPDATE_UPDATE)

    @pyqtSlot()
    def __resolve_as_local(self) -> None:
        self.__resolving_model.resolve_all_as_local()

    @pyqtSlot()
    def __resolve_as_remote(self) -> None:
        self.__resolving_model.resolve_all_as_remote()

    @pyqtSlot()
    def __validate(self) -> None:
        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).setEnabled(self.__resolving_model.is_all_resolved)
