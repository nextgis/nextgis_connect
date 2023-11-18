from qgis.PyQt.QtCore import Qt, QModelIndex, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QPalette, QPainter, QPen, QKeyEvent
from qgis.PyQt.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QSpacerItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QDialog,
    QPushButton
)

from qgis.utils import iface
from qgis.gui import QgsNewNameDialog

from ..tree_widget.item import QNGWResourceItem
from ..utils import SupportStatus

from ..ngw_connection.ngw_connections_manager import NgwConnectionsManager


__all__ = ["QNGWResourceTreeView"]


class QOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        palette = QPalette(self.palette())
        self._overlay_color = palette.color(QPalette.ColorRole.Background)
        self._overlay_color.setAlpha(200)
        palette.setColor(
            QPalette.ColorRole.Background, Qt.GlobalColor.transparent
        )
        self.setPalette(palette)

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QBrush(self._overlay_color))
        painter.setPen(QPen(Qt.PenStyle.NoPen))


class QMessageOverlay(QOverlay):
    def __init__(self, parent, text):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.setLayout(self.layout)

        self.text = QLabel(text, self)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.layout.addWidget(self.text)

    def set_text(self, text: str) -> None:
        self.text.setText(text)


class MigrationOverlay(QOverlay):
    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        spacer_before = QSpacerItem(
            20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        spacer_after = QSpacerItem(
            20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding
        )

        self.text = QLabel(
            self.tr(
                'We are transitioning to the QGIS Authentication System to '
                'enhance security and streamline your experience. This change '
                'requires the conversion of existing connections.\n\nPlease be'
                ' aware that your current connections will be converted to the'
                ' new format automatically. This is a one-time process and '
                'should not affect your workflow.\n'
            ),
            self
        )
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)

        full_migrate_button = QPushButton(
            self.tr('Convert connectons and authentification data')
        )
        full_migrate_button.clicked.connect(self.__full_migrate)

        layout.addSpacerItem(spacer_before)
        layout.addWidget(self.text)
        layout.addWidget(full_migrate_button)
        layout.addSpacerItem(spacer_after)

    def __full_migrate(self):
        NgwConnectionsManager().convert_old_connections(convert_auth=True)
        self.__reinit()

    def __reinit(self):
        dock = iface.mainWindow().findChild(QWidget, 'NGConnectDock')
        dock.reinit_tree(force=True)


class QProcessOverlay(QOverlay):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        spacer_before = QSpacerItem(
            20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        spacer_after = QSpacerItem(
            20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding
        )
        self.layout.addItem(spacer_before)

        self.central_widget = QWidget(self)
        self.central_widget_layout = QVBoxLayout(self.central_widget)
        self.central_widget.setLayout(self.central_widget_layout)
        self.layout.addWidget(self.central_widget)

        self.layout.addItem(spacer_after)

        self.progress = QProgressBar(self)
        self.progress.setMinimum(0)
        self.progress.setMaximum(0)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.central_widget_layout.addWidget(self.progress)
        self.setStyleSheet(
            """
                QProgressBar {
                    border: 1px solid grey;
                    border-radius: 5px;
                }
            """
        )

        self.text = QLabel(self)
        self.text.setAlignment(
            Qt.AlignmentFlag(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        )
        self.text.setOpenExternalLinks(True)
        self.text.setWordWrap(True)
        self.central_widget_layout.addWidget(self.text)

    def write(self, jobs):
        text = ""
        for job_name, job_status in list(jobs.items()):
            text += "<strong>%s</strong><br/>" % job_name
            if job_status != "":
                text += "%s<br/>" % job_status

        self.text.setText(text)


class UnsupportedVersionOverlay(QMessageOverlay):
    def __init__(self, parent: QWidget):
        super().__init__(parent, "")

    def set_status(
        self, status: SupportStatus, ngc_version: str, ngw_version: str
    ) -> None:
        text = ""
        if status == SupportStatus.OLD_CONNECT:
            text = self.tr(
                "NextGIS Connect version is outdated. Please update the "
                "plugin via Plugins - Manage and install plugins menu."
            )
        elif status == SupportStatus.OLD_NGW:
            text = self.tr(
                "NextGIS Web service version is outdated and not supported by "
                "NextGIS Connect. Please contact your server administrator"
                " for further assistance."
            )

        text += "\n\n" + self.tr(
            "NextGIS Connect version: {}\nNextGIS Web version: {}"
        ).format(ngc_version, ngw_version)

        self.set_text(text)


class QNGWResourceTreeView(QTreeView):
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)

        header = self.header()
        assert header is not None
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)

        # no ngw connectiond message
        self.no_ngw_connections_overlay = QMessageOverlay(
            self,
            self.tr(
                'No connections to nextgis.com. Please create a connection. You can get your free Web GIS at <a href="https://my.nextgis.com/">nextgis.com</a>!'
            ),
        )
        self.no_ngw_connections_overlay.hide()

        self.unsupported_version_overlay = UnsupportedVersionOverlay(self)
        self.unsupported_version_overlay.hide()
        self.migration_overlay = MigrationOverlay(self)
        self.migration_overlay.hide()

        self.no_oauth_auth_overlay = QMessageOverlay(
            self, self.tr(
                "Please authorize via NextGIS Account Toolbar"
            ))
        self.no_oauth_auth_overlay.hide()

        self.ngw_job_block_overlay = QProcessOverlay(self)
        self.ngw_job_block_overlay.hide()

        self.jobs = {}

    def setModel(self, model):
        self._source_model = model
        self._source_model.rowsInserted.connect(self.__insertRowsProcess)

        super().setModel(self._source_model)

    def selectedIndex(self):
        return self.selectionModel().currentIndex()

    def __insertRowsProcess(self, parent, start, end):
        if not parent.isValid():
            self.expandAll()
        # else:
        #     self.expand(
        #         parent
        #     )

    def resizeEvent(self, event):
        self.no_ngw_connections_overlay.resize(event.size())
        self.ngw_job_block_overlay.resize(event.size())
        self.unsupported_version_overlay.resize(event.size())
        self.migration_overlay.resize(event.size())
        self.no_oauth_auth_overlay.resize(event.size())

        super().resizeEvent(event)

    def mouseDoubleClickEvent(self, e):
        index = self.indexAt(e.pos())
        if index.isValid():
            self.itemDoubleClicked.emit(index)

        super(QNGWResourceTreeView, self).mouseDoubleClickEvent(e)

    def showWelcomeMessage(self):
        self.no_ngw_connections_overlay.show()

    def hideWelcomeMessage(self):
        self.no_ngw_connections_overlay.hide()

    def addBlockedJob(self, job_name):
        self.jobs.update({job_name: ""})
        self.ngw_job_block_overlay.write(self.jobs)

        self.ngw_job_block_overlay.show()

    def addJobStatus(self, job_name, status):
        if job_name in self.jobs:
            self.jobs[job_name] = status
            self.ngw_job_block_overlay.write(self.jobs)

    def removeBlockedJob(self, job_name):
        if job_name in self.jobs:
            self.jobs.pop(job_name)
            self.ngw_job_block_overlay.write(self.jobs)

        if len(self.jobs) == 0:
            self.ngw_job_block_overlay.hide()

    def keyPressEvent(self, event: QKeyEvent):
        is_f2 = event.key() == Qt.Key.Key_F2
        index = self.currentIndex()
        if is_f2 and index.isValid():
            self.rename_resource(index)
        else:
            super().keyPressEvent(event)

    def rename_resource(self, index: QModelIndex):
        # Get current resource name. This name can differ from display
        # text of tree item (see style resources).
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        current_name = ngw_resource.common.display_name

        # Get existing names
        existing_names = []
        parent = index.parent()
        if parent.isValid():
            model = parent.model()
            assert model is not None
            for i in range(model.rowCount(parent)):
                if i == index.row():
                    continue
                sibling_index = model.index(i, 0, parent)
                sibling_resource = sibling_index.data(
                    QNGWResourceItem.NGWResourceRole
                )
                existing_names.append(sibling_resource.common.display_name)

        dialog = QgsNewNameDialog(
            initial=current_name,
            existing=existing_names,
            cs=Qt.CaseSensitivity.CaseSensitive,
            parent=iface.mainWindow(),
        )
        dialog.setWindowTitle(self.tr("Change resource name"))
        dialog.setOverwriteEnabled(False)
        dialog.setAllowEmptyName(False)
        dialog.setHintString(self.tr("Enter new name for selected resource"))
        dialog.setConflictingNameWarning(self.tr("Resource already exists"))

        if dialog.exec_() != QDialog.DialogCode.Accepted:
            return

        new_name = dialog.name()

        if new_name == current_name:
            return

        self.__rename_resource_resp = self.model().renameResource(
            index, new_name
        )
        self.__rename_resource_resp.done.connect(  # type: ignore
            self.setCurrentIndex
        )
