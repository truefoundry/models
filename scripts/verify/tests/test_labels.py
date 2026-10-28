import re

import pytest

from verify import labels
from verify.labels import DESCRIPTION_MAX, FAST_LANE, META, OWNED, is_hold, is_owned, label_meta


def test_fast_lane_is_owned_by_exact_name():
    assert FAST_LANE == "fast-lane" and is_owned("fast-lane") and "fast-lane" in OWNED
    for near in ("fast-lane ", "Fast-lane", "fast_lane", "fastlane", "fast-lane:x", "gate:fast-lane", "lane:fast-lane"):
        assert not is_owned(near), near
    assert "fast-lane" not in labels.GATE_LABELS | labels.RISK_LABELS | labels.KIND_LABELS | labels.VERIFY_LABELS


def test_every_owned_label_has_a_colour_and_a_short_description():
    assert set(META) == set(OWNED), set(OWNED) ^ set(META)
    for name in OWNED:
        colour, description = label_meta(name)
        assert re.fullmatch(r"[0-9a-f]{6}", colour), (name, colour)
        assert description.strip() and "\n" not in description and len(description) <= DESCRIPTION_MAX, name
        assert description == description.strip()


def test_descriptions_are_distinct_enough_to_tell_labels_apart():
    descriptions = [label_meta(n)[1] for n in OWNED]
    assert len(set(descriptions)) == len(descriptions)


def test_no_meta_for_labels_that_are_not_ours():
    for name in ("gate:hold", "gate:reviewed", "id:5", "id:case-duplicate", "id:high-edit-provider", "verify:prices-from-source", "bug", ""):
        assert label_meta(name) is None


def test_the_four_review_lanes():
    assert labels.LANES == ("fast-lane", "normal", "escalate", "hold")


@pytest.mark.parametrize("names,hold", [(["gate:hold"], True), (["id:1"], False), (["id:case-duplicate"], False), (["fast-lane"], False), (["gate:holdup"], False)])
def test_fast_lane_does_not_change_hold(names, hold):
    assert is_hold(names) is hold


def test_addition_flags_and_the_prices_from_source_label_belong_to_the_addition_job():
    assert labels.addition_flags(["id:case-duplicate", "bug"]) == ["addition flagged: case duplicate of an existing file"]
    assert labels.addition_flags(["id:7", "gate:hold", "id:CASE-DUPLICATE"]) == []
    assert labels.PRICES_FROM_SOURCE == "verify:prices-from-source" and not is_owned(labels.PRICES_FROM_SOURCE)
    assert not any(n.startswith("id:") for n in OWNED) and "verify:prices-from-source" not in OWNED
