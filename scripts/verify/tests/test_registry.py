from pathlib import Path

import pytest
import yaml

from verify import registry
from verify.registry import RegistryError

REPO = Path(__file__).resolve().parents[3]
GOOD = {"version": 1, "sources": [{"provider": "p", "kind": "api", "source": "fake", "fields": ["price"], "added": "2026-10-27"}]}


def with_row(**kw):
    row = dict(GOOD["sources"][0], **kw)
    return {"version": 1, "sources": [row]}


def test_real_registry_is_valid_and_lists_the_starter_providers():
    reg = registry.load(REPO / "sources" / "registry.yaml", REPO / "providers")
    got = {(e.provider, e.source) for e in reg.entries}
    assert {("openrouter", "openrouter"), ("deepinfra", "deepinfra"), ("aws-bedrock", "aws-price-list")} <= got
    assert [e.source for e in reg.for_provider("aws-bedrock")] == ["aws-price-list"]
    assert reg.for_provider("nobody") == []


def test_parse_good():
    reg = registry.parse(GOOD)
    assert reg.entries[0].fields == ("price",) and reg.entries[0].added == "2026-10-27"
    assert reg.source_names() == {"fake"} and reg.source_names({"zzz"}) == set()


def test_yaml_date_is_accepted():
    data = yaml.safe_load("version: 1\nsources:\n  - {provider: p, kind: page, source: s, fields: [limits], added: 2026-10-27}\n")
    assert registry.parse(data).entries[0].added == "2026-10-27"


@pytest.mark.parametrize("bad", [
    {"kind": "rss"}, {"provider": "Bad Name"}, {"provider": "../x"}, {"source": "Has Space"}, {"fields": []},
    {"fields": ["price", "price"]}, {"fields": ["vibes"]}, {"fields": "price"}, {"added": "yesterday"}, {"added": 20261027},
    {"extra": 1},
])
def test_rejects_bad_rows(bad):
    with pytest.raises(RegistryError):
        registry.parse(with_row(**bad))


@pytest.mark.parametrize("data", [None, [], {"sources": "x"}, {"version": 2, "sources": []}, {"sources": [], "oops": 1}, {"sources": ["x"]}])
def test_rejects_bad_documents(data):
    with pytest.raises(RegistryError):
        registry.parse(data)


def test_missing_key_and_duplicates():
    row = dict(GOOD["sources"][0])
    del row["added"]
    with pytest.raises(RegistryError, match="missing `added`"):
        registry.parse({"sources": [row]})
    with pytest.raises(RegistryError, match="duplicate"):
        registry.parse({"sources": [GOOD["sources"][0], GOOD["sources"][0]]})


def test_provider_directory_must_exist(tmp_path):
    (tmp_path / "p").mkdir()
    registry.parse(GOOD, tmp_path)
    with pytest.raises(RegistryError, match="does not exist"):
        registry.parse(with_row(provider="nope"), tmp_path)


def test_load_errors(tmp_path):
    with pytest.raises(RegistryError):
        registry.load(tmp_path / "missing.yaml")
    bad = tmp_path / "r.yaml"
    bad.write_text("a: [\n")
    with pytest.raises(RegistryError):
        registry.load(bad)
