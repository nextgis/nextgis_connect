from typing import Dict, Optional, Set, cast

from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsHighlight, QgsMapCanvas, QgsMapToolIdentify
from qgis.PyQt.QtCore import QObject

from nextgis_connect.detached_editing.identification.types import FeatureKey
from nextgis_connect.logging import logger


class HighlightHandler(QObject):
    """Manage identification feature highlights on the map canvas.

    Keep background highlights for all identified features and maintain a
    dedicated foreground highlight for the currently active feature so it
    is rendered above the rest.

    :ivar _highlights: Store background highlights by feature key.
    :ivar _results: Store identify results required to recreate the active
        highlight.
    :ivar _active_highlight: Store the foreground highlight for the active
        feature.
    :ivar _active_feature_key: Store the key of the active feature.
    """

    def __init__(
        self, canvas: QgsMapCanvas, parent: Optional[QObject] = None
    ) -> None:
        """Initialize highlight management for the provided canvas.

        :param canvas: Map canvas used to render highlights.
        :param parent: Parent object.
        """
        super().__init__(parent)
        self._canvas = canvas

        # Background highlights for all identified features
        self._highlights: Dict[FeatureKey, QgsHighlight] = {}

        # Results needed to recreate active highlight on top
        self._results: Dict[FeatureKey, QgsMapToolIdentify.IdentifyResult] = {}

        # Foreground highlight rendered last (always on top)
        self._active_highlight: Optional[QgsHighlight] = None
        self._active_feature_key: Optional[FeatureKey] = None

    def add_feature(
        self,
        feature_key: FeatureKey,
        result: QgsMapToolIdentify.IdentifyResult,
    ) -> None:
        """Register a feature and show its background highlight.

        :param feature_key: Unique key of the identified feature.
        :param result: Identify result containing the feature and layer.
        """
        self._results[feature_key] = result
        highlight = self._create_highlight(result)
        self._apply_background_style(highlight)
        highlight.show()
        self._highlights[feature_key] = highlight

    def set_active_feature(self, feature_key: FeatureKey) -> None:
        """Activate the feature highlight and render it above others.

        Hide the background highlight for the selected feature and create a
        dedicated foreground highlight that is drawn last.

        :param feature_key: Unique key of the feature to activate.
        """
        if feature_key not in self._results:
            logger.warning(
                f"Cannot set active feature {feature_key} - not found in results"
            )
            return

        self._remove_active_highlight()
        self._active_feature_key = feature_key

        # Hide the background highlight for this feature
        background = self._highlights.get(feature_key)
        if background is not None:
            background.hide()

        # Re-create the active highlight so it is rendered last
        result = self._results.get(feature_key)
        if result is None:
            return

        self._active_highlight = self._create_highlight(result)
        self._active_highlight.applyDefaultStyle()
        self._active_highlight.show()

    def deactivate_feature(self) -> None:
        """Deactivate the current foreground highlight.

        Restore the background highlight for the previously active feature.
        """
        self._remove_active_highlight()

    def remove_features(self, feature_keys: Set[FeatureKey]) -> None:
        """Remove stored highlights for the specified features.

        :param feature_keys: Feature keys to remove from the handler.
        """
        for feature_key in feature_keys:
            self._results.pop(feature_key, None)

            highlight = self._highlights.pop(feature_key, None)
            if highlight is not None:
                highlight.hide()

            if feature_key == self._active_feature_key:
                self._remove_active_highlight()

    def clear(self) -> None:
        """Clear all registered highlights and stored identify results."""
        self._remove_active_highlight()

        for highlight in self._highlights.values():
            highlight.hide()
        self._highlights.clear()
        self._results.clear()

    def _create_highlight(
        self, result: QgsMapToolIdentify.IdentifyResult
    ) -> QgsHighlight:
        return QgsHighlight(
            self._canvas,
            result.mFeature,
            cast(QgsVectorLayer, result.mLayer),
        )

    def _apply_background_style(self, highlight: QgsHighlight) -> None:
        highlight.applyDefaultStyle()
        selection_color = QgsProject.instance().selectionColor()
        highlight.setColor(selection_color)
        highlight.setFillColor(selection_color)

    def _remove_active_highlight(self) -> None:
        # Restore the background highlight for the previously active feature
        if self._active_feature_key is not None:
            background = self._highlights.get(self._active_feature_key)
            if background is not None:
                background.show()

        if self._active_highlight is not None:
            self._active_highlight.hide()
            self._active_highlight = None
        self._active_feature_key = None
