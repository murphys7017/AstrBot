"""Small asynchronous client for the isolated NeuroBrain WebSocket service."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any

from astrbot.api import logger


class NeuroBrainReadOnlyAPI:
    """Read-only in-process view exposed to other AstrBot plugins."""

    def __init__(self, bridge: NeuroBrainBridge) -> None:
        self._bridge = bridge

    def get_state(self, state_key: str | None = None) -> dict[str, Any] | None:
        """Return a detached cached snapshot without advancing NeuroBrain."""

        return self._bridge.get_cached_state(state_key)

    def list_states(self) -> list[dict[str, Any]]:
        """Return all cached snapshots as detached dictionaries."""

        return self._bridge.list_cached_states()

    def is_ready(self) -> bool:
        return self._bridge.is_ready

    async def fetch_state(self, state_key: str) -> dict[str, Any] | None:
        """Query the service when the local cache does not contain a state."""

        return await self._bridge.fetch_state(state_key)

    async def wait_for_persona_result(
        self,
        persona_result_id: str,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any] | None:
        """Wait for AstrBot's update for one result, then return its snapshot."""

        return await self._bridge.wait_for_persona_result(
            persona_result_id,
            timeout_seconds=timeout_seconds,
        )


class NeuroBrainBridge:
    """Maintain one writer connection and a local read-only state cache."""

    def __init__(
        self,
        *,
        url: str,
        token: str = "",
        request_timeout_seconds: float = 2.0,
        connect_timeout_seconds: float = 5.0,
        client_id: str = "astrbot",
    ) -> None:
        self.url = url.strip()
        self.token = token
        self.request_timeout_seconds = max(0.1, float(request_timeout_seconds))
        self.connect_timeout_seconds = max(0.1, float(connect_timeout_seconds))
        self.client_id = client_id.strip() or "astrbot"
        self._websocket: Any | None = None
        self._reader_task: asyncio.Task[Any] | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._persona_result_snapshots: OrderedDict[
            str, asyncio.Future[dict[str, Any] | None]
        ] = OrderedDict()
        self._closed = False
        self._ready = asyncio.Event()
        self.readonly_api = NeuroBrainReadOnlyAPI(self)

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._websocket is not None

    async def start(self) -> None:
        self._closed = False
        await self._ensure_connected()

    async def close(self) -> None:
        self._closed = True
        reader = self._reader_task
        self._reader_task = None
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        websocket = self._websocket
        self._websocket = None
        self._ready.clear()
        if websocket is not None:
            await websocket.close()
        self._fail_pending(RuntimeError("NeuroBrain bridge is closed"))
        for future in self._persona_result_snapshots.values():
            if not future.done():
                future.set_result(None)
        self._persona_result_snapshots.clear()

    def get_cached_state(self, state_key: str | None = None) -> dict[str, Any] | None:
        if state_key is None:
            if len(self._latest) != 1:
                return None
            state_key = next(iter(self._latest))
        snapshot = self._latest.get(state_key)
        return copy.deepcopy(snapshot) if snapshot is not None else None

    def list_cached_states(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self._latest[key]) for key in sorted(self._latest)]

    def register_persona_result(self, persona_result_id: str) -> None:
        key = persona_result_id.strip()
        if not key:
            return
        future = self._persona_result_snapshots.get(key)
        if future is None or future.done():
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        self._trim_persona_result_snapshots()

    def complete_persona_result(
        self,
        persona_result_id: str,
        response: Mapping[str, Any] | None,
    ) -> None:
        key = persona_result_id.strip()
        if not key:
            return
        future = self._persona_result_snapshots.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        if not future.done():
            future.set_result(copy.deepcopy(dict(response)) if response is not None else None)
        self._trim_persona_result_snapshots()

    async def wait_for_persona_result(
        self,
        persona_result_id: str,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any] | None:
        key = persona_result_id.strip()
        if not key:
            return None
        future = self._persona_result_snapshots.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._persona_result_snapshots[key] = future
        self._persona_result_snapshots.move_to_end(key)
        self._trim_persona_result_snapshots()
        try:
            response = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(0.0, float(timeout_seconds)),
            )
        except asyncio.TimeoutError:
            return None
        if not isinstance(response, Mapping):
            return None
        snapshot = response.get("snapshot")
        return copy.deepcopy(dict(snapshot)) if isinstance(snapshot, Mapping) else None

    def _trim_persona_result_snapshots(self) -> None:
        while len(self._persona_result_snapshots) > 4096:
            _, future = self._persona_result_snapshots.popitem(last=False)
            if not future.done():
                future.set_result(None)

    async def _ensure_connected(self) -> None:
        if self._closed:
            raise RuntimeError("NeuroBrain bridge is closed")
        if self.is_ready:
            return
        async with self._connect_lock:
            if self.is_ready:
                return
            if not self.url:
                raise RuntimeError("NeuroBrain WebSocket URL is empty")
            try:
                import websockets

                websocket = await asyncio.wait_for(
                    websockets.connect(
                        self.url,
                        ping_interval=20,
                        ping_timeout=20,
                        max_size=2 * 1024 * 1024,
                    ),
                    timeout=self.connect_timeout_seconds,
                )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "hello",
                            "protocol_version": "neurobrain-ws-v1",
                            "role": "writer",
                            "token": self.token,
                            "client_id": self.client_id,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                raw = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=self.connect_timeout_seconds,
                )
                response = json.loads(raw)
                if (
                    not isinstance(response, Mapping)
                    or response.get("type") != "hello_ack"
                ):
                    await websocket.close()
                    raise RuntimeError(
                        str(
                            response.get("message")
                            if isinstance(response, Mapping)
                            else "invalid handshake"
                        )
                    )
                states = response.get("states")
                if not isinstance(states, list):
                    await websocket.close()
                    raise RuntimeError("invalid handshake state list")
                self._websocket = websocket
                self._ready.set()
                self._latest.clear()
                for state in states:
                    self._cache_state(state)
                self._reader_task = asyncio.create_task(
                    self._reader_loop(websocket),
                    name="neurobrain.bridge.reader",
                )
                await self._request(
                    {"type": "subscribe", "state_key": "*"},
                    retry=False,
                )
            except Exception:
                self._ready.clear()
                self._websocket = None
                raise

    def _cache_state(self, snapshot: Any) -> None:
        if not isinstance(snapshot, Mapping):
            return
        state_key = snapshot.get("state_key")
        if isinstance(state_key, str) and state_key.strip():
            self._latest[state_key] = copy.deepcopy(dict(snapshot))

    def _fail_pending(self, error: BaseException) -> None:
        pending = tuple(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)

    async def _reader_loop(self, websocket: Any) -> None:
        try:
            async for raw in websocket:
                payload = json.loads(raw)
                if not isinstance(payload, Mapping):
                    continue
                if payload.get("type") == "state":
                    self._cache_state(payload.get("snapshot"))
                elif payload.get("type") == "state_reset":
                    state_key = payload.get("state_key")
                    if isinstance(state_key, str) and state_key.strip():
                        self._latest.pop(state_key, None)
                request_id = payload.get("request_id")
                if isinstance(request_id, str):
                    future = self._pending.pop(request_id, None)
                    if future is not None and not future.done():
                        if payload.get("type") == "error":
                            future.set_exception(
                                RuntimeError(
                                    str(
                                        payload.get("message")
                                        or "NeuroBrain request failed"
                                    )
                                )
                            )
                        else:
                            future.set_result(dict(payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("NeuroBrain WebSocket reader stopped: %s", exc)
        finally:
            if self._websocket is websocket:
                self._websocket = None
                self._ready.clear()
            self._fail_pending(RuntimeError("NeuroBrain WebSocket disconnected"))

    async def _request(
        self,
        payload: Mapping[str, Any],
        *,
        retry: bool = True,
    ) -> dict[str, Any]:
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                await self._ensure_connected()
                websocket = self._websocket
                if websocket is None:
                    raise RuntimeError("NeuroBrain WebSocket is not connected")
                request_id = uuid.uuid4().hex
                request = {**payload, "request_id": request_id}
                future: asyncio.Future[dict[str, Any]] = (
                    asyncio.get_running_loop().create_future()
                )
                self._pending[request_id] = future
                async with self._send_lock:
                    await websocket.send(
                        json.dumps(
                            request,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                return await asyncio.wait_for(
                    future,
                    timeout=self.request_timeout_seconds,
                )
            except Exception:
                if attempt + 1 >= attempts:
                    raise
                await self._disconnect_for_retry()
        raise RuntimeError("NeuroBrain request failed")

    async def _disconnect_for_retry(self) -> None:
        websocket = self._websocket
        self._websocket = None
        self._ready.clear()
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass
        self._fail_pending(RuntimeError("retrying NeuroBrain request"))

    async def submit_stimulus(
        self,
        *,
        state_key: str,
        event_id: str,
        segments: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        response = await self._request(
            {
                "type": "stimulus",
                "state_key": state_key,
                "event_id": event_id,
                "segments": [dict(segment) for segment in segments],
            }
        )
        self._cache_state(response.get("snapshot"))
        return response

    async def fetch_state(self, state_key: str) -> dict[str, Any] | None:
        response = await self._request({"type": "get_state", "state_key": state_key})
        snapshot = response.get("snapshot")
        if isinstance(snapshot, Mapping):
            self._cache_state(snapshot)
        else:
            self._latest.pop(state_key, None)
        return self.get_cached_state(state_key)
