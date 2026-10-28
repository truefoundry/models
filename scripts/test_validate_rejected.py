#!/usr/bin/env python3
"""Tests for scripts/validate_rejected.py (run with pytest or `python3 scripts/test_validate_rejected.py`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import validate_rejected as v

GOOD = """\
- id: openai/gpt-9
  reason: not-released
  who: caio
  date: 2026-10-27
  note: announced, not out
- id: openrouter/vendor/some-model
  reason: bogus
  who: caio
  date: "2026-10-20"
"""


def entry(**over):
    base = {"id": "openai/gpt-9", "reason": "bogus", "who": "caio", "date": "2026-10-27"}
    base.update(over)
    return base


def errors_of(data, providers_dir=None):
    return v.validate(data, providers_dir)[0]


class ValidateTests(unittest.TestCase):
    def test_good_entries(self):
        self.assertEqual(v.validate([entry(), entry(id="openai/gpt-10", note="x")]), ([], []))

    def test_empty_list_is_valid(self):
        self.assertEqual(v.validate([]), ([], []))

    def test_top_level_must_be_a_list(self):
        for bad in ({"rejected": []}, None, "openai/gpt-9"):
            self.assertTrue(errors_of(bad), bad)

    def test_entry_must_be_a_mapping(self):
        self.assertTrue(errors_of(["openai/gpt-9"]))

    def test_missing_required_keys(self):
        for key in ("id", "reason", "who", "date"):
            e = entry()
            del e[key]
            self.assertTrue(any(f"missing `{key}`" in x for x in errors_of([e])), key)

    def test_unknown_key(self):
        self.assertTrue(any("unknown key" in x for x in errors_of([entry(reasn="x")])))

    def test_reason_is_a_closed_set(self):
        for bad in ("Bogus", "spam", None):
            self.assertTrue(errors_of([entry(reason=bad)]), bad)
        for good in v.REASONS:
            self.assertEqual(errors_of([entry(reason=good)]), [])

    def test_a_trailing_newline_is_not_part_of_an_id_or_a_date(self):
        self.assertTrue(v.validate([entry(id="a/m\n")])[0])
        self.assertTrue(v.validate([entry(date="2026-10-27\n")])[0])
        self.assertFalse(v.validate([entry(id="a/m", date="2026-10-27")])[0])

    def test_id_shape(self):
        for bad in ("gpt-9", "openai/", "/gpt-9", "openai/gpt 9", " openai/gpt-9", "", None, 7):
            self.assertTrue(errors_of([entry(id=bad)]), bad)
        self.assertEqual(errors_of([entry(id="openrouter/a/b/c")]), [])

    def test_case_variants_are_distinct(self):
        self.assertEqual(errors_of([entry(id="a/Model"), entry(id="a/model")]), [])

    def test_who_must_be_non_blank(self):
        for bad in ("  ", 3, None):
            self.assertTrue(errors_of([entry(who=bad)]), bad)

    def test_date_must_be_a_real_day(self):
        for bad in ("2026-13-01", "2026-02-30", "27/10/2026", "2026-10-27T00:00:00", 20261027, None):
            self.assertTrue(errors_of([entry(date=bad)]), bad)

    def test_note_may_be_empty_or_a_scalar(self):
        for note in (None, "", "text", 12, 1.5, True, False):
            self.assertEqual(errors_of([entry(note=note)]), [], note)

    def test_note_cannot_be_a_list_or_mapping(self):
        for note in (["a"], {"a": 1}):
            self.assertTrue(errors_of([entry(note=note)]), note)

    def test_exact_repeat_is_a_warning(self):
        errors, warnings = v.validate([entry(), entry(note="again")])
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_same_id_different_reason_is_an_error(self):
        self.assertTrue(any("different reason" in x for x in errors_of([entry(reason="bogus"), entry(reason="promo")])))
        self.assertTrue(
            any("different reason" in x for x in errors_of([entry(reason="bogus"), entry(reason="bogus"), entry(reason="promo")]))
        )

    def test_unknown_provider_folder_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "openai").mkdir()
            errors, warnings = v.validate([entry(), entry(id="opnai/gpt-9")], Path(d))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("providers/opnai/", warnings[0])


class FileTests(unittest.TestCase):
    def _check(self, text: str | bytes | None):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rejected.yaml"
            if isinstance(text, bytes):
                path.write_bytes(text)
            elif text is not None:
                path.write_text(text)
            return v.check_file(path)

    def test_good_file(self):
        self.assertEqual(self._check(GOOD), ([], []))

    def test_explicit_empty_list(self):
        self.assertEqual(self._check("[]\n"), ([], []))

    def test_empty_file_is_an_error(self):
        for text in ("", "\n", "# only a comment\n"):
            self.assertTrue(self._check(text)[0], text)

    def test_a_timestamp_is_not_a_day(self):
        # YAML parses `2026-10-27 10:00:00` to a datetime, which is a date subclass.
        text = "- {id: a/m, reason: bogus, who: c, date: 2026-10-27 10:00:00}\n"
        self.assertTrue(any("`date`" in x for x in self._check(text)[0]))

    def test_invalid_yaml(self):
        self.assertTrue(any("not valid YAML" in x for x in self._check("- id: [oops\n")[0]))

    def test_an_unquoted_impossible_date_is_an_error_not_a_crash(self):
        text = "- {id: a/m, reason: bogus, who: c, date: 2026-13-45}\n"
        errors = self._check(text)[0]
        self.assertTrue(any("not valid YAML" in x for x in errors), errors)

    def test_missing_file(self):
        self.assertTrue(any("cannot be read" in x for x in self._check(None)[0]))

    def test_undecodable_file(self):
        self.assertTrue(self._check(b"\xff\xfe\x00bad")[0])


class MainTests(unittest.TestCase):
    def _run(self, text: str | None, extra=()):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rejected.yaml"
            if text is not None:
                path.write_text(text)
            return v.main(["validate_rejected.py", str(path), *extra])

    def test_exit_codes(self):
        self.assertEqual(self._run(GOOD), 0)
        self.assertEqual(self._run("- id: x\n"), 1)
        self.assertEqual(self._run(None), 1)
        self.assertEqual(self._run(GOOD, extra=("extra",)), 2)

    def test_the_committed_file_is_valid(self):
        self.assertEqual(v.main(["validate_rejected.py"]), 0)


if __name__ == "__main__":
    unittest.main()
