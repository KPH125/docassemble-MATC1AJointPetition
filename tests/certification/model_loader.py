"""Strict loader for the finite certification model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects silently shadowed mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_model(path: Path) -> dict[str, Any]:
    """Load a certification model without permitting ambiguous YAML."""

    model = yaml.load(path.read_text(), Loader=UniqueKeyLoader)
    if not isinstance(model, dict):
        raise ValueError(f"certification model must be a mapping: {path}")
    return model
