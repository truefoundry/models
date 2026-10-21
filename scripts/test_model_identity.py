#!/usr/bin/env python3
"""Unit tests for canonical model identity and Artificial Analysis matching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import model_identity_lib as lib


class ProposeCanonicalTests(unittest.TestCase):
    def test_provider_alias_and_regional_suffix(self):
        cases = [
            ("anthropic", "claude-opus-4-6-20251201", "anthropic/claude-opus-4-6"),
            ("aws-bedrock", "us.anthropic.claude-opus-4-6-v1:0", "anthropic/claude-opus-4-6"),
            ("google-vertex", "anthropic/claude-opus-4-6@20251201", "anthropic/claude-opus-4-6"),
            ("openai", "gpt-4.1-mini-2025-04-14", "openai/gpt-4-1-mini"),
            ("aws-bedrock", "eu.anthropic.claude-sonnet-5", "anthropic/claude-sonnet-5"),
            ("openrouter", "claude-3.7-sonnet:thinking", "anthropic/claude-3-7-sonnet-thinking"),
            ("openrouter", "mistral-nemo:free", "mistral/mistral-nemo"),
            ("together-ai", "nim/meta/llama-3.1-70b-instruct", "meta/llama-3-1-70b-instruct"),
        ]
        for provider, model_id, expected in cases:
            with self.subTest(model_id=model_id):
                got = lib.propose_canonical(provider, model_id).proposed_canonical
                self.assertEqual(got, expected)
                self.assertTrue(lib.is_valid_canonical(got))

    def test_distinct_releases_and_reasoning_efforts(self):
        a = lib.propose_canonical("openai", "o4-mini").proposed_canonical
        b = lib.propose_canonical("openai", "o4-mini-high").proposed_canonical
        self.assertNotEqual(a, b)
        self.assertEqual(a, "openai/o4-mini")
        self.assertEqual(b, "openai/o4-mini-high")

        dated = lib.propose_canonical("anthropic", "claude-3-5-sonnet-20240620").proposed_canonical
        later = lib.propose_canonical("anthropic", "claude-3-5-sonnet-20241022").proposed_canonical
        # Dates collapse to the same foundation name once reviewed as identical weights family.
        self.assertEqual(dated, later)
        self.assertEqual(dated, "anthropic/claude-3-5-sonnet")


class ArtificialAnalysisMatchTests(unittest.TestCase):
    def setUp(self):
        self.aa_models = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "slug": "claude-opus-4-6",
                "name": "Claude Opus 4.6 (Non-reasoning, High)",
                "release_date": "2025-12-01",
                "model_creator": {"name": "Anthropic"},
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "slug": "claude-opus-4-6-adaptive",
                "name": "Claude Opus 4.6 (Max)",
                "release_date": "2025-12-01",
                "model_creator": {"name": "Anthropic"},
            },
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "slug": "gpt-4-1-mini",
                "name": "GPT-4.1 mini",
                "release_date": "2025-04-14",
                "model_creator": {"name": "OpenAI"},
            },
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "slug": "qwen3-14b-instruct",
                "name": "Qwen3 14B Instruct",
                "release_date": "2025-01-01",
                "model_creator": {"name": "Alibaba"},
            },
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "slug": "qwen3-14b-instruct-reasoning",
                "name": "Qwen3 14B Instruct Reasoning",
                "release_date": "2025-01-01",
                "model_creator": {"name": "Alibaba"},
            },
        ]

    def test_exact_slug_match(self):
        status, ids, _ = lib.match_aa_for_canonical(
            "anthropic/claude-opus-4-6", self.aa_models, {}
        )
        self.assertEqual(status, "matched")
        self.assertEqual(ids["artificial_analysis_slug"], "claude-opus-4-6")
        self.assertEqual(ids["artificial_analysis_id"], "11111111-1111-1111-1111-111111111111")

    def test_creator_mismatch(self):
        status, ids, _ = lib.match_aa_for_canonical(
            "openai/claude-opus-4-6", self.aa_models, {}
        )
        self.assertEqual(status, "unmatched")
        self.assertIsNone(ids)

    def test_ambiguous_matches_not_auto_resolved(self):
        # Two Alibaba rows; foundation equals neither slug exactly and name is not unique.
        status, ids, cands = lib.match_aa_for_canonical(
            "alibaba/qwen3-14b", self.aa_models, {}
        )
        self.assertEqual(status, "unmatched")
        self.assertIsNone(ids)
        self.assertEqual(cands, [])

        # If slug itself is ambiguous (duplicate slugs), report ambiguous.
        dup = list(self.aa_models) + [
            {
                "id": "66666666-6666-6666-6666-666666666666",
                "slug": "claude-opus-4-6",
                "name": "Claude Opus 4.6 Duplicate",
                "release_date": "2025-12-01",
                "model_creator": {"name": "Anthropic"},
            }
        ]
        status, ids, cands = lib.match_aa_for_canonical(
            "anthropic/claude-opus-4-6", dup, {}
        )
        self.assertEqual(status, "ambiguous")
        self.assertIsNone(ids)
        self.assertEqual(len(cands), 2)

    def test_reviewed_mapping_wins(self):
        reviewed = {
            "anthropic/claude-opus-4-6": {
                "artificial_analysis_slug": "claude-opus-4-6-adaptive",
                "artificial_analysis_id": "22222222-2222-2222-2222-222222222222",
            }
        }
        status, ids, _ = lib.match_aa_for_canonical(
            "anthropic/claude-opus-4-6", self.aa_models, reviewed
        )
        self.assertEqual(status, "reviewed")
        self.assertEqual(ids["artificial_analysis_slug"], "claude-opus-4-6-adaptive")

    def test_api_failure_safety(self):
        import urllib.error

        class FakeOpener:
            def open(self, req):  # noqa: ANN001, ARG002
                raise urllib.error.HTTPError(
                    url="https://artificialanalysis.ai/api/v2/language/models/free?page=1",
                    code=500,
                    msg="err",
                    hdrs=None,
                    fp=None,
                )

        with self.assertRaises(RuntimeError):
            lib.fetch_aa_language_models(api_key="test-key", opener=FakeOpener())


class ApplyIdempotencyTests(unittest.TestCase):
    def test_apply_canonical_and_external_ids_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            providers = root / "providers" / "anthropic"
            providers.mkdir(parents=True)
            model_path = providers / "claude-test.yaml"
            model_path.write_text(
                "mode: chat\nmodel: claude-test\nlimits:\n    max_tokens: 1\n",
                encoding="utf-8",
            )
            aliases = root / "canonical_aliases.yaml"
            aliases.write_text(
                "aliases:\n  claude-test: anthropic/claude-test\n",
                encoding="utf-8",
            )
            external = root / "canonical_external_ids.yaml"
            external.write_text(
                "external_ids:\n  anthropic/claude-test:\n"
                "    artificial_analysis_id: 11111111-1111-1111-1111-111111111111\n"
                "    artificial_analysis_slug: claude-test\n",
                encoding="utf-8",
            )

            with mock.patch.object(lib, "REPO_ROOT", root), mock.patch.object(
                lib, "PROVIDERS_DIR", root / "providers"
            ), mock.patch.object(lib, "ALIASES_PATH", aliases), mock.patch.object(
                lib, "EXTERNAL_IDS_PATH", external
            ), mock.patch.object(lib, "EXCEPTIONS_PATH", root / "canonical_exceptions.yaml"):
                first = lib.update_model_yaml_fields(
                    model_path, canonical_model="anthropic/claude-test"
                )
                second = lib.update_model_yaml_fields(
                    model_path, canonical_model="anthropic/claude-test"
                )
                self.assertTrue(first)
                self.assertFalse(second)

                ids = {
                    "artificial_analysis_id": "11111111-1111-1111-1111-111111111111",
                    "artificial_analysis_slug": "claude-test",
                }
                third = lib.update_model_yaml_fields(model_path, external_ids=ids)
                fourth = lib.update_model_yaml_fields(model_path, external_ids=ids)
                self.assertTrue(third)
                self.assertFalse(fourth)


if __name__ == "__main__":
    unittest.main()
