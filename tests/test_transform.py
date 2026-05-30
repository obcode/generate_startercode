from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transform import _is_removed, transform_source


def test_solution_keeps_block_and_removes_markers() -> None:
    src = """\
def foo(x):
    # SOLUTION_BEGIN
    return x * 2
    # SOLUTION_END
"""

    out = transform_source(src, "solution")

    assert "SOLUTION_BEGIN" not in out
    assert "SOLUTION_END" not in out
    assert "return x * 2" in out


def test_startercode_replaces_block_when_replacement_is_set() -> None:
    src = """\
def foo(x):
    # SOLUTION_BEGIN raise NotImplementedError
    return x * 2
    # SOLUTION_END
"""

    out = transform_source(src, "startercode")

    assert "return x * 2" not in out
    assert "raise NotImplementedError" in out


def test_startercode_drops_block_when_no_replacement_exists() -> None:
    src = """\
def foo(x):
    # SOLUTION_BEGIN
    return x * 2
    # SOLUTION_END
    return x
"""

    out = transform_source(src, "startercode")

    assert "return x * 2" not in out
    assert "return x" in out


def test_removed_path_matching() -> None:
    assert _is_removed(Path("Aufgabenstellung/Task1.md"), {"Aufgabenstellung"})
    assert _is_removed(Path(".gitlab/ci/config.yml"), {".gitlab/ci"})
    assert not _is_removed(Path("src/main.py"), {"Aufgabenstellung"})


def test_solution_import_block_does_not_leave_blank_separator() -> None:
    src = """\
from typing import TypeVar

from blatt_06.bst import BinarySearchTree, Comparable

# SOLUTION_BEGIN
from blatt_06.tree_node import TreeNode

# SOLUTION_END
"""

    out = transform_source(src, "solution")

    assert (
        "from blatt_06.bst import BinarySearchTree, Comparable\n"
        "from blatt_06.tree_node import TreeNode\n" in out
    )


def test_startercode_does_not_leave_three_consecutive_blank_lines() -> None:
    src = """\
def foo():
    return 1

# SOLUTION_BEGIN
print("hidden")
# SOLUTION_END

def bar():
    return 2
"""

    out = transform_source(src, "startercode")

    assert "\n\n\n" not in out
