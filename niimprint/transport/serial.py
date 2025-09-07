"""Serial transport for Niimprint printers."""

import serial
from serial.tools.list_ports import comports as list_comports

from .base import BaseTransport


class SerialTransport(BaseTransport):
    """Serial/USB transport implementation."""
    
    def __init__(self, port: str = "auto"):
        port = port if port != "auto" else self._detect_port()
        self._serial = serial.Serial(port=port, baudrate=115200, timeout=0.5)

    def _detect_port(self):
        all_ports = list(list_comports())
        if len(all_ports) == 0:
            raise RuntimeError("No serial ports detected")
        if len(all_ports) > 1:
            msg = "Too many serial ports, please select specific one:"
            for port, desc, hwid in all_ports:
                msg += f"\n- {port} : {desc} [{hwid}]"
            raise RuntimeError(msg)
        return all_ports[0][0]

    def read(self, length: int) -> bytes:
        return self._serial.read(length)

    def write(self, data: bytes) -> int:
        return self._serial.write(data)
