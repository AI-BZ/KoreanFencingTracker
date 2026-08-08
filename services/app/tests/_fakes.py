"""In-memory fake Supabase client for app-service pipeline tests.

Unlike the ad-hoc fake in ``test_dispatcher_kakao.py`` (whose ``.eq()/.in_()/.gt()``
are no-ops), this fake **actually filters**. That matters because the production
code relies on filter correctness (``members.player_id`` scoping, ``data_events.id``
watermark advancement, idempotency lookups keyed on 4 columns). A no-op fake would
pass even if those filters were dropped.

Supported (only what the pipeline uses):
    table(name)
      .select(*cols)              → returns full stored rows (column projection ignored)
      .insert(dict|list)          → appends, auto-assigns int "id" when absent
      .update(dict)               → mutates matching rows in place
      .upsert(dict|list, on_conflict="a,b") → insert or replace by conflict key
      .delete()                   → removes matching rows
      .eq/.neq/.in_/.gt/.gte/.lt/.lte(col, val)
      .order(col, desc=False)     → applied to select only
      .limit(n)                   → applied to select only
      .single()                   → select returns one object (or None) instead of list
      .execute()                  → _Result(data=...)

A table listed in ``raise_on`` makes any ``.execute()`` on it raise, to exercise
the pipeline's exception-absorption paths.
"""
from __future__ import annotations

import copy
from typing import Any, Iterable, Optional


class _Result:
    def __init__(self, data: Any):
        self.data = data


class _Table:
    def __init__(self, db: "FakeSupabase", name: str):
        self._db = db
        self._name = name
        self._op: Optional[str] = None
        self._payload: Any = None
        self._on_conflict: Optional[str] = None
        self._filters: list[tuple[str, str, Any]] = []
        self._order: Optional[tuple[str, bool]] = None
        self._limit: Optional[int] = None
        self._single = False

    # ---- operation selectors -------------------------------------------------
    def select(self, *_cols: Any, **_kw: Any) -> "_Table":
        self._op = "select"
        return self

    def insert(self, row: Any) -> "_Table":
        self._op = "insert"
        self._payload = row
        return self

    def update(self, patch: dict) -> "_Table":
        self._op = "update"
        self._payload = patch
        return self

    def upsert(self, row: Any, on_conflict: Optional[str] = None) -> "_Table":
        self._op = "upsert"
        self._payload = row
        self._on_conflict = on_conflict
        return self

    def delete(self) -> "_Table":
        self._op = "delete"
        return self

    # ---- filters / modifiers -------------------------------------------------
    def eq(self, col: str, val: Any) -> "_Table":
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col: str, val: Any) -> "_Table":
        self._filters.append(("neq", col, val))
        return self

    def in_(self, col: str, vals: Iterable[Any]) -> "_Table":
        self._filters.append(("in", col, list(vals)))
        return self

    def gt(self, col: str, val: Any) -> "_Table":
        self._filters.append(("gt", col, val))
        return self

    def gte(self, col: str, val: Any) -> "_Table":
        self._filters.append(("gte", col, val))
        return self

    def lt(self, col: str, val: Any) -> "_Table":
        self._filters.append(("lt", col, val))
        return self

    def lte(self, col: str, val: Any) -> "_Table":
        self._filters.append(("lte", col, val))
        return self

    def order(self, col: str, desc: bool = False) -> "_Table":
        self._order = (col, desc)
        return self

    def limit(self, n: int) -> "_Table":
        self._limit = n
        return self

    def single(self) -> "_Table":
        self._single = True
        return self

    # ---- execution -----------------------------------------------------------
    def _match(self, row: dict) -> bool:
        for op, col, val in self._filters:
            cur = row.get(col)
            if op == "eq":
                if cur != val:
                    return False
            elif op == "neq":
                if cur == val:
                    return False
            elif op == "in":
                if cur not in val:
                    return False
            elif op == "gt":
                if cur is None or not (cur > val):
                    return False
            elif op == "gte":
                if cur is None or not (cur >= val):
                    return False
            elif op == "lt":
                if cur is None or not (cur < val):
                    return False
            elif op == "lte":
                if cur is None or not (cur <= val):
                    return False
        return True

    def _next_id(self, rows: list[dict]) -> int:
        ints = [r["id"] for r in rows if isinstance(r.get("id"), int)]
        base = max(ints) if ints else 0
        return base + 1

    def _insert_one(self, rows: list[dict], row: dict) -> dict:
        stored = copy.deepcopy(row)
        if "id" not in stored or stored["id"] is None:
            stored["id"] = self._next_id(rows)
        rows.append(stored)
        return copy.deepcopy(stored)

    def execute(self) -> _Result:
        if self._name in self._db._raise_on:
            raise RuntimeError(f"fake supabase: forced failure on table '{self._name}'")

        rows = self._db._tables.setdefault(self._name, [])

        if self._op == "insert":
            payload = self._payload
            if isinstance(payload, list):
                return _Result([self._insert_one(rows, r) for r in payload])
            return _Result([self._insert_one(rows, payload)])

        if self._op == "upsert":
            conflict_cols = (
                [c.strip() for c in self._on_conflict.split(",")]
                if self._on_conflict
                else ["id"]
            )
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            out: list[dict] = []
            for incoming in payload:
                existing = next(
                    (
                        r
                        for r in rows
                        if all(r.get(c) == incoming.get(c) for c in conflict_cols)
                    ),
                    None,
                )
                if existing is not None:
                    existing.update(copy.deepcopy(incoming))
                    out.append(copy.deepcopy(existing))
                else:
                    out.append(self._insert_one(rows, incoming))
            return _Result(out)

        matched = [r for r in rows if self._match(r)]

        if self._op == "select":
            if self._order is not None:
                col, desc = self._order
                matched = sorted(
                    matched, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc
                )
            if self._limit is not None:
                matched = matched[: self._limit]
            data = [copy.deepcopy(r) for r in matched]
            if self._single:
                return _Result(data[0] if data else None)
            return _Result(data)

        if self._op == "update":
            for r in matched:
                r.update(copy.deepcopy(self._payload))
            return _Result([copy.deepcopy(r) for r in matched])

        if self._op == "delete":
            for r in list(matched):
                rows.remove(r)
            return _Result([copy.deepcopy(r) for r in matched])

        return _Result([])


class FakeSupabase:
    """In-memory stand-in for a supabase-py client.

    Args:
        tables: initial ``{table_name: [row, ...]}`` seed data (deep-copied).
        raise_on: table names whose ``.execute()`` should raise.
    """

    def __init__(
        self,
        tables: Optional[dict[str, list[dict]]] = None,
        raise_on: Optional[Iterable[str]] = None,
    ):
        self._tables: dict[str, list[dict]] = {
            name: [copy.deepcopy(r) for r in rows] for name, rows in (tables or {}).items()
        }
        self._raise_on: set[str] = set(raise_on or ())

    def table(self, name: str) -> _Table:
        return _Table(self, name)

    # ---- test inspection helpers --------------------------------------------
    def rows(self, name: str) -> list[dict]:
        """Current rows of a table (live reference)."""
        return self._tables.setdefault(name, [])

    def count(self, name: str) -> int:
        return len(self._tables.get(name, []))
