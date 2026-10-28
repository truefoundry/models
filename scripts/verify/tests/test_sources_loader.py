import sys

from verify import sources


def test_no_adapters_means_empty_list(monkeypatch):
    monkeypatch.setattr(sources, "SOURCES", {})
    assert sources.load_sources() == [] and sources.load_sources(["x"]) == []


def test_registered_adapters_are_instantiated_and_filtered(monkeypatch):
    class A:
        name = "a"

    class B:
        name = "b"
    monkeypatch.setattr(sources, "SOURCES", {"a": A, "b": B})
    assert [s.name for s in sources.load_sources()] == ["a", "b"]
    assert [s.name for s in sources.load_sources(["b", "zzz"])] == ["b"]


def test_failing_factory_is_skipped_and_recorded(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(sources, "SOURCES", {"a": boom})
    monkeypatch.setattr(sources, "IMPORT_ERRORS", {})
    assert sources.load_sources() == [] and "RuntimeError" in sources.IMPORT_ERRORS["verify.sources.a"]


def test_adapter_modules_register_themselves_and_a_broken_one_does_not_stop_the_rest(tmp_path, monkeypatch):
    (tmp_path / "good.py").write_text("from . import SOURCES\nclass G:\n    name = 'good'\nSOURCES['good'] = G\n")
    (tmp_path / "bad.py").write_text("raise ImportError('x')\n")
    (tmp_path / "_private.py").write_text("raise RuntimeError('never imported')\n")
    monkeypatch.setattr(sources, "__path__", [*sources.__path__, str(tmp_path)])
    monkeypatch.setattr(sources, "SOURCES", dict(sources.SOURCES))
    monkeypatch.setattr(sources, "IMPORT_ERRORS", {})
    got = sources.load_sources(["good"])
    assert [s.name for s in got] == ["good"]
    assert "verify.sources.bad" in sources.IMPORT_ERRORS and "verify.sources._private" not in sources.IMPORT_ERRORS
    for m in ("good", "bad"):
        sys.modules.pop(f"verify.sources.{m}", None)
