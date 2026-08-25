# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.

"""Read image projection metadata used by the attachment preview."""

import re
import warnings
from pathlib import Path
from typing import Any, Mapping, Optional

from osgeo import gdal

EQUIRECTANGULAR_PROJECTION = "equirectangular"
_PROJECTION_TYPE_ATTRIBUTE = re.compile(
    r"(?:\b[\w.-]+:)?ProjectionType\s*=\s*(['\"])(.*?)\1",
    re.DOTALL,
)
_PROJECTION_TYPE_ELEMENT = re.compile(
    r"<(?:[\w.-]+:)?ProjectionType(?:\s[^>]*)?>(.*?)</(?:[\w.-]+:)?ProjectionType\s*>",
    re.DOTALL,
)


def is_equirectangular_projection(projection_type: Optional[str]) -> bool:
    """Return whether the NGW-supported projection is requested."""
    return projection_type == EQUIRECTANGULAR_PROJECTION


def projection_type_from_file_meta(file_meta: Any) -> Optional[str]:
    """Return a projection type from an NGW attachment ``file_meta`` value."""
    if not isinstance(file_meta, Mapping):
        return None

    panorama = file_meta.get("panorama")
    if not isinstance(panorama, Mapping):
        return None

    projection_type = panorama.get("ProjectionType")
    return projection_type if isinstance(projection_type, str) else None


def projection_type_from_image(path: Path) -> Optional[str]:
    """Read GPano ``ProjectionType`` from an image XMP packet.

    GDAL is bundled with the supported QGIS runtime and, unlike QImageReader,
    exposes the XMP domain without adding a plugin dependency.
    """
    if not path.is_file():
        return None

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Neither gdal.UseExceptions\(\) nor gdal.DontUseExceptions\(\)",
            category=FutureWarning,
        )
        dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY)
    if dataset is None:
        return None

    try:
        packets = dataset.GetMetadata_List("xml:XMP") or []
    finally:
        dataset = None

    for packet in packets:
        projection_type = _projection_type_from_xmp(packet)
        if projection_type is not None:
            return projection_type

    return None


def _projection_type_from_xmp(packet: str) -> Optional[str]:
    """Extract the GPano field without evaluating untrusted XML entities."""
    for pattern in (_PROJECTION_TYPE_ATTRIBUTE, _PROJECTION_TYPE_ELEMENT):
        match = pattern.search(packet)
        if match is not None:
            return (
                match.group(
                    2 if pattern is _PROJECTION_TYPE_ATTRIBUTE else 1
                ).strip()
                or None
            )
    return None
