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

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from nextgis_connect.features.search.domain.resource_blueprint import (
    ResourceBlueprintLabelParser,
    ResourceBlueprintTypeParser,
)


@dataclass(frozen=True)
class ResourceType:
    identity: str
    label: str
    category: str = ""

    @property
    def sort_key(self) -> Tuple[bool, str, str, str]:
        _, separator, kind = self.identity.partition("_")
        return (
            not bool(separator),
            kind.casefold(),
            self.label.casefold(),
            self.identity,
        )


@dataclass(frozen=True)
class ResourceCategory:
    identity: str
    label: str
    order: float


@dataclass(frozen=True)
class ResourceTypeGroup:
    label: Optional[str]
    resources: Tuple[ResourceType, ...]


class ResourceTypeCatalogParser:
    def parse(self, blueprint: object) -> List[ResourceTypeGroup]:
        payload = self._mapping(blueprint, "blueprint")
        resources = self._resources(payload)
        categories = self._categories(payload)
        groups: Dict[str, List[ResourceType]] = {}
        for resource in resources:
            groups.setdefault(resource.category, []).append(resource)

        ordered_categories = [
            categories.get(
                identity, ResourceCategory(identity, identity, float("inf"))
            )
            for identity in groups
        ]
        ordered_categories.sort(
            key=lambda category: (category.order, category.identity)
        )
        return [
            ResourceTypeGroup(
                category.label or (None if categories else ""),
                tuple(
                    sorted(
                        groups[category.identity],
                        key=lambda resource: resource.sort_key,
                    )
                ),
            )
            for category in ordered_categories
        ]

    def _resources(self, payload: Mapping[str, object]) -> List[ResourceType]:
        definitions = self._mapping(payload.get("resources", {}), "resources")
        parsed = {
            identity: self._resource(identity, definition)
            for identity, definition in definitions.items()
        }
        identities = ResourceBlueprintTypeParser().parse(payload)
        labels = ResourceBlueprintLabelParser().parse(payload)
        return [
            parsed.get(
                identity,
                ResourceType(identity, labels.get(identity, identity)),
            )
            for identity in identities
        ]

    def _resource(self, identity: str, value: object) -> ResourceType:
        definition = self._mapping(value, identity)
        return ResourceType(
            identity,
            self._string(definition.get("label", identity), "label"),
            self._string(definition.get("category", ""), "category"),
        )

    def _categories(
        self, payload: Mapping[str, object]
    ) -> Dict[str, ResourceCategory]:
        definitions = self._mapping(
            payload.get("categories", {}), "categories"
        )
        return {
            identity: self._category(identity, definition)
            for identity, definition in definitions.items()
        }

    def _category(self, identity: str, value: object) -> ResourceCategory:
        definition = self._mapping(value, identity)
        order = definition.get("order")
        return ResourceCategory(
            identity,
            self._string(definition.get("label", identity), "label"),
            float(order) if isinstance(order, (int, float)) else float("inf"),
        )

    @staticmethod
    def _mapping(value: object, field: str) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise ValueError(f"Blueprint {field} must be an object")
        return value

    @staticmethod
    def _string(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Blueprint {field} must be a string")
        return value
