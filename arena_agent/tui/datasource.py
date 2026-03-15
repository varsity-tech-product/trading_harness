"""Direct runtime snapshot datasource for the terminal monitor."""

from __future__ import annotations

import copy
import json
import queue
import socket
import threading
import time
from typing import Any

from arena_agent.observability.runtime_monitor import build_empty_snapshot


class RuntimeStreamDataSource:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        reconnect_seconds: float = 1.0,
        connect_timeout_seconds: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.reconnect_seconds = max(0.1, reconnect_seconds)
        self.connect_timeout_seconds = max(0.1, connect_timeout_seconds)
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_snapshot = _with_connection(build_empty_snapshot(), status="disconnected")
        self._status_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="arena-monitor-datasource", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def poll_latest(self) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        return latest

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=self.connect_timeout_seconds) as conn:
                    conn.settimeout(1.0)
                    self._emit_status("connected")
                    buffer = b""
                    while not self._stop_event.is_set():
                        try:
                            chunk = conn.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise ConnectionError("runtime stream closed")
                        buffer += chunk
                        while b"\n" in buffer:
                            raw_line, buffer = buffer.split(b"\n", 1)
                            if not raw_line:
                                continue
                            payload = json.loads(raw_line.decode("utf-8"))
                            snapshot = _with_connection(payload, status="connected")
                            with self._status_lock:
                                self._last_snapshot = snapshot
                            self._queue.put(snapshot)
            except Exception as exc:
                self._emit_status("disconnected", error=str(exc))
                time.sleep(self.reconnect_seconds)

    def _emit_status(self, status: str, *, error: str | None = None) -> None:
        with self._status_lock:
            snapshot = copy.deepcopy(self._last_snapshot)
        snapshot = _with_connection(snapshot, status=status, error=error)
        with self._status_lock:
            self._last_snapshot = snapshot
        self._queue.put(snapshot)


def _with_connection(snapshot: dict[str, Any], *, status: str, error: str | None = None) -> dict[str, Any]:
    snapshot = dict(snapshot)
    snapshot["connection"] = {
        "status": status,
        "host": snapshot.get("stream", {}).get("host"),
        "port": snapshot.get("stream", {}).get("port"),
        "error": error,
    }
    return snapshot
