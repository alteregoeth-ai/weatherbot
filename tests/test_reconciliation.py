from weatherbot.execution.reconciliation import (
    LocalFill,
    ReconciliationIssue,
    RemoteFill,
    PositionSnapshot,
    reconcile_execution_state,
)


def local_fill(decision_id="decision-1", market_id="market-1", outcome="YES", shares=2.0):
    return LocalFill(
        decision_id=decision_id,
        market_id=market_id,
        outcome=outcome,
        shares=shares,
        price=0.50,
        dollars=1.0,
    )


def remote_fill(decision_id="decision-1", market_id="market-1", outcome="YES", shares=2.0):
    return RemoteFill(
        decision_id=decision_id,
        remote_order_id="remote-1",
        market_id=market_id,
        outcome=outcome,
        shares=shares,
        price=0.50,
        dollars=1.0,
    )


def position(market_id="market-1", outcome="YES", shares=2.0):
    return PositionSnapshot(market_id=market_id, outcome=outcome, shares=shares)


def test_reconciliation_passes_when_fills_and_positions_match():
    report = reconcile_execution_state(
        local_fills=[local_fill()],
        remote_fills=[remote_fill()],
        local_positions=[position()],
        remote_positions=[position()],
    )

    assert report.ok is True
    assert report.can_open_new_trades is True
    assert report.issues == []


def test_reconciliation_detects_missing_remote_fill_for_local_fill():
    report = reconcile_execution_state(
        local_fills=[local_fill()],
        remote_fills=[],
        local_positions=[position()],
        remote_positions=[],
    )

    assert report.ok is False
    assert report.can_open_new_trades is False
    assert ReconciliationIssue(
        code="missing_remote_fill",
        decision_id="decision-1",
        market_id="market-1",
        outcome="YES",
        detail="local fill has no matching remote fill",
    ) in report.issues


def test_reconciliation_detects_remote_fill_missing_from_local_ledger():
    report = reconcile_execution_state(
        local_fills=[],
        remote_fills=[remote_fill()],
        local_positions=[],
        remote_positions=[position()],
    )

    assert report.ok is False
    assert report.can_open_new_trades is False
    assert report.issues[0].code == "missing_local_fill"
    assert report.issues[0].decision_id == "decision-1"


def test_reconciliation_detects_position_share_mismatch():
    report = reconcile_execution_state(
        local_fills=[local_fill()],
        remote_fills=[remote_fill()],
        local_positions=[position(shares=2.0)],
        remote_positions=[position(shares=1.5)],
    )

    assert report.ok is False
    assert report.can_open_new_trades is False
    assert report.issues == [
        ReconciliationIssue(
            code="position_mismatch",
            market_id="market-1",
            outcome="YES",
            detail="local shares 2.0 != remote shares 1.5",
        )
    ]


def test_reconciliation_builds_local_fills_from_ledger_entries():
    entries = [
        {
            "decision_id": "decision-1",
            "event_type": "decision",
            "payload": {"market_id": "market-1"},
        },
        {
            "decision_id": "decision-1",
            "event_type": "paper_fill",
            "payload": {
                "market_id": "market-1",
                "outcome": "YES",
                "shares": 2.0,
                "fill_price": 0.5,
                "dollars": 1.0,
            },
        },
    ]

    fills = LocalFill.from_ledger_entries(entries)

    assert fills == [local_fill()]
