from weatherbot.risk.kill_switch import KillSwitch


def test_kill_switch_allows_trading_when_file_absent(tmp_path):
    switch = KillSwitch(tmp_path / "KILL_SWITCH")

    assert not switch.is_triggered()
    assert switch.allows_new_trades()


def test_kill_switch_blocks_new_trades_when_file_exists(tmp_path):
    path = tmp_path / "KILL_SWITCH"
    path.write_text("stop now")
    switch = KillSwitch(path)

    assert switch.is_triggered()
    assert not switch.allows_new_trades()
    assert switch.reason() == "stop now"


def test_kill_switch_can_be_triggered_and_cleared(tmp_path):
    switch = KillSwitch(tmp_path / "KILL_SWITCH")

    switch.trigger("manual stop from operator")
    assert switch.is_triggered()
    assert not switch.allows_new_trades()
    assert switch.reason() == "manual stop from operator"

    switch.clear()
    assert not switch.is_triggered()
    assert switch.allows_new_trades()


def test_empty_kill_switch_file_has_default_reason(tmp_path):
    path = tmp_path / "KILL_SWITCH"
    path.write_text("")

    assert KillSwitch(path).reason() == "kill switch file present"
