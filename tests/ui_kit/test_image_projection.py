# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.

from pathlib import Path

from nextgis_connect.ui_kit.widgets import image_projection


class _Dataset:
    def __init__(self, packets):
        self._packets = packets

    def GetMetadata_List(self, domain: str):
        assert domain == "xml:XMP"
        return self._packets


def test_projection_type_from_file_meta_requires_expected_structure() -> None:
    assert (
        image_projection.projection_type_from_file_meta(
            {"panorama": {"ProjectionType": "equirectangular"}}
        )
        == "equirectangular"
    )
    assert image_projection.projection_type_from_file_meta({}) is None
    assert image_projection.projection_type_from_file_meta(None) is None


def test_projection_type_from_image_reads_gpano_xmp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "panorama.jpg"
    image_path.write_bytes(b"image")
    dataset = _Dataset(
        [
            """
            <x:xmpmeta xmlns:x="adobe:ns:meta/">
              <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
                <rdf:Description xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"
                    GPano:ProjectionType="equirectangular" />
              </rdf:RDF>
            </x:xmpmeta>
            """
        ]
    )
    monkeypatch.setattr(image_projection.gdal, "OpenEx", lambda *_: dataset)

    assert image_projection.projection_type_from_image(image_path) == (
        "equirectangular"
    )


def test_projection_type_from_image_ignores_invalid_xmp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"image")
    monkeypatch.setattr(
        image_projection.gdal,
        "OpenEx",
        lambda *_: _Dataset(["not xml"]),
    )

    assert image_projection.projection_type_from_image(image_path) is None


def test_is_equirectangular_projection_is_case_sensitive() -> None:
    assert image_projection.is_equirectangular_projection("equirectangular")
    assert not image_projection.is_equirectangular_projection(
        "Equirectangular"
    )
    assert not image_projection.is_equirectangular_projection(None)
