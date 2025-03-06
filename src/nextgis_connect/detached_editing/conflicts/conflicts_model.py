from enum import IntEnum, auto
from pathlib import Path
from typing import Any, List, Optional

from qgis.PyQt.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QVariant,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QIcon

from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    ConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item_extractor import (
    ConflictResolvingItemExtractor,
)
from nextgis_connect.detached_editing.conflicts.item_to_resolution_converter import (
    ItemToResolutionConverter,
)
from nextgis_connect.detached_editing.utils import DetachedContainerMetaData
from nextgis_connect.utils import material_icon


class ConflictsResolvingModel(QAbstractListModel):
    """
    Qt model for managing conflicts resolution items.

    :param conflicts: Initial list of conflicts.
    """

    class Roles(IntEnum):
        RESOLVING_ITEM = Qt.ItemDataRole.UserRole + 1
        RESOLVING_STATE = auto()

    _container_path: Path
    _container_metadata: DetachedContainerMetaData
    _conflict_resoving_items: List[ConflictResolvingItem]

    __not_resolved_icon: QIcon
    __resolved_icon: QIcon

    def __init__(
        self,
        container_path: Path,
        metadata: DetachedContainerMetaData,
        conflicts: List[VersioningConflict],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._container_path = container_path
        self._container_metadata = metadata
        self._conflict_resoving_items = self.__convert_conflicts_to_items(
            conflicts
        )

        self.__not_resolved_icon = material_icon(
            "question_mark.svg", color="#f1ea64", size=16
        )
        self.__resolved_icon = material_icon(
            "check.svg", color="#7bab4d", size=16
        )

    @property
    def resolved_count(self) -> int:
        return sum(
            1 for item in self._conflict_resoving_items if item.is_resolved
        )

    @property
    def is_all_resolved(self) -> bool:
        return all(item.is_resolved for item in self._conflict_resoving_items)

    @property
    def resulutions(self) -> List[ConflictResolution]:
        converter = ItemToResolutionConverter(
            self._container_path, self._container_metadata
        )
        return converter.convert(self._conflict_resoving_items)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        """
        Returns the number of conflicts in the model.

        :param parent: Parent index (not used).
        :return: Number of conflicts.
        """
        return len(self._conflict_resoving_items)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        """
        Returns data for the given index and role.

        :param index: QModelIndex for the requested data.
        :param role: Rojle for which data is requested.
        :return: QVariant containing the requested data.
        """
        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return QVariant()

        item = self._conflict_resoving_items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            label_field = self._container_metadata.fields.label_field
            if label_field is None:
                return self.tr("Feature №") + str(item.conflict.fid)

            for feature in (
                item.local_feature,
                item.remote_feature,
                item.result_feature,
            ):
                if feature is None:
                    continue

                return feature.attribute(label_field.attribute)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self.tr("Feature №") + str(item.conflict.fid)

        if role == Qt.ItemDataRole.DecorationRole:
            return (
                self.__resolved_icon
                if item.is_resolved
                else self.__not_resolved_icon
            )

        if role == self.Roles.RESOLVING_ITEM:
            return item

        if role == self.Roles.RESOLVING_STATE:
            return item.is_resolved

        return QVariant()

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return False

        if role == self.Roles.RESOLVING_STATE:
            item = self._conflict_resoving_items[index.row()]
            item.is_resolved = value
            self.dataChanged.emit(index, index)
            return True

        return False

    @pyqtSlot(QModelIndex)
    def resolve_as_local(self, index: QModelIndex) -> None:
        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return

        self._conflict_resoving_items[index.row()].resolve_as_local()
        self.dataChanged.emit(index, index)

    @pyqtSlot(QModelIndex)
    def resolve_as_remote(self, index: QModelIndex) -> None:
        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return

        self._conflict_resoving_items[index.row()].resolve_as_remote()
        self.dataChanged.emit(index, index)

    @pyqtSlot()
    def resolve_all_as_local(self) -> None:
        for resolving_item in self._conflict_resoving_items:
            resolving_item.resolve_as_local()

        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, 0)
        )

    @pyqtSlot()
    def resolve_all_as_remote(self) -> None:
        for resolving_item in self._conflict_resoving_items:
            resolving_item.resolve_as_remote()

        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, 0)
        )

    def __convert_conflicts_to_items(
        self, conflicts: List[VersioningConflict]
    ) -> List[ConflictResolvingItem]:
        extractor = ConflictResolvingItemExtractor(
            self._container_path, self._container_metadata
        )
        return extractor.extract(conflicts)
