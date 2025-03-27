import functools
import random
import shutil
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable, Dict, Tuple

from qgis.core import (
    QgsFeature,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
    QgsWkbTypes,
    edit,
)

from nextgis_connect.compat import WkbType
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.resources.ngw_data_type import NgwDataType
from tests.magic_qobject_mock import MagicQObjectMock
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestData,
)


def random_feature(
    wkb_type: WkbType, fields: QgsFields, fid_field: str = "fid"
) -> QgsFeature:
    wkb_type = QgsWkbTypes.flatType(QgsWkbTypes.singleType(wkb_type))
    feature = QgsFeature(fields)

    # Set geometry with a 10% chance of being None
    if random.random() <= 0.1:
        feature.setGeometry(None)
    else:
        if wkb_type == WkbType.Point:
            feature.setGeometry(
                QgsGeometry.fromPointXY(
                    QgsPointXY(
                        random.uniform(-180, 180), random.uniform(-90, 90)
                    )
                )
            )
        elif wkb_type == WkbType.LineString:
            feature.setGeometry(
                QgsGeometry.fromPolylineXY(
                    [
                        QgsPointXY(
                            random.uniform(-180, 180), random.uniform(-90, 90)
                        ),
                        QgsPointXY(
                            random.uniform(-180, 180), random.uniform(-90, 90)
                        ),
                    ]
                )
            )
        elif wkb_type == WkbType.Polygon:
            feature.setGeometry(
                QgsGeometry.fromPolygonXY(
                    [
                        [
                            QgsPointXY(
                                random.uniform(-180, 180),
                                random.uniform(-90, 90),
                            ),
                            QgsPointXY(
                                random.uniform(-180, 180),
                                random.uniform(-90, 90),
                            ),
                            QgsPointXY(
                                random.uniform(-180, 180),
                                random.uniform(-90, 90),
                            ),
                            QgsPointXY(
                                random.uniform(-180, 180),
                                random.uniform(-90, 90),
                            ),
                        ]
                    ]
                )
            )
        else:
            feature.setGeometry(None)

    # Set attributes with a 20% chance of being None
    for i in range(fields.count()):
        field = fields.field(i)
        if field.name() == fid_field:
            continue

        if random.random() <= 0.2:
            feature.setAttribute(i, None)
        else:
            if field.type() == NgwDataType.INTEGER:
                feature.setAttribute(i, random.randint(-1000, 1000))
            elif field.type() == NgwDataType.BIGINT:
                feature.setAttribute(i, random.randint(-1000000, 1000000))
            elif field.type() == NgwDataType.REAL:
                feature.setAttribute(i, random.uniform(-1000.0, 1000.0))
            elif field.type() == NgwDataType.STRING:
                string_value = "".join(
                    random.choices(
                        "abcdefghijklmnopqrstuvwxyz'\"",
                        k=random.randint(5, 10),
                    )
                )
                wrap_random = random.random()
                if wrap_random <= 0.25:
                    string_value = f"'{string_value}'"
                elif wrap_random <= 0.50:
                    string_value = f'"{string_value}"'
                feature.setAttribute(i, string_value)

            elif field.type() == NgwDataType.DATE:
                feature.setAttribute(
                    i,
                    date(
                        random.randint(1900, 2100),
                        random.randint(1, 12),
                        random.randint(1, 28),
                    ).isoformat(),
                )
            elif field.type() == NgwDataType.TIME:
                feature.setAttribute(
                    i,
                    time(
                        random.randint(0, 23),
                        random.randint(0, 59),
                        random.randint(0, 59),
                    ).isoformat(),
                )
            elif field.type() == NgwDataType.DATETIME:
                feature.setAttribute(
                    i,
                    datetime(
                        random.randint(1900, 2100),
                        random.randint(1, 12),
                        random.randint(1, 28),
                        random.randint(0, 23),
                        random.randint(0, 59),
                        random.randint(0, 59),
                    ).isoformat(),
                )
            else:
                raise NotImplementedError

    return feature


def mock_container(
    test_data: TestData,
    *,
    is_versioning_enabled: bool = False,
    extra_features_count: int = 0,
    empty_features: bool = False,
    **metadata_values: Dict,
) -> Callable:
    def create_container_mock(
        self: NgConnectTestCase,
    ) -> Tuple[MagicQObjectMock, QgsVectorLayer]:
        ngw_layer = self.resource(test_data)
        assert isinstance(ngw_layer, NGWVectorLayer)
        qgs_layer = self.layer(test_data)
        assert isinstance(qgs_layer, QgsVectorLayer)

        container_path = self.create_temp_file(".gpkg")

        factory = DetachedLayerFactory()
        factory.create_initial_container(ngw_layer, container_path)

        # Handle extra features
        source_path = self.data_path(test_data)
        temp_path = None
        if extra_features_count > 0:
            temp_path = self.create_temp_file(".gpkg")
            shutil.copyfile(source_path, temp_path)

            temp_layer = QgsVectorLayer(
                detached_layer_uri(temp_path), "temp_layer", "ogr"
            )
            temp_fields = QgsFields()
            for field in temp_layer.fields():
                ngw_field = ngw_layer.fields.find_with(keyname=field.name())
                temp_fields.append(
                    field if ngw_field is None else ngw_field.to_qgs_field()
                )

            with edit(temp_layer):
                features = [
                    random_feature(temp_layer.wkbType(), temp_fields)
                    if not empty_features
                    else QgsFeature(temp_fields)
                    for _ in range(extra_features_count)
                ]
                temp_layer.dataProvider().addFeatures(features)

            source_path = Path(temp_path)

        factory.fill_container(
            ngw_layer,
            source_path=source_path,
            container_path=container_path,
        )

        metadata = replace(
            container_metadata(container_path),
            epoch=1 if is_versioning_enabled else None,
            version=1 if is_versioning_enabled else None,
            **metadata_values,
        )

        container_mock = MagicQObjectMock()
        container_mock.metadata = metadata
        container_mock.path = container_path

        qgs_layer = QgsVectorLayer(
            detached_layer_uri(container_path, metadata),
            metadata.layer_name,
            "ogr",
        )

        return container_mock, qgs_layer

    def decorator(
        method: Callable[..., None],
    ) -> Callable[..., None]:
        @functools.wraps(method)
        def wrapper(
            self: NgConnectTestCase, *args: Tuple, **kwargs: Dict
        ) -> None:
            container_mock, qgs_layer = create_container_mock(self)
            try:
                method(self, container_mock, qgs_layer, *args, **kwargs)
            finally:
                container_mock.deleteLater()

        return wrapper

    return decorator
