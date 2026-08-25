# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.

"""Compatibility imports for optional Qt OpenGL widgets.

QGIS does not expose QtOpenGL modules through ``qgis.PyQt`` on every Qt 6
build. Import the matching binding only at this boundary so the rest of the
plugin can keep using the QGIS Qt wrapper.
"""

from importlib import import_module
from typing import Any, Optional, Tuple, Type

from qgis.PyQt.QtCore import QT_VERSION_STR
from qgis.PyQt.QtGui import (
    QGuiApplication,
    QOffscreenSurface,
    QOpenGLContext,
    QSurfaceFormat,
)
from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.platform.logging import logger

OPENGL_AVAILABLE = False
QOpenGLWidget: Optional[Type[QWidget]] = None
QOpenGLBuffer: Any = None
QOpenGLShader: Any = None
QOpenGLShaderProgram: Any = None
QOpenGLTexture: Any = None
QOpenGLVertexArrayObject: Any = None
_OPENGL_CONTEXT_AVAILABLE: Optional[bool] = None


def panorama_renderer_available() -> bool:
    """Return whether the panorama renderer is safe for this runtime."""
    if not OPENGL_AVAILABLE:
        return False
    return _opengl_context_available()


def _opengl_context_available() -> bool:
    global _OPENGL_CONTEXT_AVAILABLE
    if _OPENGL_CONTEXT_AVAILABLE is not None:
        return _OPENGL_CONTEXT_AVAILABLE

    if QGuiApplication.platformName() == "offscreen":
        # The test-only platform plugin tears down manually created OpenGL
        # contexts outside Qt's normal window lifecycle.
        _OPENGL_CONTEXT_AVAILABLE = True
        logger.debug(
            "Panorama OpenGL preflight skipped for offscreen Qt platform"
        )
        return _OPENGL_CONTEXT_AVAILABLE

    try:
        surface = QOffscreenSurface()
        surface.setFormat(QSurfaceFormat.defaultFormat())
        surface.create()

        context = QOpenGLContext()
        context.setFormat(surface.format())
        context_created = context.create()
        context_current = context_created and context.makeCurrent(surface)
        if context_current:
            context.doneCurrent()

        _OPENGL_CONTEXT_AVAILABLE = bool(
            surface.isValid() and context.isValid() and context_current
        )
        logger.debug(
            "Panorama OpenGL preflight: surface_valid=%s, context_created=%s, "
            "context_valid=%s, context_current=%s",
            surface.isValid(),
            context_created,
            context.isValid(),
            context_current,
        )
    except Exception:
        _OPENGL_CONTEXT_AVAILABLE = False
        logger.exception("Panorama OpenGL preflight failed")
    return _OPENGL_CONTEXT_AVAILABLE


try:
    if QT_VERSION_STR.startswith("5."):
        qt_gui = import_module("qgis.PyQt.QtGui")
        QOpenGLBuffer = qt_gui.QOpenGLBuffer
        QOpenGLShader = qt_gui.QOpenGLShader
        QOpenGLShaderProgram = qt_gui.QOpenGLShaderProgram
        QOpenGLTexture = qt_gui.QOpenGLTexture
        QOpenGLVertexArrayObject = qt_gui.QOpenGLVertexArrayObject
        QOpenGLWidget = import_module("qgis.PyQt.QtWidgets").QOpenGLWidget
    else:
        # QGIS Qt 6 wrappers omit these modules, while QGIS itself uses the
        # same PyQt binding. Keep this exceptional import confined here.
        qt_open_gl = import_module("PyQt6.QtOpenGL")
        QOpenGLBuffer = qt_open_gl.QOpenGLBuffer
        QOpenGLShader = qt_open_gl.QOpenGLShader
        QOpenGLShaderProgram = qt_open_gl.QOpenGLShaderProgram
        QOpenGLTexture = qt_open_gl.QOpenGLTexture
        QOpenGLVertexArrayObject = qt_open_gl.QOpenGLVertexArrayObject
        QOpenGLWidget = import_module("PyQt6.QtOpenGLWidgets").QOpenGLWidget
except ImportError:
    pass
else:
    OPENGL_AVAILABLE = True


def opengl_classes() -> Tuple[Any, Any, Any, Any, Any, Type[QWidget]]:
    """Return required Qt OpenGL classes when the runtime provides them."""
    if not OPENGL_AVAILABLE or QOpenGLWidget is None:
        raise RuntimeError("Qt OpenGL widgets are unavailable")

    return (
        QOpenGLBuffer,
        QOpenGLShader,
        QOpenGLShaderProgram,
        QOpenGLTexture,
        QOpenGLVertexArrayObject,
        QOpenGLWidget,
    )
