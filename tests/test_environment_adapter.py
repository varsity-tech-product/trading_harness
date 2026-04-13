from __future__ import annotations

import unittest

from arena_agent.core.environment_adapter import EnvironmentAdapter


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = "Bad Request" if status_code == 400 else "Service Unavailable"

    def json(self) -> dict[str, object]:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class DummyHttpError(Exception):
    def __init__(self, response: DummyResponse) -> None:
        super().__init__(f"http {response.status_code}")
        self.response = response


class WriteFailureClient:
    def __init__(self, status_code: int, succeed_on_attempt: int | None = None) -> None:
        self.status_code = status_code
        self.succeed_on_attempt = succeed_on_attempt
        self.attempts = 0

    def trade_open(self, *args, **kwargs):
        self.attempts += 1
        if self.succeed_on_attempt is not None and self.attempts >= self.succeed_on_attempt:
            return {"ok": True}
        raise DummyHttpError(
            DummyResponse(
                self.status_code,
                payload={"message": "invalid order" if self.status_code == 400 else "temporary failure"},
            )
        )


class EnvironmentAdapterRetryTest(unittest.TestCase):
    def test_trade_write_does_not_retry_semantic_400(self) -> None:
        client = WriteFailureClient(status_code=400)
        adapter = EnvironmentAdapter(client=client, retry_attempts=3, retry_backoff_seconds=0)

        with self.assertRaisesRegex(RuntimeError, "trade_open failed: 400 invalid order"):
            adapter.trade_open(10, "short", 1.0)

        self.assertEqual(client.attempts, 1)

    def test_trade_write_retries_transient_503(self) -> None:
        client = WriteFailureClient(status_code=503, succeed_on_attempt=3)
        adapter = EnvironmentAdapter(client=client, retry_attempts=3, retry_backoff_seconds=0)

        response = adapter.trade_open(10, "short", 1.0)

        self.assertEqual(client.attempts, 3)
        self.assertEqual(response, {"ok": True})


if __name__ == "__main__":
    unittest.main()
