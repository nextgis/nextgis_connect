# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

from typing import Sequence, Tuple

from qgis.core import QgsMapLayer, QgsMapLayerStyle
from qgis.PyQt.QtXml import QDomDocument


def replace_layer_styles(
    layer: QgsMapLayer,
    styles: Sequence[Tuple[str, str]],
) -> None:
    """Replace a layer's style collection, restoring it on installation failure."""
    if not styles:
        raise ValueError("No QGIS styles are available")
    for _, qml in styles:
        document = QDomDocument()
        parsed = document.setContent(qml)
        valid = parsed[0] if isinstance(parsed, tuple) else bool(parsed)
        if not valid or document.documentElement().tagName() != "qgis":
            raise ValueError("Invalid QGIS style")
    prepared = [(name, QgsMapLayerStyle(qml)) for name, qml in styles]
    if len({name for name, _ in prepared}) != len(prepared):
        raise ValueError("Style names must be unique")
    if any(not style.isValid() for _, style in prepared):
        raise ValueError("Invalid QGIS style")
    manager = layer.styleManager()
    assert manager is not None
    active = manager.currentStyle()
    current = QgsMapLayerStyle()
    current.readFromLayer(layer)
    backup = [
        (
            name,
            current
            if name == active
            else QgsMapLayerStyle(manager.style(name)),
        )
        for name in manager.styles()
    ]

    def install(items, selected):
        temporary = "_nextgis_style_transfer"
        names = set(manager.styles()) | {name for name, _ in items}
        while temporary in names:
            temporary += "_"
        if not manager.renameStyle(manager.currentStyle(), temporary):
            raise RuntimeError("Could not preserve current style")
        for name in list(manager.styles()):
            if name != temporary and not manager.removeStyle(name):
                raise RuntimeError("Could not remove style")
        for name, style in items:
            if not manager.addStyle(name, style):
                raise RuntimeError("Could not add style")
        if not manager.setCurrentStyle(selected):
            raise RuntimeError("Could not activate style")
        if not manager.removeStyle(temporary):
            raise RuntimeError("Could not remove temporary style")

    try:
        install(
            prepared, active if active in dict(prepared) else prepared[0][0]
        )
    except Exception:
        install(backup, active)
        raise
    layer.triggerRepaint()
