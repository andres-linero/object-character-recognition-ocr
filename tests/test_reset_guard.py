import pytest

from scripts import rebuild_scan_dataset


def test_reset_requires_explicit_flag_before_touching_data(monkeypatch):
    def forbidden_replace(root):
        pytest.fail("Reset must not touch data without explicit confirmation")

    monkeypatch.setattr(rebuild_scan_dataset, "replace", forbidden_replace)
    with pytest.raises(SystemExit) as error:
        rebuild_scan_dataset.main([])
    assert error.value.code == 2


def test_explicit_reset_dispatches_to_rebuilder(monkeypatch):
    calls = []
    monkeypatch.setattr(rebuild_scan_dataset, "replace", calls.append)
    rebuild_scan_dataset.main(["--confirm-reset"])
    assert calls == [rebuild_scan_dataset.Path(__file__).resolve().parents[1]]
