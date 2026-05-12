from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class BackgroundVerifier:
    def __init__(
        self,
        verify_fn: Callable[[], tuple[bool, int | None, str]],
        on_corruption: Callable[[str], None],
        interval_s: float = 30.0,
    ) -> None:
        self.verify_fn = verify_fn
        self.on_corruption = on_corruption
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="replica-verifier", daemon=True)
        self._thread.start()
        logger.info("Background verifier started (interval=%ss)", self.interval_s)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ok, bad, reason = self.verify_fn()
                if not ok:
                    logger.error("Verify FAIL bad=%s reason=%s", bad, reason)
                    self.on_corruption(reason)
            except Exception:
                logger.exception("Background verify crashed")
            self._stop.wait(self.interval_s)


class BackgroundLeaderSync:
    """Periodically pull a longer chain from LEADER_URL (see RecoveryManager.sync_from_leader)."""

    def __init__(self, sync_fn: Callable[[], None], interval_s: float = 5.0) -> None:
        self.sync_fn = sync_fn
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="replica-leader-sync", daemon=True)
        self._thread.start()
        logger.info("Leader chain sync started (interval=%ss)", self.interval_s)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_fn()
            except Exception:
                logger.exception("Leader sync crashed")
            self._stop.wait(self.interval_s)
