from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)

from nextgis_connect.ui.icon import draw_icon, material_icon


class NoFeaturesWidget(QWidget):
    """Show a message when no features match the click location.

    Render an informational icon and centered text explaining that the
    identification request did not return any features.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the placeholder widget.

        :param parent: Parent widget owning the placeholder.
        """
        super().__init__(parent)

        label = QLabel("No features were found at the click location.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_size = label.fontMetrics().height()
        icon = QLabel()
        draw_icon(icon, material_icon("info"), size=icon_size)

        layout = QHBoxLayout()
        layout.addSpacerItem(
            QSpacerItem(
                40,
                20,
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Minimum,
            )
        )
        layout.addWidget(icon)
        layout.addWidget(label)
        layout.addSpacerItem(
            QSpacerItem(
                40,
                20,
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Minimum,
            )
        )
        self.setLayout(layout)
