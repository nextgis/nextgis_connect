from qgis.core import QgsVectorLayer, edit

from nextgis_connect.detached_editing.detached_container import (
    DetachedContainer,
)
from nextgis_connect.detached_editing.utils import (
    container_path,
    is_ngw_container,
)


class DetachedLayerEdit(edit):
    def __init__(self, layer: QgsVectorLayer) -> None:
        super().__init__(layer)
        self.container = None
        if is_ngw_container(layer):
            path = container_path(layer)
            self.container = DetachedContainer(path)
            self.container.add_layer(layer)
            layer.setReadOnly(False)

    def __exit__(self, ex_type, ex_value, traceback) -> bool:
        result = super().__exit__(ex_type, ex_value, traceback)

        if self.container is not None:
            self.container.delete_layer(self.layer.id())
            self.container = None

        return result
