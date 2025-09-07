"""Bluetooth Low Energy (BLE) transport for Niimprint printers."""

import platform
import time

from .base import BaseTransport

# Try to import BLE libraries
try:
    from bleak import BleakClient, BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


class BLETransport(BaseTransport):
    """Bluetooth Low Energy transport implementation using bleak."""
    
    # Common GATT UUIDs for serial-like services
    UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"  # Nordic UART Service
    UART_TX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"       # TX Characteristic
    UART_RX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"       # RX Characteristic
    
    def __init__(self, address: str):
        if not BLEAK_AVAILABLE:
            raise ImportError(
                "Bleak library not available. Install with: pip install bleak"
            )
        
        self.address = address
        self.client = None
        self._connected = False
        self._read_buffer = bytearray()
        self._connect()
    
    def _connect(self):
        """Connect to the BLE device"""
        import asyncio
        
        async def _async_connect():
            self.client = BleakClient(self.address)
            
            try:
                await self.client.connect()
                self._connected = True
                print(f"Connected to BLE device {self.address}")
                
                # Set up notification handler for receiving data
                await self.client.start_notify(self.UART_RX_UUID, self._notification_handler)
                
            except Exception as e:
                raise RuntimeError(f"Failed to connect to BLE device {self.address}: {e}")
        
        # Run the async connection
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_async_connect())
        finally:
            # Don't close the loop, we'll need it for read/write operations
            pass
    
    def _notification_handler(self, sender, data):
        """Handle incoming BLE notifications"""
        self._read_buffer.extend(data)
    
    def read(self, length: int) -> bytes:
        """Read data from the BLE connection"""
        if not self._connected:
            raise RuntimeError("Not connected to BLE device")
        
        # Wait for data to be available in buffer
        timeout = 1.0
        start_time = time.time()
        
        while len(self._read_buffer) == 0 and (time.time() - start_time) < timeout:
            time.sleep(0.01)  # Small delay to allow notifications to arrive
        
        if len(self._read_buffer) == 0:
            raise TimeoutError("No data received within timeout")
        
        # Return whatever data is available, up to the requested length
        actual_length = min(length, len(self._read_buffer))
        data = bytes(self._read_buffer[:actual_length])
        del self._read_buffer[:actual_length]
        
        print(f"BLE read {len(data)} bytes: {data}")
        return data
    
    def write(self, data: bytes) -> int:
        """Write data to the BLE connection"""
        if not self._connected:
            raise RuntimeError("Not connected to BLE device")
        
        import asyncio
        
        async def _async_write():
            await self.client.write_gatt_char(self.UART_TX_UUID, data)
            return len(data)
        
        print(f"BLE write {len(data)} bytes: {data}")
        
        # Run the async write
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_async_write())
    
    def close(self):
        """Close the BLE connection"""
        if self.client and self._connected:
            import asyncio
            
            async def _async_close():
                await self.client.disconnect()
            
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_async_close())
            
            self._connected = False
            print("BLE connection closed")
    
    def __del__(self):
        """Cleanup when transport is destroyed"""
        self.close()
