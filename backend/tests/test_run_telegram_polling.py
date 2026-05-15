import pytest

from scripts import run_telegram_polling


def test_run_loop_retries_after_exception(monkeypatch, capsys):
    calls: list[bool] = []

    def fake_run_once(*, disable_webhook: bool) -> None:
        calls.append(disable_webhook)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        raise KeyboardInterrupt()

    def fake_sleep(seconds: float) -> None:
        assert seconds == 0.5

    monkeypatch.setattr(run_telegram_polling, "run_once", fake_run_once)
    monkeypatch.setattr(run_telegram_polling.time, "sleep", fake_sleep)

    with pytest.raises(KeyboardInterrupt):
        run_telegram_polling.run_loop(interval=0.1, disable_webhook=True)

    stderr = capsys.readouterr().err
    assert "polling_error" in stderr
    assert "TimeoutError" in stderr
    assert calls == [True, True]
