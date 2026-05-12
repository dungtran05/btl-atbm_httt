from __future__ import annotations

import logging
import threading
import time
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
        self._thread = threading.Thread(target=self._run, name="chain-verifier", daemon=True)
        self._thread.start()
        logger.info("Background verifier started (interval=%ss)", self.interval_s)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ok, bad, reason = self.verify_fn()
                if ok:
                    logger.debug("Verify OK")
                else:
                    logger.error("Verify FAIL bad=%s reason=%s", bad, reason)
                    self.on_corruption(reason)
            except Exception:
                logger.exception("Background verify crashed")
            self._stop.wait(self.interval_s)

