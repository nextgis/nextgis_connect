# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.

"""OpenGL canvas for equirectangular panoramas."""

import ctypes
from array import array
from math import cos, pi, sin
from typing import Any, Optional, Tuple, cast

from qgis.PyQt.QtCore import (
    QEasingCurve,
    QPoint,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QImage,
    QMatrix4x4,
    QMouseEvent,
    QShowEvent,
    QWheelEvent,
)
from qgis.PyQt.QtWidgets import QWidget

from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.opengl import (
    OPENGL_AVAILABLE,
    opengl_classes,
)

_OpenGLWidget = opengl_classes()[-1] if OPENGL_AVAILABLE else QWidget


class PanoramaWidget(_OpenGLWidget):  # type: ignore[misc]
    """Display an interactive equirectangular panorama using OpenGL."""

    view_direction_changed = pyqtSignal(float, float, float)
    initialization_failed = pyqtSignal()
    rendering_failed = pyqtSignal()

    MIN_FOV = 25.0
    MAX_FOV = 100.0
    DEFAULT_FOV = 70.0
    ROTATION_SENSITIVITY = 0.15
    FOV_STEP = 5.0
    SPHERE_SEGMENTS = 48
    SPHERE_RINGS = 24
    INITIALIZATION_TIMEOUT_MS = 1000
    INTERACTION_HINT_DELAY_MS = 350
    INTERACTION_HINT_DURATION_MS = 45000
    INTERACTION_HINT_YAW = -360.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._yaw = 0.0
        self._pitch = 0.0
        self._fov = self.DEFAULT_FOV
        self._last_mouse_position = QPoint()
        self._is_dragging = False
        self._program: Any = None
        self._vertex_array: Any = None
        self._vertex_buffer: Any = None
        self._texture: Any = None
        self._vertex_count = 0
        self._gl: Optional[_OpenGLFunctions] = None
        self._requires_frame_validation = False
        self._is_frame_validation_scheduled = False
        self._is_initialized = False
        self._is_initialization_check_scheduled = False
        self._is_shutdown = False
        self._has_shown_interaction_hint = False
        self._is_interaction_hint_scheduled = False
        self._interaction_hint_timer = QTimer(self)
        self._interaction_hint_timer.setSingleShot(True)
        self._interaction_hint_timer.setInterval(
            self.INTERACTION_HINT_DELAY_MS
        )
        self._interaction_hint_timer.timeout.connect(
            self._show_interaction_hint
        )
        self._interaction_hint_animation = QVariantAnimation(self)
        self._interaction_hint_animation.setDuration(
            self.INTERACTION_HINT_DURATION_MS
        )
        self._interaction_hint_animation.setStartValue(0.0)
        self._interaction_hint_animation.setEndValue(self.INTERACTION_HINT_YAW)
        self._interaction_hint_animation.setLoopCount(-1)
        self._interaction_hint_animation.setEasingCurve(
            QEasingCurve.Type.Linear
        )
        self._interaction_hint_animation.valueChanged.connect(
            self._set_interaction_hint_yaw
        )

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    @property
    def fov(self) -> float:
        return self._fov

    @property
    def is_dragging(self) -> bool:
        return self._is_dragging

    def set_image(self, image: QImage) -> None:
        """Set the equirectangular image to render."""
        self._image = QImage(image)
        self._requires_frame_validation = True
        self._reset_interaction_hint()
        widget = cast(Any, self)
        if widget.context() is not None:
            widget.makeCurrent()
            if not self._create_texture():
                logger.warning("Failed to update panorama texture")
                self.initialization_failed.emit()
            widget.doneCurrent()
        self.update()

    def reset_view(self) -> None:
        """Restore the default direction and field of view."""
        self._yaw = 0.0
        self._pitch = 0.0
        self._fov = self.DEFAULT_FOV
        self.update()

    def shutdown(self) -> None:
        """Release OpenGL resources while the widget context is still valid."""
        self._is_shutdown = True
        self._requires_frame_validation = False
        self._interaction_hint_timer.stop()
        self._interaction_hint_animation.stop()
        self._cleanup()

    def start_drag(self, position: QPoint) -> None:
        """Start rotating from an overlay mouse position."""
        self._cancel_interaction_hint()
        self._is_dragging = True
        self._last_mouse_position = position
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def drag_to(self, position: QPoint) -> None:
        """Rotate to an overlay mouse position."""
        if not self._is_dragging:
            return

        delta = position - self._last_mouse_position
        self._last_mouse_position = position
        self._yaw += delta.x() * self.ROTATION_SENSITIVITY
        self._pitch = max(
            -89.0,
            min(89.0, self._pitch + delta.y() * self.ROTATION_SENSITIVITY),
        )
        self.update()
        self.view_direction_changed.emit(self._yaw, self._pitch, self._fov)

    def end_drag(self) -> None:
        """Stop an overlay-driven rotation."""
        if not self._is_dragging:
            return

        self._is_dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def zoom_in(self) -> None:
        self._cancel_interaction_hint()
        self._set_fov(self._fov - self.FOV_STEP)

    def zoom_out(self) -> None:
        self._cancel_interaction_hint()
        self._set_fov(self._fov + self.FOV_STEP)

    def initializeGL(self) -> None:
        """Initialize shaders, sphere geometry, and the current texture."""
        logger.debug("Initializing panorama OpenGL renderer")
        try:
            self._gl = _OpenGLFunctions()
            self._create_program()
            self._create_sphere()
            if not self._create_texture():
                raise RuntimeError("Failed to create panorama texture")
        except Exception:
            logger.exception("Failed to initialize panorama OpenGL renderer")
            self._cleanup()
            self.initialization_failed.emit()
            return
        self._is_initialized = True
        context = cast(Any, self).context()
        if context is not None:
            self._log_context(context)
            context.aboutToBeDestroyed.connect(self._cleanup)

    def showEvent(self, event: QShowEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        super().showEvent(event)
        self._schedule_initialization_check()

    def _schedule_initialization_check(self) -> None:
        if (
            self._is_shutdown
            or self._is_initialized
            or self._is_initialization_check_scheduled
        ):
            return

        self._is_initialization_check_scheduled = True
        logger.debug("Waiting for panorama OpenGL context initialization")
        QTimer.singleShot(
            self.INITIALIZATION_TIMEOUT_MS,
            self._validate_initialization,
        )

    def _validate_initialization(self) -> None:
        self._is_initialization_check_scheduled = False
        if self._is_shutdown or self._is_initialized or not self.isVisible():
            return

        logger.warning(
            "Panorama OpenGL context did not initialize within %d ms; "
            "falling back to flat preview",
            self.INITIALIZATION_TIMEOUT_MS,
        )
        self.initialization_failed.emit()

    def resizeGL(self, width: int, height: int) -> None:
        if self._gl is not None:
            self._gl.viewport(width, height)

    def paintGL(self) -> None:
        if self._gl is None:
            return

        self._gl.clear()
        if (
            self._program is None
            or self._texture is None
            or not self._texture.isCreated()
        ):
            return

        projection = QMatrix4x4()
        projection.perspective(
            self._fov,
            self.width() / max(1, self.height()),
            0.1,
            100.0,
        )
        view = QMatrix4x4()
        view.rotate(-self._pitch, 1.0, 0.0, 0.0)
        view.rotate(-self._yaw, 0.0, 1.0, 0.0)

        self._program.bind()
        self._program.setUniformValue("projection", projection)
        self._program.setUniformValue("view", view)
        self._program.setUniformValue("panorama", 0)
        self._texture.bind(0)
        self._vertex_array.bind()
        self._gl.draw_triangles(self._vertex_count)
        self._vertex_array.release()
        self._texture.release(0)
        self._program.release()
        self._schedule_frame_validation()
        self._schedule_interaction_hint()

    def _schedule_interaction_hint(self) -> None:
        if (
            self._has_shown_interaction_hint
            or self._is_interaction_hint_scheduled
            or self._is_shutdown
            or not self.isVisible()
        ):
            return

        self._is_interaction_hint_scheduled = True
        self._interaction_hint_timer.start()

    def _show_interaction_hint(self) -> None:
        self._is_interaction_hint_scheduled = False
        if (
            self._has_shown_interaction_hint
            or self._is_shutdown
            or not self.isVisible()
        ):
            return

        self._has_shown_interaction_hint = True
        self._interaction_hint_animation.start()

    def _reset_interaction_hint(self) -> None:
        self._interaction_hint_timer.stop()
        self._is_interaction_hint_scheduled = False
        self._has_shown_interaction_hint = False
        self._interaction_hint_animation.stop()

    def _cancel_interaction_hint(self) -> None:
        if self._has_shown_interaction_hint:
            self._interaction_hint_animation.stop()
        self._has_shown_interaction_hint = True

    def _set_interaction_hint_yaw(self, value: Any) -> None:
        self._yaw = float(value)
        self.update()

    def _schedule_frame_validation(self) -> None:
        if (
            not self._requires_frame_validation
            or self._is_frame_validation_scheduled
        ):
            return

        self._is_frame_validation_scheduled = True
        QTimer.singleShot(0, self._validate_rendered_frame)

    def _validate_rendered_frame(self) -> None:
        self._is_frame_validation_scheduled = False
        if not self._requires_frame_validation or not self.isVisible():
            return

        self._requires_frame_validation = False
        frame = cast(Any, self).grabFramebuffer()
        if not self._is_blank_frame(frame):
            return

        logger.warning(
            "Panorama renderer produced a blank frame: framebuffer=%dx%d",
            frame.width(),
            frame.height(),
        )
        self.rendering_failed.emit()

    def _log_context(self, context: Any) -> None:
        surface_format = context.format()
        if self._gl is None:
            renderer, vendor, version = "unknown", "unknown", "unknown"
        else:
            renderer, vendor, version = self._gl.driver_info()
        logger.debug(
            "Initialized panorama OpenGL renderer: context_valid=%s, "
            "format=%d.%d, profile=%s, renderable_type=%s, vendor=%s, "
            "renderer=%s, version=%s",
            context.isValid(),
            surface_format.majorVersion(),
            surface_format.minorVersion(),
            surface_format.profile(),
            surface_format.renderableType(),
            vendor,
            renderer,
            version,
        )

    @staticmethod
    def _is_blank_frame(frame: QImage) -> bool:
        if frame.isNull():
            return True

        sample_positions = (
            (0, 0),
            (frame.width() // 2, 0),
            (frame.width() - 1, 0),
            (0, frame.height() // 2),
            (frame.width() // 2, frame.height() // 2),
            (frame.width() - 1, frame.height() // 2),
            (0, frame.height() - 1),
            (frame.width() // 2, frame.height() - 1),
            (frame.width() - 1, frame.height() - 1),
        )
        colors = [frame.pixelColor(x, y) for x, y in sample_positions]
        return all(
            color.red() >= 250 and color.green() >= 250 and color.blue() >= 250
            for color in colors
        ) or all(
            abs(color.red() - 32) <= 4
            and abs(color.green() - 35) <= 4
            and abs(color.blue() - 38) <= 4
            for color in colors
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        self.start_drag(event.pos())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if not self._is_dragging:
            super().mouseMoveEvent(event)
            return

        self.drag_to(event.pos())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self._is_dragging
        ):
            super().mouseReleaseEvent(event)
            return

        self.end_drag()
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if event.angleDelta().y() > 0:
            self.zoom_in()
        elif event.angleDelta().y() < 0:
            self.zoom_out()
        else:
            return
        event.accept()

    def _set_fov(self, value: float) -> None:
        self._fov = max(self.MIN_FOV, min(self.MAX_FOV, value))
        self.update()
        self.view_direction_changed.emit(self._yaw, self._pitch, self._fov)

    def _create_program(self) -> None:
        _, shader, shader_program, _, _ = opengl_classes()[:5]
        program = shader_program()
        shader_type = getattr(shader, "ShaderTypeBit", shader)
        if not program.addShaderFromSourceCode(
            shader_type.Vertex,
            _VERTEX_SHADER,
        ):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(
            shader_type.Fragment,
            _FRAGMENT_SHADER,
        ):
            raise RuntimeError(program.log())
        if not program.link():
            raise RuntimeError(program.log())
        self._program = program

    def _create_sphere(self) -> None:
        buffer, shader_program, _, _, vertex_array = opengl_classes()[:5]
        del shader_program
        vertices = _sphere_vertices(self.SPHERE_SEGMENTS, self.SPHERE_RINGS)
        self._vertex_count = len(vertices) // 5

        self._vertex_array = vertex_array(self)
        self._vertex_array.create()
        self._vertex_array.bind()

        buffer_type = getattr(buffer, "Type", buffer)
        self._vertex_buffer = buffer(buffer_type.VertexBuffer)
        self._vertex_buffer.create()
        self._vertex_buffer.bind()
        usage = getattr(buffer, "UsagePattern", buffer)
        self._vertex_buffer.setUsagePattern(usage.StaticDraw)
        self._vertex_buffer.allocate(vertices.tobytes(), len(vertices) * 4)

        self._program.bind()
        attribute_type = getattr(self._program, "AttributeType", None)
        float_type = attribute_type.Float if attribute_type else 0x1406
        stride = 5 * 4
        for attribute, offset, size in (
            ("position", 0, 3),
            ("texcoord", 12, 2),
        ):
            location = self._program.attributeLocation(attribute)
            self._program.enableAttributeArray(location)
            self._program.setAttributeBuffer(
                location,
                float_type,
                offset,
                size,
                stride,
            )
        self._program.release()
        self._vertex_buffer.release()
        self._vertex_array.release()

    def _create_texture(self) -> bool:
        if self._texture is not None:
            self._texture.destroy()
            self._texture = None
        if self._image.isNull():
            return False

        _, _, _, texture, _ = opengl_classes()[:5]
        self._texture = texture(self._image.mirrored())
        if not self._texture.isCreated():
            self._texture.create()
        filter_type = getattr(texture, "Filter", texture)
        self._texture.setMinMagFilters(filter_type.Linear, filter_type.Linear)
        wrap_mode = getattr(texture, "WrapMode", texture)
        self._texture.setWrapMode(wrap_mode.Repeat)
        if not self._texture.isCreated():
            self._texture.destroy()
            self._texture = None
            return False
        return True

    def _cleanup(self) -> None:
        widget = cast(Any, self)
        if widget.context() is None:
            return

        widget.makeCurrent()
        if self._texture is not None:
            self._texture.destroy()
            self._texture = None
        if self._vertex_buffer is not None:
            self._vertex_buffer.destroy()
            self._vertex_buffer = None
        if self._vertex_array is not None:
            self._vertex_array.destroy()
            self._vertex_array = None
        if self._program is not None:
            self._program.removeAllShaders()
        self._program = None
        widget.doneCurrent()


class _OpenGLFunctions:
    """Small portable subset of the OpenGL API used by ``PanoramaWidget``."""

    GL_COLOR_BUFFER_BIT = 0x00004000
    GL_DEPTH_BUFFER_BIT = 0x00000100
    GL_TRIANGLES = 0x0004
    GL_VENDOR = 0x1F00
    GL_RENDERER = 0x1F01
    GL_VERSION = 0x1F02

    def __init__(self) -> None:
        context = self._current_context()
        try:
            self._functions = context.functions()
        except AttributeError:
            self._functions = None
        if self._functions is None:
            self._viewport = self._function(
                context,
                "glViewport",
                None,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            )
            self._clear_color = self._function(
                context,
                "glClearColor",
                None,
                ctypes.c_float,
                ctypes.c_float,
                ctypes.c_float,
                ctypes.c_float,
            )
            self._clear = self._function(
                context, "glClear", None, ctypes.c_uint
            )
            self._draw_arrays = self._function(
                context,
                "glDrawArrays",
                None,
                ctypes.c_uint,
                ctypes.c_int,
                ctypes.c_int,
            )
            self._get_string = self._function(
                context, "glGetString", ctypes.c_char_p, ctypes.c_uint
            )

    def viewport(self, width: int, height: int) -> None:
        if self._functions is not None:
            self._functions.glViewport(0, 0, width, height)
            return
        self._viewport(0, 0, width, height)

    def clear(self) -> None:
        if self._functions is not None:
            self._functions.glClearColor(0.125, 0.137, 0.15, 1.0)
            self._functions.glClear(
                self.GL_COLOR_BUFFER_BIT | self.GL_DEPTH_BUFFER_BIT
            )
            return
        self._clear_color(0.125, 0.137, 0.15, 1.0)
        self._clear(self.GL_COLOR_BUFFER_BIT | self.GL_DEPTH_BUFFER_BIT)

    def draw_triangles(self, vertex_count: int) -> None:
        if self._functions is not None:
            self._functions.glDrawArrays(self.GL_TRIANGLES, 0, vertex_count)
            return
        self._draw_arrays(self.GL_TRIANGLES, 0, vertex_count)

    def driver_info(self) -> Tuple[str, str, str]:
        return (
            self._string(self.GL_RENDERER),
            self._string(self.GL_VENDOR),
            self._string(self.GL_VERSION),
        )

    def _string(self, name: int) -> str:
        if self._functions is not None:
            value = self._functions.glGetString(name)
        else:
            value = self._get_string(name)
        if value is None:
            return "unknown"
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    def _current_context(self) -> Any:
        from qgis.PyQt.QtGui import QOpenGLContext

        context = QOpenGLContext.currentContext()
        if context is None:
            raise RuntimeError("No current OpenGL context")
        return context

    def _function(
        self,
        context: Any,
        name: str,
        result_type: Any,
        *argument_types: Any,
    ) -> Any:
        address = context.getProcAddress(name.encode("ascii"))
        if not address:
            raise RuntimeError(f"OpenGL function is unavailable: {name}")
        return ctypes.CFUNCTYPE(result_type, *argument_types)(int(address))


def _sphere_vertices(segments: int, rings: int) -> array:
    vertices = array("f")
    for ring in range(rings):
        for segment in range(segments):
            next_segment = segment + 1
            next_ring = ring + 1
            vertices.extend(
                _sphere_vertex(segment, ring, segments, rings)
                + _sphere_vertex(next_segment, ring, segments, rings)
                + _sphere_vertex(next_segment, next_ring, segments, rings)
                + _sphere_vertex(segment, ring, segments, rings)
                + _sphere_vertex(next_segment, next_ring, segments, rings)
                + _sphere_vertex(segment, next_ring, segments, rings)
            )
    return vertices


def _sphere_vertex(
    segment: int,
    ring: int,
    segments: int,
    rings: int,
) -> array:
    longitude = 2.0 * pi * segment / segments
    latitude = pi * ring / rings - pi / 2.0
    radius = 10.0
    return array(
        "f",
        (
            radius * cos(latitude) * cos(longitude),
            radius * sin(latitude),
            radius * cos(latitude) * sin(longitude),
            segment / segments,
            ring / rings,
        ),
    )


_VERTEX_SHADER = """
attribute vec3 position;
attribute vec2 texcoord;
uniform mat4 projection;
uniform mat4 view;
varying vec2 texture_coordinate;

void main()
{
    texture_coordinate = texcoord;
    gl_Position = projection * view * vec4(position, 1.0);
}
"""

_FRAGMENT_SHADER = """
uniform sampler2D panorama;
varying vec2 texture_coordinate;

void main()
{
    gl_FragColor = texture2D(panorama, texture_coordinate);
}
"""
