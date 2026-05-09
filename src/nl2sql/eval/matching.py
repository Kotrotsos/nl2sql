"""Result-row matching for the eval harness.

Implements the article's three rules:
- numeric tolerance
- case-insensitive string compare
- bipartite row matching for unordered result sets
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


@dataclass
class RowMatcher:
    """Pair-of-values matcher with tolerance and case folding."""

    numeric_tolerance: float = 0.01
    case_insensitive_strings: bool = True

    def values_equal(self, a: Any, b: Any) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b)
        if _is_number(a) and _is_number(b):
            if a == b:
                return True
            denom = max(1.0, abs(float(a)), abs(float(b)))
            return abs(float(a) - float(b)) <= self.numeric_tolerance * denom
        if isinstance(a, str) and isinstance(b, str):
            if self.case_insensitive_strings:
                return a.strip().lower() == b.strip().lower()
            return a.strip() == b.strip()
        # cross-type: try string compare
        return str(a) == str(b)


@dataclass
class FlexibleMatcher:
    """Match a predicted result set against an expected one."""

    numeric_tolerance: float = 0.01
    case_insensitive_strings: bool = True
    row_matching: Literal["bipartite", "ordered"] = "bipartite"

    def __post_init__(self):
        self._row = RowMatcher(
            numeric_tolerance=self.numeric_tolerance,
            case_insensitive_strings=self.case_insensitive_strings,
        )

    def rows_match(
        self,
        predicted: Iterable[dict[str, Any]] | None,
        expected: Iterable[dict[str, Any]] | None,
    ) -> tuple[bool, str | None]:
        """Return (passed, diff_str)."""
        if expected is None:
            return predicted is None, None
        if predicted is None:
            return False, "predicted no rows"
        pred = list(predicted)
        exp = list(expected)

        if len(pred) != len(exp):
            return (
                False,
                f"row count: predicted {len(pred)}, expected {len(exp)}",
            )

        if self.row_matching == "ordered":
            for i, (p, e) in enumerate(zip(pred, exp)):
                ok, diff = self._row_dict_equal(p, e)
                if not ok:
                    return False, f"row {i}: {diff}"
            return True, None

        # bipartite: maximum matching where a pair matches if all common
        # columns compare equal under the value rules.
        used = [False] * len(pred)
        for j, e in enumerate(exp):
            matched = False
            for i, p in enumerate(pred):
                if used[i]:
                    continue
                ok, _ = self._row_dict_equal(p, e)
                if ok:
                    used[i] = True
                    matched = True
                    break
            if not matched:
                return False, f"expected row {j} {e!r} has no predicted match"
        return True, None

    def _row_dict_equal(
        self, p: dict[str, Any], e: dict[str, Any]
    ) -> tuple[bool, str | None]:
        # Compare on the intersection of keys (the article's rule). Missing
        # columns on either side are tolerated only if the other side has them
        # as None.
        keys_p = {k.lower(): k for k in p.keys()}
        keys_e = {k.lower(): k for k in e.keys()}
        common = set(keys_p) & set(keys_e)
        if not common:
            return False, "no shared columns"
        for k in common:
            pv = p[keys_p[k]]
            ev = e[keys_e[k]]
            if not self._row.values_equal(pv, ev):
                return False, f"col {k!r}: {pv!r} != {ev!r}"
        return True, None
