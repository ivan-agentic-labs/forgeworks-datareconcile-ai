"""Owner-reviewable finance rule: duplicates are exceptions, not invented matches."""
import hashlib
from itertools import permutations

import pytest

from datareconcile_ai.infrastructure.store import Store, TENANT


def import_amounts(store, side, amounts):
    csv_data = (
        "external_ref,currency,amount_minor,occurred_at\n" +
        "".join(
            f"{side}-{i},IDR,{amount},2026-10-11T00:00:00Z\n"
            for i, amount in enumerate(amounts)
        )
    )
    return store.batch(
        TENANT, side, hashlib.sha256(csv_data.encode()).hexdigest(),
        "IDR", csv_content=csv_data,
    )["id"]


def get_counts(store, rid):
    with store.conn() as db:
        allocations = list(db.execute(
            "SELECT * FROM allocations WHERE tenant_id=? AND run_id=?", (TENANT, rid),
        ))
        exceptions = list(db.execute(
            "SELECT * FROM exceptions WHERE tenant_id=? AND run_id=?", (TENANT, rid),
        ))
    return allocations, exceptions


def test_opt_in_unique_matching_retains_exact_automatic_allocation(tmp_path):
    store = Store(str(tmp_path / "unique.sqlite"))
    left = import_amounts(store, "left", [100, 200, -50])
    right = import_amounts(store, "right", [-50, 200, 100])
    run = store.run(TENANT, left, right, "unambiguous-amount-v2")
    allocations, exceptions = get_counts(store, run["id"])
    assert len(allocations) == 3 and not exceptions
    assert run["unmatched"] == 0
    assert store.partition_valid(TENANT, run["id"])


@pytest.mark.parametrize("left_amounts,right_amounts,matched,exceptions", [
    ([100, 100], [100, 100], 0, 4),
    ([100, 100], [100], 0, 3),
    ([100], [100, 100], 0, 3),
    ([100, 100, 200], [100, 100, 200], 1, 4),
])
def test_ambiguous_duplicate_amounts_never_auto_allocate(tmp_path,left_amounts,right_amounts,matched,exceptions):
    store = Store(str(tmp_path / "ambiguous.sqlite"))
    left = import_amounts(store, "left", left_amounts)
    right = import_amounts(store, "right", right_amounts)
    run = store.run(TENANT, left, right, "unambiguous-amount-v2")
    allocations, findings = get_counts(store, run["id"])
    assert len(allocations) == matched
    assert len(findings) == run["unmatched"] == exceptions
    assert all(item["reason"] == "AMBIGUOUS_AMOUNT" for item in findings)
    assert store.partition_valid(TENANT, run["id"])
    _, status = store.finalize(TENANT, run["id"], "a" * 64, run["version"])
    assert status == "OPEN_EXCEPTIONS"
    for item in findings:
        _, outcome = store.resolve(TENANT, item["id"], "00000000-0000-4000-8000-000000000099",
                                    "accept-as-investigated", "b" * 64, 1)
        assert outcome == "OK"
    report, outcome = store.finalize(TENANT, run["id"], "a" * 64, run["version"])
    assert outcome == "OK" and report["artifact_sha"]
    assert store.totals(TENANT, run["id"])["row_partition_valid"]


@pytest.mark.parametrize("left_amounts", list(permutations([100, 100, 200])))
def test_ambiguous_decision_is_independent_of_csv_source_order(tmp_path, left_amounts):
    store = Store(str(tmp_path / "order.sqlite"))
    left = import_amounts(store, "left", left_amounts)
    right = import_amounts(store, "right", [100, 200, 100])
    run = store.run(TENANT, left, right, "unambiguous-amount-v2")
    allocations, findings = get_counts(store, run["id"])
    assert len(allocations) == 1
    assert {item["matched_amount_minor"] for item in allocations} == {200}
    assert len(findings) == 4
    assert store.partition_valid(TENANT, run["id"])


def test_legacy_exact_v1_is_not_silently_changed(tmp_path):
    store = Store(str(tmp_path / "legacy.sqlite"))
    left = import_amounts(store, "left", [100, 100])
    right = import_amounts(store, "right", [100, 100])
    legacy = store.run(TENANT, left, right, "exact-v1")
    allocated, findings = get_counts(store, legacy["id"])
    assert len(allocated) == 2 and not findings
    assert store.partition_valid(TENANT, legacy["id"])
