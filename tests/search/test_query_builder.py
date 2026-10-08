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

from typing import List

import pytest

from nextgis_connect.features.search.domain.query import (
    NgwSearchQueryBuilder,
    SearchQueryParser,
)


class OwnerResolverStub:
    def resolve_equal(self, values: List[str]) -> List[int]:
        if values == ["Alice Smith"]:
            return [1]

        if values == ["me", "Alice Smith"]:
            return [1, 7]

        return []

    def resolve_like(self, operator: str, value: str) -> List[int]:
        if operator == "__ilike" and value == "Alice%":
            return [1]

        if operator == "__like" and value == "Bob%":
            return [2]

        return []


def test_builder_creates_default_ilike_query() -> None:
    queries = _build_queries("Roads")

    assert queries == ["display_name__ilike=%25Roads%25"]


def test_builder_creates_exact_default_query() -> None:
    queries = _build_queries('"Roads"')

    assert queries == ["display_name=Roads"]


def test_builder_creates_integer_in_query() -> None:
    queries = _build_queries("@id IN (1, 2)")

    assert queries == ["id__in=1,2"]


def test_builder_expands_unsupported_in_query() -> None:
    queries = _build_queries("@root IN (1, 2)")

    assert queries == ["root=1", "root=2"]


def test_builder_creates_string_like_query() -> None:
    queries = _build_queries('@name LIKE "Road%"')

    assert queries == ["display_name__like=Road%25"]


def test_builder_resolves_owner_name_query() -> None:
    queries = _build_queries("@owner = Alice Smith")

    assert queries == ["owner=1"]


def test_builder_resolves_owner_ilike_query() -> None:
    queries = _build_queries('@owner ILIKE "Alice%"')

    assert queries == ["owner=1"]


def test_builder_resolves_owner_like_query() -> None:
    queries = _build_queries('@owner LIKE "Bob%"')

    assert queries == ["owner=2"]


def test_builder_combines_and_queries() -> None:
    queries = _build_queries('@type = vector_layer AND @name LIKE "Road%"')

    assert queries == ["cls=vector_layer&display_name__like=Road%25"]


def test_builder_combines_or_queries() -> None:
    queries = _build_queries("@id = 1 OR @id = 2")

    assert queries == ["id=1", "id=2"]


def test_builder_combines_or_resource_type_queries() -> None:
    queries = _build_queries("@type = vector_layer OR @type = raster_layer")

    assert queries == ["cls=vector_layer", "cls=raster_layer"]


def test_builder_falls_back_on_unknown_tag() -> None:
    queries = _build_queries("@missing = 1")

    assert queries == ["display_name__ilike=%25%40missing+%3D+1%25"]


@pytest.mark.parametrize(
    ("search_string", "expected_queries"),
    [
        (
            '@metadata["priority"] = "high"',
            ["resmeta__ilike[priority]=%25high%25"],
        ),
        (
            '@metadata["priority"] = 10',
            [
                "resmeta__ilike[priority]=%2510%25",
                "resmeta__json[priority]=10",
            ],
        ),
        (
            '@metadata["enabled"] = true',
            [
                "resmeta__ilike[enabled]=%25true%25",
                "resmeta__json[enabled]=true",
            ],
        ),
    ],
)
def test_builder_creates_metadata_queries(
    search_string: str,
    expected_queries: List[str],
) -> None:
    queries = _build_queries(search_string)

    assert queries == expected_queries


def _build_queries(search_string: str) -> List[str]:
    parsed_search = SearchQueryParser().parse(search_string)
    return NgwSearchQueryBuilder(OwnerResolverStub()).build(parsed_search)
