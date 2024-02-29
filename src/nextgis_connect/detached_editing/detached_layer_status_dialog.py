import os
import sqlite3
from contextlib import closing
from typing import Optional

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QWidget

pluginPath = os.path.dirname(__file__)
WIDGET, _ = uic.loadUiType(
    os.path.join(pluginPath, "detached_layer_status_dialog_base.ui")
)


class DetachedLayerStatusDialog(QDialog, WIDGET):
    def __init__(self, path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        Button = QDialogButtonBox.StandardButton
        self.buttonBox.button(Button.Retry).hide()
        # self.buttonBox.button(Button.Retry).setText(self.tr('Synchronization'))
        # self.buttonBox.rejected.connect(self.reject)

        self.buttonBox.rejected.connect(self.reject)

        self.__fill_changes(path)

    def __fill_changes(self, path) -> None:
        with closing(sqlite3.connect(path)) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) from ngw_added_features) added,
                      (SELECT COUNT(*) from ngw_removed_features) removed,
                      (SELECT COUNT(*) from ngw_updated_attributes) attributes,
                      (SELECT COUNT(*) from ngw_updated_geometries) geometries
                """
                )
                result = cursor.fetchone()
        self.addedFeaturesLabel.setText(str(result[0]))
        self.removedFeaturesLabel.setText(str(result[1]))
        self.updatedAttributesLabel.setText(str(result[2]))
        self.updatedGeometriesLabel.setText(str(result[3]))
