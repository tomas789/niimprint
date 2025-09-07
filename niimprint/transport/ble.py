import asyncio
import logging
import threading
import time
from typing import Optional


from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

from .base import BaseTransport


class BLETransport(BaseTransport):
    """
    Bluetooth Low Energy transport for NIIMBOT printers using Bleak library.
    This transport works across Windows, macOS, and Linux platforms.
    """

    # NIIMBOT BLE service and characteristic UUIDs from documentation
    SERVICE_UUID = "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
    CHARACTERISTIC_UUID = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"

    @staticmethod
    async def scan_devices(timeout: float = 10.0):
        """Scan for available BLE devices and identify potential NIIMBOT printers"""
        print(f"Scanning for BLE devices (timeout: {timeout}s)...")
        devices = await BleakScanner.discover(timeout=timeout)

        niimbot_devices = []
        other_devices = []

        for device in devices:
            # Check if device name suggests it's a NIIMBOT printer
            name = device.name or "Unknown"
            is_niimbot = any(
                keyword in name.upper()
                for keyword in ["NIIM", "D110", "B21", "B1", "B18", "D11"]
            )

            device_info = {
                "address": device.address,
                "name": name,
                "rssi": getattr(device, "rssi", "N/A"),
            }

            if is_niimbot:
                niimbot_devices.append(device_info)
            else:
                other_devices.append(device_info)

        return niimbot_devices, other_devices

    @staticmethod
    def scan_devices_sync(timeout: float = 10.0):
        """Synchronous wrapper for device scanning"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(BLETransport.scan_devices(timeout))
        finally:
            loop.close()

    @staticmethod
    def convert_classic_to_ble_address(classic_address: str) -> str:
        """
        Convert classic Bluetooth address to potential BLE address.
        Based on documentation, D110 has:
        - Classic: 03:26:03:C3:F9:11
        - BLE: 26:03:03:C3:F9:11

        The pattern seems to be rotating the first 3 bytes.
        """
        parts = classic_address.upper().split(":")
        if len(parts) != 6:
            raise ValueError("Invalid MAC address format")

        # Try rotating first 3 bytes: AA:BB:CC:DD:EE:FF -> CC:AA:BB:DD:EE:FF
        rotated = [parts[2], parts[0], parts[1]] + parts[3:]
        return ":".join(rotated)

    def __init__(self, address: str):
        self.address = address.upper()
        self.client: Optional[BleakClient] = None
        self.characteristic: Optional[BleakGATTCharacteristic] = None
        self._read_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._connected = False

        # Start the asyncio event loop in a separate thread
        self._start_event_loop()

        # Connect to the device
        self._connect_sync()

    def _start_event_loop(self):
        """Start asyncio event loop in a separate thread"""

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

        # Wait for loop to be ready
        while self._loop is None:
            time.sleep(0.01)

    def _connect_sync(self):
        """Synchronously connect to the BLE device"""
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self._loop)
        future.result(timeout=30)  # 30 second timeout

    async def _connect_async(self):
        """Asynchronously connect to the BLE device"""
        logging.info(f"Connecting directly to BLE device: {self.address}")

        # Connect directly to the device using its address (no scanning needed)
        self.client = BleakClient(self.address)

        try:
            await self.client.connect()
            logging.info("Connected to BLE device")

            # Discover services and characteristics
            services = self.client.services
            service = services.get_service(self.SERVICE_UUID)

            if not service:
                raise RuntimeError(
                    f"Service {self.SERVICE_UUID} not found on device. "
                    "Make sure this is a compatible NIIMBOT printer."
                )

            self.characteristic = service.get_characteristic(self.CHARACTERISTIC_UUID)

            if not self.characteristic:
                raise RuntimeError(
                    f"Characteristic {self.CHARACTERISTIC_UUID} not found in service. "
                    "Make sure this is a compatible NIIMBOT printer."
                )

            # Subscribe to notifications
            await self.client.start_notify(
                self.characteristic, self._notification_handler
            )
            logging.info("Subscribed to BLE notifications")

            self._connected = True

        except Exception as e:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
            raise RuntimeError(f"Failed to connect to BLE device: {e}")

    def _notification_handler(
        self, characteristic: BleakGATTCharacteristic, data: bytearray
    ):
        """Handle incoming BLE notifications"""
        with self._buffer_lock:
            self._read_buffer.extend(data)

        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        logging.debug(
            f"[{timestamp}] BLE notification received {len(data)} bytes: {data}"
        )

    def read(self, length: int) -> bytes:
        """Read data from the BLE connection"""
        if not self._connected:
            raise RuntimeError("Not connected to BLE device")

        # Wait for data to be available
        timeout = 50.0  # 1 second timeout
        start_time = time.time()

        while True:
            with self._buffer_lock:
                if len(self._read_buffer) > 0:
                    # Return whatever data is available, up to the requested length
                    actual_length = min(length, len(self._read_buffer))
                    data = bytes(self._read_buffer[:actual_length])
                    del self._read_buffer[:actual_length]

                    timestamp = (
                        time.strftime("%H:%M:%S.")
                        + f"{int(time.time() * 1000) % 1000:03d}"
                    )
                    logging.debug(f"[{timestamp}] BLE read {len(data)} bytes: {data}")
                    return data

            if (time.time() - start_time) > timeout:
                raise TimeoutError("No data received within timeout")

            time.sleep(0.01)  # Small sleep to prevent busy waiting

    def write(self, data: bytes):
        """Write data to the BLE connection"""
        if not self._connected:
            raise RuntimeError("Not connected to BLE device")

        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        logging.debug(f"[{timestamp}] BLE write {len(data)} bytes: {data}")

        # Write data asynchronously
        future = asyncio.run_coroutine_threadsafe(self._write_async(data), self._loop)
        future.result(timeout=5.0)  # 5 second timeout

        return len(data)

    async def _write_async(self, data: bytes):
        """Asynchronously write data to the BLE characteristic"""
        if not self.client or not self.client.is_connected:
            raise RuntimeError("BLE client not connected")

        # Write without response (as specified in the documentation)
        await self.client.write_gatt_char(self.characteristic, data, response=False)

    def close(self):
        """Close the BLE connection"""
        if self._connected and self.client:
            # Disconnect asynchronously
            future = asyncio.run_coroutine_threadsafe(
                self.client.disconnect(), self._loop
            )
            try:
                future.result(timeout=5.0)
            except:
                pass  # Ignore errors during cleanup

            self._connected = False
            logging.info("BLE connection closed")

        # Stop the event loop
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def __del__(self):
        """Cleanup when transport is destroyed"""
        self.close()
