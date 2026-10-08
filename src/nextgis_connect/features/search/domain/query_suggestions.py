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

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from nextgis_connect.features.search.domain.query import SearchQueryParser


@dataclass(frozen=True)
class ResourceTypeSuggestionContext:
    """Store resource-type completion context.

    Capture the already typed text and the currently open quote state
    for resource type suggestions.

    :ivar base_text: Text before the suggested resource type.
    :ivar closing_quote: Quote that must be appended to the suggestion.
    :ivar value_prefix: Lowercase resource type prefix to match.
    """

    base_text: str
    closing_quote: str
    value_prefix: str


@dataclass(frozen=True)
class OwnerSuggestionContext:
    """Store owner-name completion context.

    Capture the already typed text and the currently open quote state
    for owner suggestions.

    :ivar base_text: Text before the suggested owner name.
    :ivar closing_quote: Quote that must be appended to the suggestion.
    :ivar value_prefix: Lowercase owner prefix to match.
    """

    base_text: str
    closing_quote: str
    value_prefix: str


@dataclass(frozen=True)
class SearchOperation:
    """Store an operation completion option.

    Represent a visible operation name and the text inserted when that
    operation is selected.

    :ivar name: Operation name used for prefix matching.
    :ivar completion_text: Text appended to the current tag expression.
    """

    name: str
    completion_text: str


@dataclass(frozen=True)
class TagOperationSyntax:
    """Store completion operations for one search tag.

    Map a user-facing search tag to the operations that can be
    suggested after that tag.

    :ivar tag_name: User-facing tag name without the leading ``@``.
    :ivar operations: Operations available for the tag.
    """

    tag_name: str
    operations: Tuple[SearchOperation, ...]


class TextSearchSuggestionBuilder:
    """Build suggestions for structured search text.

    Provide completions for tag names, tag operations, logical
    operations, resource types, and owners.
    """

    LOGICAL_OPERATIONS: Tuple[str, ...] = ("AND", "OR")

    KEYWORDS: Tuple[str, ...] = (
        "id",
        "parent",
        "root",
        "owner",
        "type",
        "name",
        "keyname",
        "metadata",
    )
    _EQUAL_OPERATION = SearchOperation("=", "= ")
    _IN_OPERATION = SearchOperation("IN", "IN (")
    _QUOTED_IN_OPERATION = SearchOperation("IN", 'IN ("')
    _LIKE_OPERATION = SearchOperation("LIKE", 'LIKE "')
    _ILIKE_OPERATION = SearchOperation("ILIKE", 'ILIKE "')
    _OWNER_LIKE_OPERATION = SearchOperation("LIKE", "LIKE ")
    _OWNER_ILIKE_OPERATION = SearchOperation("ILIKE", "ILIKE ")

    _TAG_OPERATION_SYNTAXES: Tuple[TagOperationSyntax, ...] = (
        TagOperationSyntax(
            "id",
            (_EQUAL_OPERATION, _IN_OPERATION),
        ),
        TagOperationSyntax(
            "parent",
            (_EQUAL_OPERATION, _IN_OPERATION),
        ),
        TagOperationSyntax(
            "root",
            (_EQUAL_OPERATION,),
        ),
        TagOperationSyntax(
            "owner",
            (
                _EQUAL_OPERATION,
                _OWNER_LIKE_OPERATION,
                _OWNER_ILIKE_OPERATION,
                _QUOTED_IN_OPERATION,
            ),
        ),
        TagOperationSyntax(
            "type",
            (
                _EQUAL_OPERATION,
                _LIKE_OPERATION,
                _ILIKE_OPERATION,
                _QUOTED_IN_OPERATION,
            ),
        ),
        TagOperationSyntax(
            "name",
            (
                SearchOperation("=", '= "'),
                _LIKE_OPERATION,
                _ILIKE_OPERATION,
                _QUOTED_IN_OPERATION,
            ),
        ),
        TagOperationSyntax(
            "keyname",
            (
                SearchOperation("=", '= "'),
                _LIKE_OPERATION,
                _ILIKE_OPERATION,
                _QUOTED_IN_OPERATION,
            ),
        ),
    )

    _KEYWORD_PATTERN = re.compile(r"^@(?P<prefix>[a-z_]*)$", re.IGNORECASE)
    _OPERATION_PATTERN = re.compile(
        r"^@(?P<tag>[a-z_]+)(?P<separator>\s*)(?P<operation>[a-z]*)$",
        re.IGNORECASE,
    )
    _LOGICAL_OPERATION_PATTERN = re.compile(
        r"^(?P<expression>.+)\s+(?P<operation>[a-z]*)$",
        re.IGNORECASE,
    )
    _TYPE_PATTERN = re.compile(
        r"^@type(?P<before_equals>\s*)=(?P<after_equals>\s*)"
        r"(?P<quote>['\"]?)(?P<value>[a-z0-9_]*)$",
        re.IGNORECASE,
    )
    _OWNER_PATTERN = re.compile(
        r"^@owner(?P<before_equals>\s*)=(?P<after_equals>\s*)"
        r"(?P<quote>['\"]?)(?P<value>[^'\"]*)$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        query_parser: Optional[SearchQueryParser] = None,
    ) -> None:
        """Initialize the suggestion builder.

        :param query_parser: Parser used to validate partial expressions.
        """
        self._query_parser = query_parser or SearchQueryParser()

    def keyword_suggestions(self, search_string: str) -> Optional[List[str]]:
        """Return tag-name suggestions.

        :param search_string: Current search text.
        :return: Suggested search strings or ``None`` when unavailable.
        """
        fragment = self._last_tag_fragment(search_string)
        if fragment is None:
            return None

        prefix, tag_text = fragment
        match = self._KEYWORD_PATTERN.match(tag_text)
        if match is None:
            return None

        keyword_prefix = match.group("prefix").lower()
        suggestions = [
            f"{prefix}@{keyword}" + ("[" if keyword == "metadata" else "")
            for keyword in self.KEYWORDS
            if keyword.startswith(keyword_prefix)
        ]
        return suggestions

    def operation_suggestions(self, search_string: str) -> Optional[List[str]]:
        """Return operation suggestions for the current tag.

        :param search_string: Current search text.
        :return: Suggested search strings or ``None`` when unavailable.
        """
        fragment = self._last_tag_fragment(search_string)
        if fragment is None:
            return None

        prefix, tag_text = fragment
        match = self._OPERATION_PATTERN.match(tag_text)
        if match is None:
            return None

        tag_name = match.group("tag").lower()
        tag_syntax = self._tag_operation_syntax(tag_name)
        if tag_syntax is None:
            return None

        has_separator = match.group("separator") != ""
        operation_prefix = (match.group("operation") or "").lower()
        return [
            (
                f"{prefix}@{tag_syntax.tag_name}"
                f"{self._operation_separator(operation, has_separator)}"
                f"{self._operation_completion_text(operation, has_separator)}"
            )
            for operation in tag_syntax.operations
            if operation_prefix == ""
            or operation.name.lower().startswith(operation_prefix)
        ]

    def _operation_separator(
        self,
        operation: SearchOperation,
        has_separator: bool,
    ) -> str:
        if has_separator:
            return " "

        if operation.name == "=":
            return ""

        return " "

    def _operation_completion_text(
        self,
        operation: SearchOperation,
        has_separator: bool,
    ) -> str:
        if has_separator or operation.name != "=":
            return operation.completion_text

        return operation.completion_text.replace("= ", "=", 1)

    def _tag_operation_syntax(
        self, tag_name: str
    ) -> Optional[TagOperationSyntax]:
        for syntax in self._TAG_OPERATION_SYNTAXES:
            if syntax.tag_name == tag_name:
                return syntax

        return None

    def logical_operation_suggestions(
        self,
        search_string: str,
    ) -> Optional[List[str]]:
        """Return logical operation suggestions.

        :param search_string: Current search text.
        :return: Suggested search strings or ``None`` when unavailable.
        """
        match = self._LOGICAL_OPERATION_PATTERN.match(search_string)
        if match is None:
            return None

        expression = match.group("expression").rstrip()
        operation_prefix = match.group("operation").lower()
        parsed_search = self._query_parser.parse(expression)
        if parsed_search.is_fallback:
            return None

        return [
            f"{expression} {operation} "
            for operation in self._allowed_logical_operations(expression)
            if operation.lower().startswith(operation_prefix)
        ]

    def _allowed_logical_operations(self, expression: str) -> Tuple[str, ...]:
        has_and_operator = re.search(r"(?i)\sand\s", expression) is not None
        has_or_operator = re.search(r"(?i)\sor\s", expression) is not None

        if has_and_operator and not has_or_operator:
            return ("AND",)

        if has_or_operator and not has_and_operator:
            return ("OR",)

        if has_and_operator and has_or_operator:
            return ()

        return self.LOGICAL_OPERATIONS

    def resource_type_context(
        self,
        search_string: str,
    ) -> Optional[ResourceTypeSuggestionContext]:
        """Return resource-type completion context.

        :param search_string: Current search text.
        :return: Completion context or ``None`` when unavailable.
        """
        fragment = self._last_tag_fragment(search_string)
        if fragment is None:
            return None

        prefix, tag_text = fragment
        match = self._TYPE_PATTERN.match(tag_text)
        if match is None:
            return None

        quote = match.group("quote")
        base_text = (
            f"{prefix}@type"
            f"{match.group('before_equals')}="
            f"{match.group('after_equals')}"
            f"{quote}"
        )
        return ResourceTypeSuggestionContext(
            base_text=base_text,
            closing_quote=quote,
            value_prefix=match.group("value").lower(),
        )

    def resource_type_suggestions(
        self,
        search_string: str,
        resource_types: Iterable[str],
    ) -> Optional[List[str]]:
        """Return resource-type suggestions.

        :param search_string: Current search text.
        :param resource_types: Available resource type names.
        :return: Suggested search strings or ``None`` when unavailable.
        """
        context = self.resource_type_context(search_string)
        if context is None:
            return None

        suggestions = []
        for resource_type in resource_types:
            if not resource_type.lower().startswith(context.value_prefix):
                continue

            suggestions.append(
                f"{context.base_text}{resource_type}{context.closing_quote}"
            )

        return suggestions

    def owner_context(
        self,
        search_string: str,
    ) -> Optional[OwnerSuggestionContext]:
        """Return owner-name completion context.

        :param search_string: Current search text.
        :return: Completion context or ``None`` when unavailable.
        """
        fragment = self._last_tag_fragment(search_string)
        if fragment is None:
            return None

        prefix, tag_text = fragment
        match = self._OWNER_PATTERN.match(tag_text)
        if match is None:
            return None

        quote = match.group("quote")
        base_text = f"{prefix}@owner = {quote}"
        return OwnerSuggestionContext(
            base_text=base_text,
            closing_quote=quote,
            value_prefix=match.group("value").lower(),
        )

    def owner_suggestions(
        self,
        search_string: str,
        owners: Iterable[str],
    ) -> Optional[List[str]]:
        """Return owner-name suggestions.

        :param search_string: Current search text.
        :param owners: Available owner display names.
        :return: Suggested search strings or ``None`` when unavailable.
        """
        context = self.owner_context(search_string)
        if context is None:
            return None

        suggestions = []
        added_owners = set()
        for owner in owners:
            if not owner.lower().startswith(context.value_prefix):
                continue

            owner_key = owner.casefold()
            if owner_key in added_owners:
                continue

            if not self._can_use_quoted_value(owner, context.closing_quote):
                continue

            suggestions.append(
                f"{context.base_text}{owner}{context.closing_quote}"
            )
            added_owners.add(owner_key)

        return suggestions

    def _can_use_quoted_value(self, value: str, quote: str) -> bool:
        if quote != "":
            return quote not in value

        return '"' not in value and "'" not in value

    def _last_tag_fragment(
        self,
        search_string: str,
    ) -> Optional[Tuple[str, str]]:
        tag_start = search_string.rfind("@")
        if tag_start == -1:
            return None

        return search_string[:tag_start], search_string[tag_start:]
