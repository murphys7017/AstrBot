import pytest

from astrbot.core.star.filter.command_group import CommandGroupFilter


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("math add 1 2", True),
        ("math   add\n1 2", True),
        ("mathematics", False),
        ("math123", False),
    ],
)
def test_group_matches_whole_words_only(message, expected):
    group = CommandGroupFilter("math")
    assert group.startswith(message) is expected


def test_nested_group_matches_whole_words_only():
    parent = CommandGroupFilter("tool")
    group = CommandGroupFilter("config", parent_group=parent)

    assert group.startswith("tool config set a 1")
    assert not group.startswith("tool configure")


@pytest.mark.parametrize("message", ["tool config", "tool   config", "tool\tconfig"])
def test_equals_normalizes_whitespace(message):
    parent = CommandGroupFilter("tool")
    group = CommandGroupFilter("config", parent_group=parent)

    assert group.equals(message)
