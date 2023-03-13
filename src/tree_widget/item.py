from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QIcon

from ..ngw_api.core import (
    NGWGroupResource, NGWMapServerStyle, NGWQGISRasterStyle, NGWQGISVectorStyle,
)
from ..ngw_api.utils import log  # TODO REMOVE


from qgis.PyQt.QtWidgets import QTreeWidgetItem


# TODO: remove QTreeWidgetItem inheritance
class QModelItem(QTreeWidgetItem):
    def __init__(self):
        super().__init__()

        #self.locked_item = ItemBase(["loading..."])
        #self.locked_item.setFlags(Qt.NoItemFlags)

        self._locked = False
        self.unlock()

    def lock(self):
        self._locked = True
        #self.setFlags(Qt.NoItemFlags)
        #self.addChild(self.locked_item)

    @property
    def locked(self):
        return self._locked

    def unlock(self):
        if self._locked:
            #self.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            #self.removeChild(self.locked_item)
            self._locked = False

    def flags(self):
        if self._locked:
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, role):
        return QVariant()


class QNGWResourceItem(QModelItem):
    NGWResourceRole = Qt.UserRole
    NGWResourceIdRole = Qt.UserRole + 1

    def __init__(self, ngw_resource):
        super().__init__()
        title = ngw_resource.common.display_name
        if isinstance(ngw_resource, (NGWQGISRasterStyle, NGWQGISVectorStyle)):
            title = "(qgis) " + title
        elif isinstance(ngw_resource, NGWMapServerStyle):
            title = "(ms) " + title
        self._title = title
        self._ngw_resource = ngw_resource
        self._icon = QIcon(self._ngw_resource.icon_path)

    def data(self, role):
        if role == Qt.DisplayRole:
            return self._title
        if role == Qt.DecorationRole:
            return self._icon
        if role == QNGWResourceItem.NGWResourceRole:
            return self._ngw_resource
        if role == QNGWResourceItem.NGWResourceIdRole:
            return self._ngw_resource.common.id
        return super().data(role)

    def ngw_resource_id(self):
        return self.data(QNGWResourceItem.NGWResourceIdRole)

    def is_group(self):
        ngw_resource = self.data(self.NGWResourceRole)
        return ngw_resource.type_id == NGWGroupResource.type_id

    def more_priority(self, item):
        if not isinstance(item, QNGWResourceItem):
            return True

        if self.is_group() != item.is_group():
            return self.is_group() > item.is_group()

        return self._title.lower() < item._title.lower()
