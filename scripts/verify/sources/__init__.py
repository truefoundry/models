"""Official-source adapters. `SOURCES` maps a source name to a zero-argument factory; the core
builds each lazily, calls `covers(provider)` and then `prepare()` once and `check()` per file."""
from __future__ import annotations

from typing import Callable

from ..types import Source
from .aws_price_list import AwsPriceListSource
from .deepinfra import DeepInfraSource
from .openrouter import OpenRouterSource

SOURCES: dict[str, Callable[[], Source]] = {
    "openrouter": OpenRouterSource,
    "deepinfra": DeepInfraSource,
    "aws-price-list": AwsPriceListSource,
}
