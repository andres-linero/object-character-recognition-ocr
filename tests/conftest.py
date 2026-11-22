"""Shared synchronization for tests that exercise the real intake worker."""
import time

import pytest


@pytest.fixture
def wait_for_intake():
    def wait(app, phase, timeout=60):
        # Processing includes PDF rendering and SQL writes, even with mocked
        # Azure. Hosted Windows runners can exceed five seconds per scan.
        deadline = time.monotonic() + timeout
        while True:
            snapshot = app.state.intake_progress.snapshot()
            if snapshot['phase'] == phase:
                return snapshot
            assert snapshot['phase'] not in {'error', 'ready', 'needs_attention'}, snapshot
            assert time.monotonic() < deadline, f'Intake did not reach {phase!r} within {timeout}s: {snapshot}'
            time.sleep(.05)

    return wait
