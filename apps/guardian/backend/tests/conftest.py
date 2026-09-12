"""Hermetic backend tests: ignore developer credentials and block external sockets."""
import ipaddress
import os
import socket

import pytest


# Set these before test modules import config/db or construct a source client.
# setdefault would allow a developer's real credentials to leak into the suite.
os.environ.update({
    "PYTHON_DOTENV_DISABLED": "1",
    "MONGO_URL": "mongodb://127.0.0.1:1",
    "GUARDIAN_DB_NAME": "guardian_unit_tests",
    "GUARDIAN_API_KEY": "guardian-unit-test-key",
    "GUARDIAN_AUTH_MODE": "api_key",
    "GUARDIAN_CAPTURE_MODE": "langfuse",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "LANGFUSE_HOST": "https://example.invalid",
    "LANGFUSE_READ_API": "v2",
})


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Permit local event-loop sockets; accidental external I/O is a test failure."""
    original_connect = socket.socket.connect
    original_getaddrinfo = socket.getaddrinfo

    def is_local(host):
        if host in (None, "localhost", b"localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and not is_local(address[0]):
            raise RuntimeError("External network is disabled in backend unit tests")
        return original_connect(sock, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not is_local(host):
            raise RuntimeError("External DNS is disabled in backend unit tests")
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def explicit_mock_transactions(monkeypatch):
    """Mock-only semantics; tools/test_mongo_ledger.py proves real transactions.

    Production never detects or falls back to mocks. Only tests opt in, and a
    real Motor database still invokes the real transaction runner.
    """
    from guardian.ledger import ObservationLedger
    original = ObservationLedger.transaction

    async def unit_transaction(self, callback):
        if "_AsyncMongoMockDatabase__database" in vars(self.db):
            return await callback(None)
        return await original(self, callback)

    monkeypatch.setattr(ObservationLedger, "transaction", unit_transaction)
