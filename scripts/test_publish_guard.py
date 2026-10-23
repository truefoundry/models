#!/usr/bin/env python3
"""Unit tests for the publish guard (scripts/publish_guard.py).

Run from the repo root with:
    python3 scripts/test_publish_guard.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import publish_guard as pg


def entry(provider="openai", model="m1", region="*", **rates) -> dict:
    """A built ai-models.json entry with one cost entry."""
    return {"provider": provider, "model": model, "costs": [{"region": region, **rates}]}


def rules(findings) -> list[str]:
    return sorted(f.rule for f in findings)


class FlattenCostsTests(unittest.TestCase):
    def test_flat_rates_are_keyed_by_region(self):
        costs = [{"region": "*", "input_cost_per_token": 1e-6}, {"region": "eu", "input_cost_per_token": 2e-6}]

        self.assertEqual(pg.flatten_costs(costs), {"*|input_cost_per_token": 1e-6, "eu|input_cost_per_token": 2e-6})

    def test_nested_blocks_and_tiers_are_flattened_with_tiers_keyed_by_threshold(self):
        costs = [{
            "region": "*", "input_cost_per_token": 1e-6,
            "priority_pricing": {"input_cost_per_token": 2e-6},
            "tiered_pricing": {"input": [{"from": 272000, "cost_per_token": 4e-6}, {"from": 1000000, "cost_per_token": 8e-6}],
                               "pricing_mode": "cumulative"},
        }]

        flat = pg.flatten_costs(costs)

        self.assertEqual(flat["*|priority_pricing.input_cost_per_token"], 2e-6)
        self.assertEqual(flat["*|tiered_pricing.input@272000.cost_per_token"], 4e-6)
        self.assertEqual(flat["*|tiered_pricing.input@1000000.cost_per_token"], 8e-6)
        self.assertNotIn("*|tiered_pricing.pricing_mode", flat)  # strings are not rates

    def test_bools_strings_and_junk_are_ignored(self):
        self.assertEqual(pg.flatten_costs([{"region": "*", "a": True, "b": "x", "c": None}, "junk", 3]), {})
        self.assertEqual(pg.flatten_costs("not a list"), {})

    def test_inserting_a_tier_does_not_shift_the_others(self):
        before = pg.flatten_costs([{"region": "*", "tiered_pricing": {"input": [{"from": 200000, "cost_per_token": 4e-6}]}}])
        after = pg.flatten_costs([{"region": "*", "tiered_pricing": {"input": [
            {"from": 100000, "cost_per_token": 3e-6}, {"from": 200000, "cost_per_token": 4e-6}]}}])

        self.assertEqual(before["*|tiered_pricing.input@200000.cost_per_token"], after["*|tiered_pricing.input@200000.cost_per_token"])


class StructureTests(unittest.TestCase):
    def test_a_valid_file_has_no_findings(self):
        self.assertEqual(pg.check_structure([entry(input_cost_per_token=1e-6)]), [])

    def test_not_a_list_or_empty_is_malformed(self):
        for bad in (None, {}, [], "x", 7):
            self.assertEqual(rules(pg.check_structure(bad)), ["malformed"], repr(bad))

    def test_entries_without_provider_model_or_costs_are_malformed(self):
        bad = [{"model": "m"}, {"provider": "p"}, {"provider": "p", "model": "m"}, {"provider": "p", "model": "m", "costs": []},
               {"provider": "", "model": "m", "costs": [{}]}, "junk"]

        self.assertEqual(len(pg.check_structure(bad)), len(bad))


class UnitSlipTests(unittest.TestCase):
    def test_a_per_million_rate_written_as_per_token_is_caught(self):
        findings = pg.check_unit_slips([entry(input_cost_per_token=5.0)])

        self.assertEqual(rules(findings), ["unit_slip"])
        self.assertIn("input_cost_per_token", findings[0].detail)

    def test_the_limit_is_a_tenth_of_a_dollar_per_token(self):
        # Literal numbers on purpose: a test that reads the constant moves with it.
        self.assertEqual(rules(pg.check_unit_slips([entry(input_cost_per_token=0.1)])), ["unit_slip"])
        self.assertEqual(rules(pg.check_unit_slips([entry(input_cost_per_token=0.5)])), ["unit_slip"])
        self.assertEqual(pg.check_unit_slips([entry(input_cost_per_token=0.099)]), [])
        self.assertEqual(pg.check_unit_slips([entry(input_cost_per_token=0.05)]), [])

    def test_the_highest_real_rate_in_the_catalog_passes(self):
        self.assertEqual(pg.check_unit_slips([entry(output_cost_per_token=0.00971)]), [])

    def test_the_limit_is_inclusive(self):
        self.assertEqual(rules(pg.check_unit_slips([entry(input_cost_per_token=pg.UNIT_SLIP_RATE)])), ["unit_slip"])

    def test_non_token_rates_may_be_large(self):
        self.assertEqual(pg.check_unit_slips([entry(input_cost_per_request=2.5, output_cost_per_image=4.0, input_cost_per_second=1.2)]), [])

    def test_tier_and_nested_token_rates_are_checked_too(self):
        tiered = {"provider": "p", "model": "m", "costs": [{"region": "*", "input_cost_per_token": 1e-6, "tiered_pricing": {
            "input": [{"from": 1000, "cost_per_token": 3.0}]}}]}
        nested = entry(input_cost_per_token=1e-6, priority_pricing={"output_cost_per_token": 9.0})

        self.assertEqual(rules(pg.check_unit_slips([tiered, nested])), ["unit_slip", "unit_slip"])


class PriceTests(unittest.TestCase):
    def jumps(self, old, new):
        return rules(pg.check_prices([entry(input_cost_per_token=old)], [entry(input_cost_per_token=new)]))

    def test_an_unchanged_price_passes(self):
        self.assertEqual(self.jumps(1e-6, 1e-6), [])

    def test_a_change_within_three_times_passes_either_way(self):
        self.assertEqual(self.jumps(1e-6, 2.9e-6), [])
        self.assertEqual(self.jumps(2.9e-6, 1e-6), [])

    def test_exactly_three_times_passes(self):
        self.assertEqual(self.jumps(1e-6, 3e-6), [])

    def test_between_three_and_ten_times_is_a_warning_either_way(self):
        for old, new in ((1e-6, 3.1e-6), (3.1e-6, 1e-6), (1e-6, 9e-6), (9e-6, 1e-6)):
            findings = pg.check_prices([entry(input_cost_per_token=old)], [entry(input_cost_per_token=new)])

            self.assertEqual(rules(findings), ["price_change"], (old, new))
            self.assertFalse(findings[0].blocking)

    def test_ten_times_or_more_blocks_either_way(self):
        for old, new in ((1e-6, 2e-5), (2e-5, 1e-6), (5e-6, 5e-5), (1e-6, 1e-4)):
            findings = pg.check_prices([entry(input_cost_per_token=old)], [entry(input_cost_per_token=new)])

            self.assertEqual(rules(findings), ["price_jump"], (old, new))
            self.assertTrue(findings[0].blocking)

    def test_a_decimal_ten_times_blocks_whatever_the_float_noise(self):
        # 4e-6 / 4e-7 and similar pairs are not exactly 10.0 in floating point.
        for old, new in ((4e-6, 4e-7), (1e-6, 1e-7), (3e-6, 3e-7), (1.4e-7, 1.4e-8), (1e-5, 1e-6), (2e-8, 2e-9),
                         # float division gives 9.999999999999998 for these decimal 10x pairs
                         (1.3e-6, 1.3e-5), (1.4e-7, 1.4e-6), (1.5e-5, 1.5e-4), (2.1e-9, 2.1e-8)):
            self.assertEqual(self.jumps(old, new), ["price_jump"], (old, new))
        self.assertLess(max(1.3e-6 / 1.3e-5, 1.3e-5 / 1.3e-6), 10)  # the noise this test guards against is real

    def test_a_decimal_three_times_is_still_not_a_warning(self):
        for old, new in ((1e-6, 3e-6), (3e-6, 1e-6), (1.1e-7, 3.3e-7),
                         # float division gives 3.0000000000000004 for these decimal 3x pairs
                         (1.1e-5, 3.3e-5), (1.4e-9, 4.2e-9), (1.7e-9, 5.1e-9)):
            self.assertEqual(self.jumps(old, new), [], (old, new))
        self.assertGreater(3.3e-5 / 1.1e-5, 3)  # the noise this test guards against is real

    def test_the_block_limit_is_inclusive_and_just_under_it_is_a_warning(self):
        self.assertEqual(self.jumps(1.0, 10.0), ["price_jump"])
        self.assertEqual(self.jumps(1.0, 9.99), ["price_change"])

    def test_a_priced_rate_going_to_zero_is_its_own_rule(self):
        findings = pg.check_prices([entry(input_cost_per_token=1e-6)], [entry(input_cost_per_token=0)])

        self.assertEqual(rules(findings), ["price_to_zero"])
        self.assertTrue(findings[0].blocking)

    def test_free_to_priced_is_a_new_price_not_a_jump(self):
        self.assertEqual(self.jumps(0, 5e-6), [])

    def test_a_new_model_has_no_baseline(self):
        self.assertEqual(pg.check_prices([entry(model="a", input_cost_per_token=1e-6)], [entry(model="b", input_cost_per_token=9e-6)]), [])

    def test_regions_are_compared_with_their_own_region(self):
        live = [{"provider": "p", "model": "m", "costs": [{"region": "us", "input_cost_per_token": 1e-6}, {"region": "eu", "input_cost_per_token": 5e-6}]}]
        new = [{"provider": "p", "model": "m", "costs": [{"region": "us", "input_cost_per_token": 5e-5}, {"region": "eu", "input_cost_per_token": 5e-6}]}]

        findings = pg.check_prices(live, new)

        self.assertEqual(rules(findings), ["price_jump"])
        self.assertIn("us|input_cost_per_token", findings[0].detail)

    def test_a_tier_rate_is_checked_at_its_own_threshold(self):
        def with_tier(rate):
            return {"provider": "p", "model": "m", "costs": [{"region": "*", "input_cost_per_token": 1e-6, "tiered_pricing": {
                "input": [{"from": 272000, "cost_per_token": rate}]}}]}

        findings = pg.check_prices([with_tier(4e-6)], [with_tier(8e-5)])

        self.assertEqual(rules(findings), ["price_jump"])
        self.assertIn("tiered_pricing.input@272000", findings[0].detail)

    def test_a_new_tier_or_a_new_nested_block_is_not_a_jump(self):
        live = [entry(input_cost_per_token=1e-6)]
        new = [entry(input_cost_per_token=1e-6, priority_pricing={"input_cost_per_token": 9e-6})]

        self.assertEqual(pg.check_prices(live, new), [])

    def test_duplicate_model_entries_pass_when_each_new_price_is_near_an_old_one(self):
        live = [entry(model="imagen", input_cost_per_token=1e-6), entry(model="imagen", input_cost_per_token=9e-6)]
        new = [entry(model="imagen", input_cost_per_token=9e-6), entry(model="imagen", input_cost_per_token=1e-6)]

        self.assertEqual(pg.check_prices(live, new), [])

    def test_a_duplicate_with_a_price_near_none_of_the_old_ones_is_caught(self):
        live = [entry(model="imagen", input_cost_per_token=1e-6), entry(model="imagen", input_cost_per_token=9e-6)]
        new = [entry(model="imagen", input_cost_per_token=1e-6), entry(model="imagen", input_cost_per_token=1e-4)]

        self.assertEqual(rules(pg.check_prices(live, new)), ["price_jump"])

    def test_losing_an_input_or_output_rate_is_caught(self):
        live = [entry(input_cost_per_token=1e-6, output_cost_per_token=2e-6)]
        new = [entry(input_cost_per_token=1e-6)]

        findings = pg.check_prices(live, new)

        self.assertEqual(rules(findings), ["field_dropped"])
        self.assertIn("output_cost_per_token", findings[0].detail)

    def test_a_whole_region_being_removed_is_not_a_dropped_rate(self):
        live = [{"provider": "p", "model": "m", "costs": [
            {"region": "us", "input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6},
            {"region": "asia", "input_cost_per_token": 1.1e-6, "output_cost_per_token": 2.2e-6}]}]
        new = [{"provider": "p", "model": "m", "costs": [{"region": "us", "input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}]}]

        self.assertEqual(pg.check_prices(live, new), [])

    def test_a_rate_replaced_by_another_unit_is_not_a_loss(self):
        live = [entry(input_cost_per_token=1e-6, output_cost_per_token=1e-5)]
        new = [entry(input_cost_per_token=1e-6, output_cost_per_image_token=1e-5)]

        self.assertEqual(pg.check_prices(live, new), [])

    def test_losing_a_minor_field_is_not_a_finding(self):
        live = [entry(input_cost_per_token=1e-6, cache_read_input_token_cost=1e-7)]
        new = [entry(input_cost_per_token=1e-6)]

        self.assertEqual(pg.check_prices(live, new), [])


class RemovalTests(unittest.TestCase):
    @staticmethod
    def catalog(**counts) -> list[dict]:
        return [entry(provider=p, model=f"m{i}", input_cost_per_token=1e-6) for p, n in counts.items() for i in range(n)]

    def test_a_provider_losing_three_models_and_a_fifth_of_its_catalog_is_caught(self):
        live = self.catalog(small=10, big=200)
        new = [e for e in live if not (e["provider"] == "small" and e["model"] in ("m0", "m1", "m2"))]

        findings = pg.check_removals(live, new)

        self.assertEqual(rules(findings), ["removed"])
        self.assertEqual(findings[0].where, "small")

    def test_two_removals_are_below_the_minimum_even_at_twenty_percent(self):
        live = self.catalog(small=10, big=200)
        new = [e for e in live if not (e["provider"] == "small" and e["model"] in ("m0", "m1"))]

        self.assertEqual(pg.check_removals(live, new), [])

    def test_three_removals_from_a_big_provider_are_fine(self):
        live = self.catalog(big=200)
        new = [e for e in live if e["model"] not in ("m0", "m1", "m2")]

        self.assertEqual(pg.check_removals(live, new), [])

    def test_five_percent_of_the_catalog_is_caught_even_when_no_provider_crosses_its_own_limit(self):
        live = self.catalog(a=40, b=40, c=40, d=40, e=40)  # 200 models
        gone = {("a", "m0"), ("a", "m1"), ("b", "m0"), ("b", "m1"), ("c", "m0"), ("c", "m1"), ("d", "m0"), ("d", "m1"), ("e", "m0"), ("e", "m1")}
        new = [e for e in live if (e["provider"], e["model"]) not in gone]  # 10 of 200 = 5%

        findings = pg.check_removals(live, new)

        self.assertEqual([f.where for f in findings], ["catalog"])

    def test_just_under_five_percent_passes(self):
        live = self.catalog(a=50, b=50, c=50, d=50)  # 200
        gone = {("a", f"m{i}") for i in range(2)} | {("b", f"m{i}") for i in range(2)} | {("c", f"m{i}") for i in range(2)} | {("d", f"m{i}") for i in range(3)}
        new = [e for e in live if (e["provider"], e["model"]) not in gone]  # 9 of 200 = 4.5%

        self.assertEqual(pg.check_removals(live, new), [])

    def test_a_model_listed_twice_counts_once_and_added_models_do_not_offset_removals(self):
        live = self.catalog(p=10, big=300) + [entry(provider="p", model="m0", input_cost_per_token=2e-6)]
        new = [e for e in live if not (e["provider"] == "p" and e["model"] in ("m0", "m1", "m2"))] + self.catalog(q=30)

        findings = pg.check_removals(live, new)

        self.assertEqual([f.where for f in findings], ["p"])
        self.assertIn("3 of 10", findings[0].detail)


class DroppedBlockTests(unittest.TestCase):
    @staticmethod
    def pair(n_losing: int, block="priority_pricing"):
        live = [entry(model=f"m{i}", input_cost_per_token=1e-6, **{block: {"input_cost_per_token": 2e-6}}) for i in range(10)]
        new = [entry(model=f"m{i}", input_cost_per_token=1e-6, **({} if i < n_losing else {block: {"input_cost_per_token": 2e-6}})) for i in range(10)]
        return live, new

    def test_five_models_losing_the_same_block_is_caught(self):
        findings = pg.check_dropped_blocks(*self.pair(5))

        self.assertEqual(rules(findings), ["block_dropped"])
        self.assertEqual(findings[0].where, "priority_pricing")

    def test_four_is_below_the_limit(self):
        self.assertEqual(pg.check_dropped_blocks(*self.pair(4)), [])

    def test_tiers_flex_and_ultrafast_are_covered_too(self):
        for block in ("flex_pricing", "ultrafast_pricing"):
            self.assertEqual(rules(pg.check_dropped_blocks(*self.pair(6, block))), ["block_dropped"], block)
        live = [entry(model=f"m{i}", input_cost_per_token=1e-6) for i in range(6)]
        for e in live:
            e["costs"][0]["tiered_pricing"] = {"input": [{"from": 1000, "cost_per_token": 2e-6}]}
        new = [entry(model=f"m{i}", input_cost_per_token=1e-6) for i in range(6)]

        self.assertEqual(rules(pg.check_dropped_blocks(live, new)), ["block_dropped"])

    def test_a_model_that_keeps_the_block_does_not_count(self):
        live, new = self.pair(0)

        self.assertEqual(pg.check_dropped_blocks(live, new), [])


class CompareTests(unittest.TestCase):
    def test_identical_files_have_no_findings(self):
        data = [entry(input_cost_per_token=1e-6)]

        self.assertEqual(pg.compare(data, data), [])

    def test_a_malformed_new_file_short_circuits(self):
        self.assertEqual(rules(pg.compare([entry(input_cost_per_token=1e-6)], [])), ["malformed"])

    def test_without_a_baseline_only_the_absolute_rules_run(self):
        findings = pg.compare(None, [entry(input_cost_per_token=5.0)])

        self.assertEqual(rules(findings), ["unit_slip"])

    def test_a_broken_baseline_is_ignored_not_trusted(self):
        findings = pg.compare([{"junk": True}], [entry(input_cost_per_token=1e-6)])

        self.assertEqual(findings, [])

    def test_every_rule_can_fire_in_one_publish(self):
        live = [entry(provider="p", model=f"m{i}", input_cost_per_token=1e-6, output_cost_per_token=2e-6) for i in range(10)]
        new = [entry(provider="p", model="m5", input_cost_per_token=5.0, output_cost_per_token=2e-6),
               entry(provider="p", model="m6", input_cost_per_token=1e-4, output_cost_per_token=2e-6),
               entry(provider="p", model="m7", input_cost_per_token=0, output_cost_per_token=2e-6),
               entry(provider="p", model="m8", input_cost_per_token=1e-6)]

        found = set(rules(pg.compare(live, new)))

        self.assertEqual(found, {"unit_slip", "price_jump", "price_to_zero", "field_dropped", "removed"})


class HostileNameTests(unittest.TestCase):
    """Model ids come from YAML anyone can propose in a PR; they must not be able to forge log commands."""

    EVIL = "x\n::error title=forged::pwned\r::add-mask::secret `rm -rf` \u2028::stop-commands::tok"

    def test_a_finding_is_always_a_single_line_without_backticks(self):
        finding = pg.Finding("price_jump", self.EVIL, "path: 1 -> 2 " + self.EVIL)

        for text in (finding.where, finding.detail, str(finding)):
            self.assertNotIn("\n", text)
            self.assertNotIn("\r", text)
            self.assertNotIn("\u2028", text)
            self.assertNotIn("`", text)

    def test_normal_names_are_unchanged(self):
        finding = pg.Finding("price_jump", "aws-bedrock/global.anthropic.claude-sonnet-5-5:0", "us-west-2|input_cost_per_token: 1e-06 -> 1e-05 (10.0x)")

        self.assertEqual(finding.where, "aws-bedrock/global.anthropic.claude-sonnet-5-5:0")
        self.assertIn("(10.0x)", finding.detail)

    def test_no_output_line_starts_with_a_workflow_command_from_the_data(self):
        live = [entry(provider="p", model=self.EVIL, input_cost_per_token=1e-6)]
        new = [entry(provider="p", model=self.EVIL, input_cost_per_token=1e-4)]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = {}
        for name, data in (("live", live), ("new", new)):
            paths[name] = os.path.join(tmp.name, name + ".json")
            with open(paths[name], "w", encoding="utf-8") as f:
                json.dump(data, f)
        summary = os.path.join(tmp.name, "summary.md")
        out = io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            pg.main(["--live", paths["live"], "--new", paths["new"], "--summary", summary])

        with open(summary, encoding="utf-8") as f:
            report = f.read()
        for line in (out.getvalue() + report).splitlines():
            for forged in ("::error title=forged", "::add-mask::", "::stop-commands::"):
                self.assertFalse(line.startswith(forged), line)
        annotations = [l for l in out.getvalue().splitlines() if l.startswith("::error title=publish guard::")]
        self.assertEqual(len(annotations), 1)  # the one real annotation, nothing forged beside it

    def test_a_percent_in_a_name_cannot_decode_into_a_newline_in_an_annotation(self):
        live = [entry(provider="p", model="a%0A::error::x", input_cost_per_token=1e-6)]
        new = [entry(provider="p", model="a%0A::error::x", input_cost_per_token=1e-4)]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, data in (("live", live), ("new", new)):
            with open(os.path.join(tmp.name, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f)
        out = io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            pg.main(["--live", os.path.join(tmp.name, "live.json"), "--new", os.path.join(tmp.name, "new.json")])

        annotation = [l for l in out.getvalue().splitlines() if l.startswith("::error title=publish guard::")][0]
        self.assertIn("a%250A::error::x", annotation)
        self.assertNotIn("%0A", annotation.replace("%250A", ""))


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pg.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_clean_publish_exits_zero_and_writes_the_summary(self):
        data = self.write("a.json", [entry(input_cost_per_token=1e-6)])
        summary = os.path.join(self.tmp.name, "summary.md")

        code, out, _ = self.run_main("--live", data, "--new", data, "--summary", summary)

        self.assertEqual(code, 0)
        with open(summary, encoding="utf-8") as f:
            self.assertIn("No findings", f.read())

    def test_blocking_findings_exit_ten_and_say_the_publish_is_blocked(self):
        live = self.write("live.json", [entry(input_cost_per_token=1e-6)])
        new = self.write("new.json", [entry(input_cost_per_token=2e-5)])

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, pg.EXIT_BLOCKING)
        self.assertIn("publish blocked", out)
        self.assertIn("::error", out)

    def test_warnings_alone_never_block_and_are_annotated_as_warnings(self):
        live = self.write("live.json", [entry(input_cost_per_token=1e-6)])
        new = self.write("new.json", [entry(input_cost_per_token=5e-6)])  # 5x

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, 0)
        self.assertIn("1 warning(s)", out)
        self.assertIn("price_change", out)
        self.assertIn("::warning title=publish guard::", out)
        self.assertNotIn("::error", out)
        self.assertNotIn("publish blocked", out)

    def test_warnings_next_to_a_blocking_finding_are_listed_after_it(self):
        live = self.write("live.json", [entry(model="a", input_cost_per_token=1e-6), entry(model="b", input_cost_per_token=1e-6)])
        new = self.write("new.json", [entry(model="a", input_cost_per_token=5e-6), entry(model="b", input_cost_per_token=1e-4)])

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, pg.EXIT_BLOCKING)
        self.assertLess(out.index("price_jump"), out.index("price_change"))
        self.assertIn("1 blocking finding(s)", out)
        self.assertIn("1 warning(s)", out)

    def test_report_only_prints_the_findings_but_exits_zero(self):
        live = self.write("live.json", [entry(input_cost_per_token=1e-6)])
        new = self.write("new.json", [entry(input_cost_per_token=2e-5)])

        code, out, _ = self.run_main("--live", live, "--new", new, "--report-only")

        self.assertEqual(code, 0)
        self.assertIn("price_jump", out)
        self.assertIn("override is on", out)
        self.assertNotIn("::error", out)

    def test_an_unreadable_live_file_runs_the_absolute_checks_and_says_so_loudly(self):
        new = self.write("new.json", [entry(input_cost_per_token=1e-6)])

        code, out, _ = self.run_main("--live", os.path.join(self.tmp.name, "missing.json"), "--new", new)

        self.assertEqual(code, 0)
        self.assertIn("No baseline", out)
        self.assertIn("::warning::publish guard ran without a baseline", out)

    def test_no_live_argument_is_the_same_as_an_unreadable_one(self):
        new = self.write("new.json", [entry(input_cost_per_token=1e-6)])

        code, out, _ = self.run_main("--new", new)

        self.assertEqual(code, 0)
        self.assertIn("No baseline", out)

    def test_a_unit_slip_still_blocks_without_a_baseline(self):
        new = self.write("new.json", [entry(input_cost_per_token=5.0)])

        code, out, _ = self.run_main("--new", new)

        self.assertEqual(code, pg.EXIT_BLOCKING)
        self.assertIn("unit_slip", out)

    def test_a_corrupt_live_file_is_treated_as_no_baseline(self):
        live = self.write("live.json", "{not json")
        new = self.write("new.json", [entry(input_cost_per_token=1e-6)])

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, 0)
        self.assertIn("No baseline", out)

    def test_a_live_file_that_is_not_a_list_is_treated_as_no_baseline(self):
        live = self.write("live.json", {"a": 1})
        new = self.write("new.json", [entry(input_cost_per_token=1e-6)])

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, 0)
        self.assertIn("No baseline", out)

    def test_a_crash_in_the_guard_exits_three_and_says_nothing_was_checked(self):
        new = self.write("new.json", [entry(input_cost_per_token=1e-6)])
        out, err = io.StringIO(), io.StringIO()

        with mock.patch.object(pg, "compare", side_effect=RuntimeError("bug")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pg.cli(["--new", new])

        self.assertEqual(code, 3)
        self.assertIn("RuntimeError: bug", err.getvalue())
        self.assertIn("nothing was checked", out.getvalue())

    def test_blocking_findings_and_a_bad_new_file_keep_their_own_exit_codes_through_cli(self):
        live = self.write("live.json", [entry(input_cost_per_token=1e-6)])
        slip = self.write("slip.json", [entry(input_cost_per_token=5.0)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(pg.cli(["--live", live, "--new", slip]), pg.EXIT_BLOCKING)
            self.assertEqual(pg.cli(["--new", os.path.join(self.tmp.name, "missing.json")]), 2)
            self.assertEqual(pg.cli(["--live", live, "--new", live]), 0)

    def test_an_unreadable_new_file_exits_two(self):
        code, _, err = self.run_main("--new", os.path.join(self.tmp.name, "missing.json"))

        self.assertEqual(code, 2)
        self.assertIn("cannot read the new file", err)

    def test_a_corrupt_new_file_exits_two(self):
        code, _, _ = self.run_main("--new", self.write("new.json", "{not json"))

        self.assertEqual(code, 2)

    def test_at_most_forty_findings_are_listed(self):
        live = self.write("live.json", [entry(model=f"m{i}", input_cost_per_token=1e-6) for i in range(100)])
        new = self.write("new.json", [entry(model=f"m{i}", input_cost_per_token=1e-4) for i in range(100)])

        code, out, _ = self.run_main("--live", live, "--new", new)

        self.assertEqual(code, pg.EXIT_BLOCKING)
        self.assertIn("100 blocking finding(s)", out)
        self.assertIn("and 60 more", out)


class MalformedNewFileTests(unittest.TestCase):
    """Publishing an empty or garbage catalog is never acceptable, whatever the flags."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_with(self, new_data, *flags):
        path = os.path.join(self.tmp.name, "new.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = pg.main(["--new", path, *flags])
        return code, out.getvalue()

    def test_a_structurally_malformed_file_exits_two_even_in_report_only_mode(self):
        for bad in ([], {"a": 1}, [{"provider": "x", "model": "y", "costs": []}], [{"model": "y"}], ["junk"]):
            for flags in ((), ("--report-only",)):
                code, out = self.run_with(bad, *flags)

                self.assertEqual(code, pg.EXIT_BAD_NEW_FILE, (bad, flags))
                self.assertIn("cannot be overridden", out)

    def test_a_malformed_file_cannot_be_overridden_with_a_live_baseline_either(self):
        live = os.path.join(self.tmp.name, "live.json")
        with open(live, "w", encoding="utf-8") as f:
            json.dump([entry(input_cost_per_token=1e-6)], f)
        new = os.path.join(self.tmp.name, "new.json")
        with open(new, "w", encoding="utf-8") as f:
            json.dump([], f)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(pg.main(["--live", live, "--new", new, "--report-only"]), pg.EXIT_BAD_NEW_FILE)


class UsableBaselineTests(unittest.TestCase):
    def test_one_broken_live_entry_does_not_switch_the_comparisons_off(self):
        live = [{"junk": True}] + [entry(model=f"m{i}", input_cost_per_token=1e-6) for i in range(5)]
        new = [entry(model=f"m{i}", input_cost_per_token=1e-6) for i in range(5)]
        new[0] = entry(model="m0", input_cost_per_token=1e-3)

        self.assertEqual(rules(pg.compare(live, new)), ["price_jump"])

    def test_the_cli_says_how_many_live_entries_it_ignored(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = {}
        for name, data in (("live", [{"junk": 1}, {"provider": "p"}, entry(input_cost_per_token=1e-6)]), ("new", [entry(input_cost_per_token=1e-6)])):
            paths[name] = os.path.join(tmp.name, name + ".json")
            with open(paths[name], "w", encoding="utf-8") as f:
                json.dump(data, f)
        out = io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = pg.main(["--live", paths["live"], "--new", paths["new"]])

        self.assertEqual(code, 0)
        self.assertIn("ignoring 2 live entries", out.getvalue())
        self.assertIn("2 live entries were ignored", out.getvalue())
        self.assertIn("Compared 1 new entries with 1 live entries", out.getvalue())

    def test_a_live_file_with_no_usable_entry_is_no_baseline(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        live, new = os.path.join(tmp.name, "live.json"), os.path.join(tmp.name, "new.json")
        for path, data in ((live, [{"junk": 1}]), (new, [entry(input_cost_per_token=5.0)])):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        out = io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = pg.main(["--live", live, "--new", new])

        self.assertEqual(code, pg.EXIT_BLOCKING)  # the unit slip still blocks
        self.assertIn("No baseline", out.getvalue())

    def test_a_live_file_that_is_not_a_list_says_it_ran_without_a_baseline(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        live, new = os.path.join(tmp.name, "live.json"), os.path.join(tmp.name, "new.json")
        for path, data in ((live, {"a": 1}), (new, [entry(input_cost_per_token=1e-6)])):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        out = io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            pg.main(["--live", live, "--new", new])

        self.assertIn("::warning::publish guard ran without a baseline", out.getvalue())


class FieldDroppedReplacementTests(unittest.TestCase):
    def dropped(self, **new_rates):
        live = [entry(input_cost_per_token=1e-6, output_cost_per_token=2e-6)]
        new = [entry(input_cost_per_token=1e-6, **new_rates)]
        return rules(pg.check_prices(live, new))

    def test_a_batches_rate_next_to_a_missing_main_rate_is_still_a_loss(self):
        self.assertEqual(self.dropped(output_cost_per_token_batches=1e-6), ["field_dropped"])

    def test_an_audio_or_cache_rate_is_not_a_replacement(self):
        self.assertEqual(self.dropped(output_cost_per_audio_token=1e-6), ["field_dropped"])
        self.assertEqual(self.dropped(cache_read_input_token_cost=1e-7), ["field_dropped"])

    def test_the_other_direction_is_not_a_replacement(self):
        live = [entry(input_cost_per_token=1e-6)]
        new = [entry(output_cost_per_image=0.04)]

        self.assertEqual(rules(pg.check_prices(live, new)), ["field_dropped"])

    def test_priced_per_image_second_character_page_query_request_or_video_token_is_a_change_of_unit(self):
        for unit in ("output_cost_per_image", "output_cost_per_image_token", "output_cost_per_second", "output_cost_per_second_480p",
                     "output_cost_per_character", "output_cost_per_page", "output_cost_per_query", "output_cost_per_request",
                     "output_cost_per_video_token"):
            self.assertEqual(self.dropped(**{unit: 1e-6}), [], unit)

    def test_a_nested_block_rate_is_not_a_replacement(self):
        self.assertEqual(self.dropped(priority_pricing={"output_cost_per_token": 3e-6}), ["field_dropped"])

    def test_a_rate_that_was_already_zero_is_not_reported_when_it_goes_away(self):
        live = [entry(input_cost_per_token=1e-6, output_cost_per_token=0)]
        new = [entry(input_cost_per_token=1e-6)]

        self.assertEqual(pg.check_prices(live, new), [])


class MassDropTests(unittest.TestCase):
    @staticmethod
    def models(n, provider="p", regions=("us",), **rates):
        return [{"provider": provider, "model": f"m{i}", "costs": [{"region": r, "input_cost_per_token": 1e-6, **rates} for r in regions]}
                for i in range(n)]

    def test_five_models_losing_cache_read_everywhere_is_caught_and_four_is_not(self):
        live = self.models(10, cache_read_input_token_cost=1e-7)
        for lost, expected in ((5, ["rate_dropped"]), (4, [])):
            new = self.models(10)
            for e in new[lost:]:
                e["costs"][0]["cache_read_input_token_cost"] = 1e-7

            self.assertEqual(rules(pg.check_dropped_rates(live, new)), expected, lost)

    def test_all_four_optional_rates_are_covered(self):
        for rate in pg.MASS_DROP_RATES:
            live = self.models(6, **{rate: 1e-7})
            findings = pg.check_dropped_rates(live, self.models(6))

            self.assertEqual([f.where for f in findings], [rate])

    def test_a_rate_kept_in_any_region_is_not_lost(self):
        live = self.models(6, regions=("us", "eu"), cache_read_input_token_cost=1e-7)
        new = self.models(6, regions=("us", "eu"))
        for e in new:
            e["costs"][1]["cache_read_input_token_cost"] = 1e-7

        self.assertEqual(pg.check_dropped_rates(live, new), [])

    def test_a_rate_that_was_zero_is_not_counted_as_lost(self):
        self.assertEqual(pg.check_dropped_rates(self.models(6, cache_read_input_token_cost=0), self.models(6)), [])

    def test_five_models_of_one_provider_losing_a_region_is_caught(self):
        live = self.models(8, regions=("us", "eu"))
        new = self.models(8, regions=("us", "eu"))
        for e in new[:5]:
            e["costs"] = e["costs"][:1]

        findings = pg.check_dropped_regions(live, new)

        self.assertEqual(rules(findings), ["regions_dropped"])
        self.assertEqual(findings[0].where, "p")

    def test_four_models_losing_a_region_is_not(self):
        live = self.models(8, regions=("us", "eu"))
        new = self.models(8, regions=("us", "eu"))
        for e in new[:4]:
            e["costs"] = e["costs"][:1]

        self.assertEqual(pg.check_dropped_regions(live, new), [])

    def test_single_region_models_cannot_lose_a_region_and_providers_are_counted_separately(self):
        self.assertEqual(pg.check_dropped_regions(self.models(8), self.models(8, regions=("eu",))), [])
        live = self.models(3, "a", regions=("us", "eu")) + self.models(3, "b", regions=("us", "eu"))
        new = self.models(3, "a") + self.models(3, "b")  # each provider loses 3, none reaches 5

        self.assertEqual(pg.check_dropped_regions(live, new), [])

    def test_compare_runs_all_the_mass_drop_checks(self):
        live = self.models(10, regions=("us", "eu"), cache_read_input_token_cost=1e-7, priority_pricing={"input_cost_per_token": 2e-6})
        new = self.models(10)

        found = set(rules(pg.compare(live, new)))

        self.assertTrue({"block_dropped", "rate_dropped", "regions_dropped"} <= found, found)


class BadRateTests(unittest.TestCase):
    def test_negative_and_non_finite_rates_are_caught(self):
        for bad in (-1e-6, float("inf"), float("-inf"), float("nan")):
            findings = pg.check_bad_rates([entry(input_cost_per_token=bad)])

            self.assertEqual(rules(findings), ["bad_rate"], bad)

    def test_zero_and_ordinary_rates_pass(self):
        self.assertEqual(pg.check_bad_rates([entry(input_cost_per_token=0, output_cost_per_token=2e-6)]), [])

    def test_an_integer_too_large_for_a_float_does_not_crash(self):
        flat = pg.flatten_costs([{"region": "*", "input_cost_per_token": 10 ** 400}])

        self.assertEqual(flat["*|input_cost_per_token"], float("inf"))
        self.assertEqual(sorted({f.rule for f in pg.compare(None, [entry(input_cost_per_token=10 ** 400)])}), ["bad_rate", "unit_slip"])

    def test_bad_rates_block_without_a_baseline(self):
        self.assertEqual(rules(pg.compare(None, [entry(input_cost_per_token=-1.0)])), ["bad_rate"])


class MoreUnitSlipTests(unittest.TestCase):
    def test_cache_and_audio_token_rates_are_checked_too(self):
        for field in ("cache_read_input_token_cost", "cache_creation_input_token_cost", "input_cost_per_audio_token",
                      "input_cost_per_token_batches", "output_cost_per_video_token"):
            self.assertEqual(rules(pg.check_unit_slips([entry(**{field: 5.0})])), ["unit_slip"], field)


class RemovalBoundaryTests(unittest.TestCase):
    @staticmethod
    def catalog(**counts):
        return [entry(provider=p, model=f"m{i}", input_cost_per_token=1e-6) for p, n in counts.items() for i in range(n)]

    def test_exactly_twenty_percent_of_a_provider_is_caught_and_sixteen_is_not(self):
        live = self.catalog(p=25, big=1000)
        for removed, expected in ((5, ["removed"]), (4, [])):
            new = [e for e in live if not (e["provider"] == "p" and int(e["model"][1:]) < removed)]

            self.assertEqual(rules(pg.check_removals(live, new)), expected, removed)

    def test_the_provider_percentage_uses_that_providers_own_size(self):
        live = self.catalog(p=100, big=1000)
        new = [e for e in live if not (e["provider"] == "p" and int(e["model"][1:]) < 19)]  # 19% of p

        self.assertEqual(pg.check_removals(live, new), [])


class StructureLimitTests(unittest.TestCase):
    def test_a_file_full_of_bad_entries_lists_at_most_forty(self):
        self.assertEqual(len(pg.check_structure([{"junk": i} for i in range(200)])), pg.MAX_LISTED)


class SummaryRenderingTests(unittest.TestCase):
    def test_names_are_rendered_inside_a_code_span_so_markdown_cannot_inject_links(self):
        finding = pg.Finding("price_jump", "p/[click](http://evil.example)<b>x</b>", "path: 1 -> 100")

        report = pg.render_summary([finding], 10, 10, False)
        line = [l for l in report.splitlines() if "price_jump" in l][0]

        self.assertTrue(line.startswith("- `price_jump` `"), line)
        self.assertTrue(line.endswith("`"), line)
        self.assertEqual(line.count("`"), 4)  # no backtick from the data can close the span early


class ExitCodeTests(unittest.TestCase):
    def test_the_codes_the_workflow_relies_on(self):
        self.assertEqual((pg.EXIT_OK, pg.EXIT_BAD_NEW_FILE, pg.EXIT_CRASH, pg.EXIT_BLOCKING), (0, 2, 3, 10))
        # 1 is what Python itself exits with after an uncaught error, so it must not mean "blocked".
        self.assertNotIn(1, (pg.EXIT_OK, pg.EXIT_BAD_NEW_FILE, pg.EXIT_CRASH, pg.EXIT_BLOCKING))


if __name__ == "__main__":
    unittest.main()
