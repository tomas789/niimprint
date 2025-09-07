"""Bluetooth transport for Niimprint printers (Linux/standard)."""

import socket

from .base import BaseTransport


class BluetoothTransport(BaseTransport):
    """Standard Bluetooth RFCOMM transport implementation for Linux."""
    
    def __init__(self, address: str):
        self._sock = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_STREAM,
            socket.BTPROTO_RFCOMM,
        )
        self._sock.connect((address, 1))

    def read(self, length: int) -> bytes:
        content = self._sock.recv(length)
        print(f"read {length} bytes: {content}")
        return content

    def write(self, data: bytes) -> int:
        print(f"write {len(data)} bytes: {data}")
        return self._sock.send(data)
