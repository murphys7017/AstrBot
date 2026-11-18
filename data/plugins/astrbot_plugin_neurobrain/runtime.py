"""One model thread, an input queue, and an independently readable snapshot."""

from __future__ import annotations

from collections import deque
import copy
import math
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from astrbot.api import logger


class NeuroBrainRuntime:
    """Keep all model operations on one thread; readers never acquire its lock."""

    def __init__(self, checkpoint: str, *, device: str, delta_seconds: float):
        if not math.isfinite(delta_seconds) or delta_seconds <= 0:
            raise ValueError("delta_seconds must be finite and positive")
        self._checkpoint = checkpoint
        self._device = device
        self._delta_seconds = delta_seconds
        self._inputs: deque[tuple[str | None, dict[str, float]]] = deque()
        self._input_lock = threading.Lock()
        self._stop = threading.Event()
        self._initialized = threading.Event()
        self._snapshot: dict[str, Any] | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, name="neurobrain.model", daemon=True
        )

    def start(self) -> None:
        """Wait for initialization; call outside the AstrBot event loop."""
        self._thread.start()
        self._initialized.wait()
        if self._error is not None:
            raise RuntimeError("NeuroBrain initialization failed") from self._error

    def stop(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join()

    @property
    def is_running(self) -> bool:
        return (
            self._snapshot is not None
            and self._thread.is_alive()
            and not self._stop.is_set()
        )

    def submit_emotion(self, tendency: Mapping[str, int], *, turn_id: str | None = None) -> None:
        """Queue each admitted stimulus once in presentation order."""
        from neurobrain import convert_astrbot_tendency_to_stimulus

        if not self.is_running:
            raise RuntimeError("NeuroBrain is not running")
        stimulus = convert_astrbot_tendency_to_stimulus(tendency)
        with self._input_lock:
            if len(self._inputs) >= 256:
                raise RuntimeError("NeuroBrain pending emotion capacity exceeded")
            self._inputs.append((turn_id, stimulus))

    def cancel_pending(self, turn_id: str) -> None:
        with self._input_lock:
            self._inputs = deque(item for item in self._inputs if item[0] != turn_id)

    def get_state(self) -> dict[str, Any] | None:
        """Copy the last complete snapshot without touching the model."""
        return copy.deepcopy(self._snapshot)

    def _run(self) -> None:
        try:
            import torch
            from neurobrain import CURRENT_STIMULUS_DIMENSIONS, NeuroBrainSession

            device = self._device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            session = NeuroBrainSession.from_checkpoint(
                self._checkpoint, device=device, delta_seconds=self._delta_seconds
            )
            zero = dict.fromkeys(CURRENT_STIMULUS_DIMENSIONS, 0.0)
            revision = 0
            last_tendency: dict[str, int] = {}

            def advance(stimulus: dict[str, float]) -> None:
                nonlocal revision
                snapshot = session.update(stimulus).as_dict()
                revision += 1
                snapshot["revision"] = revision
                snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
                snapshot["last_tendency"] = dict(last_tendency)
                # Never mutate a published object. A read can keep the old one
                # while this thread performs the next inference.
                self._snapshot = snapshot

            advance(zero)
            self._initialized.set()
            logger.info("NeuroBrain model thread ready: device=%s", device)
            next_tick = monotonic() + self._delta_seconds
            while not self._stop.wait(max(0.0, next_tick - monotonic())):
                with self._input_lock:
                    stimulus = self._inputs.popleft()[1] if self._inputs else zero
                if stimulus is not zero:
                    from neurobrain import ASTRBOT_TENDENCY_DIMENSIONS

                    last_tendency = {
                        source: round(stimulus[target] * 10)
                        for source, target in ASTRBOT_TENDENCY_DIMENSIONS
                    }
                advance(stimulus)
                # Inputs do not reset the clock. Skip overdue wall-clock ticks
                # rather than spinning through catch-up inference.
                next_tick += self._delta_seconds
                now = monotonic()
                if next_tick <= now:
                    next_tick = now + self._delta_seconds
        except Exception as exc:
            self._error = exc
            logger.exception("NeuroBrain model thread stopped")
        finally:
            self._stop.set()
            self._initialized.set()
