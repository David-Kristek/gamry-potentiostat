"""Technique-key naming: repeated techniques get occurrence suffixes, and the
suffix is stripped back off to find the base technique."""

from __future__ import annotations

import pytest

from potentiostat.utils.technique_keys import base_technique, occurrence_keys


def test_single_occurrences_keep_bare_names():
    assert occurrence_keys(["ocp", "eis", "lpr", "cpp"]) == ["ocp", "eis", "lpr", "cpp"]


def test_repeated_techniques_get_numbered_suffixes():
    assert occurrence_keys(["ocp", "eis", "eis", "lpr"]) == ["ocp", "eis_1", "eis_2", "lpr"]


def test_repeated_non_adjacent_techniques_share_numbering():
    # Numbering is per-name across the whole sequence, not per-run.
    assert occurrence_keys(["ocp", "eis", "lpr", "eis"]) == ["ocp", "eis_1", "lpr", "eis_2"]


def test_empty_sequence():
    assert occurrence_keys([]) == []


@pytest.mark.parametrize(
    "key, expected",
    [
        ("eis", "eis"),
        ("eis_2", "eis"),
        ("cpp_10", "cpp"),
        ("ocp_1", "ocp"),
        ("foo_bar", "foo_bar"),  # non-numeric suffix is not an occurrence marker
        ("eis_", "eis_"),
        ("2", "2"),
    ],
)
def test_base_technique(key, expected):
    assert base_technique(key) == expected
