"""Bluetooth transport for Niimprint printers (Linux/standard)."""

import socket
import errno

from .base import BaseTransport


class BluetoothTransport(BaseTransport):
    """Standard Bluetooth RFCOMM transport implementation for Linux."""
    
    def __init__(self, address: str):
        self._sock = socket.socket(
            socket.AF_BLUETOOTH,
            socket.SOCK_STREAM,
            socket.BTPROTO_RFCOMM,
        )
        try:
            self._sock.connect((address, 1))
        except OSError as e:
            if e.errno == errno.EHOSTDOWN:  # errno 112
                raise ConnectionError(
                    f"Cannot connect to Bluetooth device {address}. "
                    f"Please ensure the device is:\n"
                    f"1. Powered on and in range\n"
                    f"2. In pairing/discoverable mode\n"
                    f"3. Properly paired with this system using: bluetoothctl\n"
                    f"4. Not connected to another device\n"
                    f"5. Your Bluetooth adapter is up: sudo hciconfig hci0 up"
                ) from e
            elif e.errno == errno.ECONNREFUSED:  # errno 111
                raise ConnectionError(
                    f"Connection refused by device {address}. "
                    f"The device may not be in pairing mode or may be busy."
                ) from e
            else:
                raise

    def read(self, length: int) -> bytes:
        content = self._sock.recv(length)
        print(f"read {length} bytes: {content!r}")
        return content

    def write(self, data: bytes) -> int:
        print(f"write {len(data)} bytes: {data!r}")
        return self._sock.send(data)
