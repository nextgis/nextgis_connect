from typing import List, Optional, cast

from PyQt5.QtCore import QModelIndex
from qgis.PyQt.QtCore import QObject, QSortFilterProxyModel

from .model import QNGWResourceItem, QNGWResourceTreeModel


class NgConnectProxyModel(QSortFilterProxyModel):
    def __init__(self, parent: Optional[QObject]) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.__resources_id = []
        self.__expandex_resources = []

    def set_resources_id(self, resources_id: List[int]) -> None:
        self.__resources_id = resources_id

        self.invalidateFilter()

        self.layoutAboutToBeChanged.emit()
        self.__extract_expanded_resources()
        self.layoutChanged.emit()

    @property
    def expanded_resources(self) -> List[int]:
        return self.__expandex_resources

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        if self.sourceModel() is None or len(self.__resources_id) == 0:
            return True

        source_index = self.sourceModel().index(source_row, 0, source_parent)
        return (
            self.__accept_resource(source_index)
            or self.__accept_ancestor(source_index)
            or self.__accept_descendant(source_index)
        )

    def __accept_resource(self, source_index: QModelIndex) -> bool:
        resource_id = source_index.data(QNGWResourceItem.NGWResourceIdRole)

        return resource_id in self.__resources_id

    def __accept_ancestor(self, source_index: QModelIndex) -> bool:
        parent_index = source_index.parent()
        if not parent_index.isValid():
            return False

        if self.__accept_resource(parent_index):
            return True

        return self.__accept_ancestor(parent_index)

    def __accept_descendant(self, source_index: QModelIndex) -> bool:
        for row in range(self.sourceModel().rowCount(source_index)):
            child_index = self.sourceModel().index(row, 0, source_index)
            if self.__accept_resource(child_index):
                return True
            if self.__accept_descendant(child_index):
                return True

        return False

    def __extract_expanded_resources(self) -> None:
        self.__expandex_resources = []

        if self.sourceModel() is None or (
            len(self.__resources_id) == 1 and self.__resources_id[0] == -1
        ):
            return

        model = cast(QNGWResourceTreeModel, self.sourceModel())

        closest_to_root = self.__extract_closest_to_root()
        expanded_resources = set()

        for resource_id in closest_to_root:
            index = model.index_from_id(resource_id)
            while index.isValid():
                parent = index.parent()
                if not parent.isValid():
                    break
                parent_id = model.resource(parent).resource_id
                expanded_resources.add(parent_id)
                index = parent

        self.__expandex_resources = list(expanded_resources)

    def __extract_closest_to_root(self) -> List[int]:
        closest_to_root = set()

        model = cast(QNGWResourceTreeModel, self.sourceModel())

        for resource_id in self.__resources_id:
            index = model.index_from_id(resource_id)

            has_parent_in_found_list = False

            while index.isValid():
                parent = index.parent()
                if not parent.isValid():
                    break

                parent_id = model.resource(parent).resource_id
                if parent_id in self.__resources_id:
                    has_parent_in_found_list = True
                    break

                index = parent

            if not has_parent_in_found_list:
                closest_to_root.add(resource_id)

        return list(closest_to_root)
