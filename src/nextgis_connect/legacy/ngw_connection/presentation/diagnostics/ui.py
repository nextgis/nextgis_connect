# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from typing import Dict, Optional

from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.ngw_connection.domain.diagnostics import (
    ConnectionCheckId,
    ConnectionCheckState,
    ConnectionCheckUpdate,
    ConnectionDiagnosticsSummary,
    ConnectionIssueSource,
)


class NgwConnectionDiagnosticsWidget(QGroupBox):
    _summary_label: QLabel
    _tree: QTreeWidget
    _items: Dict[ConnectionCheckId, QTreeWidgetItem]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle(self.tr("Web GIS"))
        self._items = {}

        layout = QVBoxLayout(self)
        self._summary_label = QLabel(self)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._tree = QTreeWidget(self)
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(0)
        self._tree.setHeaderLabels(
            [self.tr("Check"), self.tr("State"), self.tr("Description")]
        )
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._tree)

        self.reset()

    def reset(self) -> None:
        self._items.clear()
        self._tree.clear()
        self._summary_label.setText(
            self.tr("Run diagnostics for the selected Web GIS.")
        )

    def set_connection_title(self, name: str) -> None:
        self.setTitle(self.tr("Diagnostics for {name}").format(name=name))

    def show_running(self) -> None:
        self._summary_label.setText(self.tr("Diagnostics are running."))

    def set_summary_text(self, text: str) -> None:
        self._summary_label.setText(text)

    def apply_update(self, update: ConnectionCheckUpdate) -> None:
        item = self._items.get(update.check_id)
        if item is None:
            item = QTreeWidgetItem(self._tree)
            self._items[update.check_id] = item

        item.setText(0, update.title)
        item.setText(1, self._state_label(update.state))
        item.setText(2, update.description)

        brush = QBrush(self._state_color(update.state))
        item.setForeground(1, brush)
        item.setForeground(2, brush)

        tooltip = update.description
        if update.issue is not None:
            tooltip_lines = [
                update.description,
                "",
                self._source_label(update.issue.source),
                update.issue.details,
                update.issue.resolution,
            ]
            if update.issue.technical_details is not None:
                tooltip_lines.extend(["", update.issue.technical_details])
            tooltip = "\n".join(tooltip_lines)

        for column in range(3):
            item.setToolTip(column, tooltip)

    def apply_summary(self, summary: ConnectionDiagnosticsSummary) -> None:
        for result in summary.results:
            self.apply_update(
                ConnectionCheckUpdate(
                    check_id=result.check_id,
                    title=result.title,
                    state=result.state,
                    description=result.description,
                    issue=result.issue,
                )
            )

        if summary.has_blocking_failures:
            self._summary_label.setText(
                self.tr("Web GIS checks finished with blocking issues.")
            )
            return

        if summary.state == ConnectionCheckState.FAILURE:
            self._summary_label.setText(
                self.tr("Web GIS checks finished with issues.")
            )
            return

        if summary.state == ConnectionCheckState.WARNING:
            self._summary_label.setText(
                self.tr("Web GIS checks finished with warnings.")
            )
            return

        self._summary_label.setText(self.tr("All Web GIS checks succeeded."))

    def _source_label(self, source: ConnectionIssueSource) -> str:
        labels = {
            ConnectionIssueSource.SERVER: self.tr("Problem source: server"),
            ConnectionIssueSource.NETWORK: self.tr("Problem source: network"),
            ConnectionIssueSource.CLIENT: self.tr("Problem source: client"),
        }
        return labels[source]

    def _state_label(self, state: ConnectionCheckState) -> str:
        labels = {
            ConnectionCheckState.NOT_STARTED: self.tr("Not started"),
            ConnectionCheckState.PENDING: self.tr("Pending"),
            ConnectionCheckState.STARTED: self.tr("Running"),
            ConnectionCheckState.SUCCESS: self.tr("Success"),
            ConnectionCheckState.WARNING: self.tr("Warning"),
            ConnectionCheckState.FAILURE: self.tr("Failure"),
        }
        return labels[state]

    def _state_color(self, state: ConnectionCheckState) -> QColor:
        colors = {
            ConnectionCheckState.NOT_STARTED: QColor("#7a7a7a"),
            ConnectionCheckState.PENDING: QColor("#7a7a7a"),
            ConnectionCheckState.STARTED: QColor("#1565c0"),
            ConnectionCheckState.SUCCESS: QColor("#2e7d32"),
            ConnectionCheckState.WARNING: QColor("#ed6c02"),
            ConnectionCheckState.FAILURE: QColor("#c62828"),
        }
        return colors[state]
