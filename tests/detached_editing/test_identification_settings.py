# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.

import pytest

from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)


def test_image_preview_mode_defaults_to_panorama(reset_qgis_settings) -> None:
    del reset_qgis_settings

    assert IdentificationSettings().image_preview_mode == "panorama"


def test_image_preview_mode_is_persisted(reset_qgis_settings) -> None:
    del reset_qgis_settings

    settings = IdentificationSettings()
    settings.image_preview_mode = "flat"

    assert IdentificationSettings().image_preview_mode == "flat"


def test_image_preview_mode_rejects_unknown_value(
    reset_qgis_settings,
) -> None:
    del reset_qgis_settings

    with pytest.raises(ValueError, match="Unsupported image preview mode"):
        IdentificationSettings().image_preview_mode = "unsupported"
