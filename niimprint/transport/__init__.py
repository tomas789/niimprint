"""Transport layer for Niimprint printers.

This module provides different transport implementations that can be dynamically
imported based on the connection type selected by the user.
"""

from .base import BaseTransport

__all__ = ["BaseTransport", "get_transport"]


def get_transport(transport_type: str, **kwargs):
    """Dynamically import and create a transport instance based on type.
    
    Args:
        transport_type: One of 'serial', 'bluetooth', 'bluetooth_osx', 'ble'
        **kwargs: Arguments to pass to the transport constructor
        
    Returns:
        Transport instance
        
    Raises:
        ImportError: If transport type is not supported or dependencies missing
        ValueError: If transport_type is unknown
    """
    if transport_type == "serial":
        from .serial import SerialTransport
        return SerialTransport(**kwargs)
    elif transport_type == "bluetooth":
        from .bluetooth import BluetoothTransport
        return BluetoothTransport(**kwargs)
    elif transport_type == "bluetooth_osx":
        from .bluetooth_osx import BluetoothOSXTransport
        return BluetoothOSXTransport(**kwargs)
    elif transport_type == "ble":
        from .ble import BLETransport
        return BLETransport(**kwargs)
    else:
        raise ValueError(f"Unknown transport type: {transport_type}")
