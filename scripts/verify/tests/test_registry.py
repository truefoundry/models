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


def test_an_unquoted_impossible_date_is_a_registry_error_not_a_crash(tmp_path):
    bad = tmp_path / "r.yaml"
    bad.write_text("version: 1\nsources:\n  - {provider: p, kind: api, source: s, fields: [price], added: 2026-13-45}\n")
    with pytest.raises(RegistryError, match="not valid YAML"):
        registry.load(bad)


@pytest.mark.parametrize("field,value", [("provider", "p\n"), ("source", "fake\n"), ("provider", "p\n\n")])
def test_a_trailing_newline_is_not_a_valid_name(field, value):
    with pytest.raises(RegistryError):
        registry.parse(with_row(**{field: value}))


def _header_list(text, key):
    line = next(x for x in text.splitlines() if x.startswith(f"# {key}:"))
    return {x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()}


def test_the_header_contract_lists_every_price_source_and_keeps_openrouter_out_of_price_ownership():
    """The sweep / agent (models-agent repo) read `price` in `fields` as 'price-owned'. This file
    cannot import the sweep, so the contract is the header: every source with `price` is named as
    either SAFE-TO-WRITE or REPORT-ONLY, and openrouter never carries `price`."""
    path = REPO / "sources" / "registry.yaml"
    text = path.read_text()
    safe, report_only = _header_list(text, "SAFE-TO-WRITE"), _header_list(text, "REPORT-ONLY")
    owned_header = _header_list(text, "PRICE-OWNED")
    assert not (safe & report_only) and safe == {"deepinfra", "aws-price-list", "anthropic-pricing-page"}
    assert owned_header == {"deepinfra", "aws-price-list"} and owned_header <= safe     # owned only what the sweep writes
    reg = registry.load(path, REPO / "providers")
    priced = {e.source for e in reg.entries if "price" in e.fields}
    assert priced == owned_header and priced <= safe and "openrouter" not in priced and "anthropic-pricing-page" not in priced
    assert [e.fields for e in reg.for_provider("openrouter")] == [("limits",)]
    azure = [e for e in reg.entries if e.source == "azure-retail-prices"]
    assert {e.provider for e in azure} == {"azure-open-ai", "azure-ai-foundry", "microsoft-foundry"}
    assert all(e.fields == ("price-report",) for e in azure)          # report-only: never price-owned
    assert "azure-retail-prices" not in priced
    assert [(e.source, e.fields) for e in reg.for_provider("anthropic")] == [("anthropic-pricing-page", ("price-report",))]
    assert all(e.added >= "2026-10-27" for e in reg.entries)


def test_a_provider_has_at_most_one_price_source():
    reg = registry.load(REPO / "sources" / "registry.yaml", REPO / "providers")
    for provider in {e.provider for e in reg.entries}:
        price_sources = [e.source for e in reg.for_provider(provider) if "price" in e.fields]
        assert len(price_sources) <= 1, provider


def test_price_report_is_a_valid_field_and_is_not_price():
    row = with_row(fields=["price-report"])
    assert registry.parse(row).entries[0].fields == ("price-report",)
    assert "price" not in registry.parse(row).entries[0].fields and "price-report" in registry.FIELDS
    with pytest.raises(RegistryError):
        registry.parse(with_row(fields=["price-reports"]))


def test_the_sweeps_and_the_agents_price_owned_rule_ignores_price_report():
    """Both read `"price" in fields` on the raw list (sweep/verifier.py load_registry,
    updation/job/ownership.py load_price_owned): re-implemented here as a contract check."""
    data = yaml.safe_load((REPO / "sources" / "registry.yaml").read_text())
    owned = {row["provider"] for row in data["sources"] if isinstance(row.get("fields"), list) and "price" in row["fields"]}
    assert owned == {"deepinfra", "aws-bedrock"}
    assert not owned & {"openrouter", "anthropic", "azure-open-ai", "azure-ai-foundry", "microsoft-foundry"}


def test_propose_apply_sources_are_exactly_the_price_owned_sources_of_the_header():
    """verify.propose.APPLY_SOURCES (what the addition job may WRITE) must be the registry header's
    PRICE-OWNED set, and every one of them SAFE-TO-WRITE: change one without the other and this fails."""
    from verify import propose
    text = (REPO / "sources" / "registry.yaml").read_text()
    owned, safe = _header_list(text, "PRICE-OWNED"), _header_list(text, "SAFE-TO-WRITE")
    assert set(propose.APPLY_SOURCES) == owned and owned <= safe
    reg = registry.load(REPO / "sources" / "registry.yaml", REPO / "providers")
    assert {e.source for e in reg.entries if "price" in e.fields} == set(propose.APPLY_SOURCES)
    assert "openrouter" not in propose.APPLY_SOURCES and "anthropic-pricing-page" not in propose.APPLY_SOURCES
