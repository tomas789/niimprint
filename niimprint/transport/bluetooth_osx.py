"""Bluetooth transport for Niimprint printers (macOS)."""

import platform
import time

from .base import BaseTransport

# OSX-specific imports
if platform.system() == "Darwin":
    try:
        import objc
        from Foundation import NSDate, NSDefaultRunLoopMode, NSObject, NSRunLoop, NSData
        from IOBluetooth import IOBluetoothDevice
        OSX_BLUETOOTH_AVAILABLE = True
    except ImportError:
        OSX_BLUETOOTH_AVAILABLE = False
else:
    OSX_BLUETOOTH_AVAILABLE = False


class RFCOMMChannelDelegate(NSObject):
    """Delegate class to handle RFCOMM channel events"""
    
    def init(self):
        self = objc.super(RFCOMMChannelDelegate, self).init()
        if self is None:
            return None
        self.transport = None
        self.channel = None
        return self
    
    def rfcommChannelOpenComplete_status_(self, rfcommChannel, error):
        """Called when RFCOMM channel is opened"""
        if error == 0:  # kIOReturnSuccess
            self.channel = rfcommChannel
            print("RFCOMM channel opened successfully")
        else:
            print(f"RFCOMM channel open failed with error: {error}")
    
    def rfcommChannelData_data_length_(self, rfcommChannel, data, length):
        """Called when data is received on RFCOMM channel"""
        if self.transport and data:
            # Convert NSData to bytes and add to buffer
            if hasattr(data, 'bytes'):
                # NSData object
                bytes_data = bytes(data.bytes()[:length])
            else:
                # Already bytes
                bytes_data = data[:length] if isinstance(data, (bytes, bytearray)) else bytes(data)
            self.transport._read_buffer.extend(bytes_data)
    
    def rfcommChannelClosed_(self, rfcommChannel):
        """Called when RFCOMM channel is closed"""
        print("RFCOMM channel closed")
        if self.transport:
            self.transport._connected = False


class BluetoothOSXTransport(BaseTransport):
    """
    macOS-specific Bluetooth transport using PyObjC and IOBluetooth framework.
    This transport uses RFCOMM (classic Bluetooth) similar to the Linux implementation.
    """
    
    def __init__(self, address: str):
        if not OSX_BLUETOOTH_AVAILABLE:
            raise ImportError(
                "PyObjC IOBluetooth framework not available. "
                "Install with: pip install pyobjc-framework-IOBluetooth"
            )
        
        if platform.system() != "Darwin":
            raise RuntimeError("BluetoothOSXTransport can only be used on macOS")
            
        # Remove colons for IOBluetooth
        self.address = address.replace(":", "").upper()
        self.device = None
        self.channel = None
        self.delegate = None
        self._connected = False
        self._read_buffer = bytearray()
        self._connect()
    
    def _connect(self):
        """Connect to the Bluetooth device using RFCOMM"""
        # Find the device by address
        self.device = IOBluetoothDevice.deviceWithAddressString_(self.address)
        if not self.device:
            raise RuntimeError(
                f"Could not find Bluetooth device with address {self.address}"
            )
        
        # Create delegate for handling RFCOMM events
        self.delegate = RFCOMMChannelDelegate.alloc().init()
        self.delegate.transport = self
        
        # Check if device is paired and connected first
        if not self.device.isPaired():
            raise RuntimeError(
                f"Bluetooth device {self.address} is not paired. "
                "Please pair the device first using System Preferences > Bluetooth."
            )
        
        if not self.device.isConnected():
            # Try to connect the device first
            connect_result = self.device.openConnection()
            if connect_result != 0:  # kIOReturnSuccess
                # Extract error code if result is a tuple
                error_code = connect_result[0] if isinstance(connect_result, tuple) else connect_result
                error_msg = self._get_bluetooth_error_message(error_code)
                raise RuntimeError(
                    f"Failed to connect to Bluetooth device {self.address}: {error_msg}. "
                    "Make sure the device is turned on and in range."
                )
        
        # Open RFCOMM channel synchronously (channel 1, similar to Linux implementation)
        channel_ref = objc.nil
        result = self.device.openRFCOMMChannelSync_withChannelID_delegate_(
            channel_ref, 1, self.delegate
        )
        
        # Extract error code if result is a tuple, otherwise use result directly
        error_code = result[0] if isinstance(result, tuple) else result
        
        if error_code != 0:  # kIOReturnSuccess is 0
            error_msg = self._get_bluetooth_error_message(error_code)
            raise RuntimeError(f"Failed to open RFCOMM channel: {error_msg}")
        
        # Wait a moment for the channel to be established
        timeout = 5.0
        start_time = time.time()
        while not self.delegate.channel and (time.time() - start_time) < timeout:
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )
        
        self.channel = self.delegate.channel
        if not self.channel:
            raise RuntimeError("Failed to get RFCOMM channel reference")
        
        self._connected = True
        print(f"Connected to Bluetooth device {self.address}")
    
    def _get_bluetooth_error_message(self, error_code):
        """Convert IOKit error codes to human-readable messages"""
        error_messages = {
            -536870212: "Device not found or not available",
            -536870208: "Device busy or already in use", 
            -536870207: "Connection refused",
            -536870186: "Connection timeout",
            -536870174: "Device not paired",
            -536870173: "Authentication failed",
        }
        return error_messages.get(error_code, f"Unknown error code: {error_code}")
    
    def read(self, length: int) -> bytes:
        """Read data from the Bluetooth connection"""
        if not self._connected:
            raise RuntimeError("Not connected to Bluetooth device")
        
        # Wait for any data to be available in buffer
        timeout = 0.5  # Reduced timeout to 0.5 seconds
        start_time = time.time()
        
        while len(self._read_buffer) == 0 and (time.time() - start_time) < timeout:
            # Process run loop to handle incoming data
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode, 
                NSDate.dateWithTimeIntervalSinceNow_(0.01)  # Smaller intervals
            )
        
        if len(self._read_buffer) == 0:
            raise TimeoutError("No data received within timeout")
        
        # Return whatever data is available, up to the requested length
        actual_length = min(length, len(self._read_buffer))
        data = bytes(self._read_buffer[:actual_length])
        del self._read_buffer[:actual_length]
        
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        print(f"[{timestamp}] read {len(data)} bytes: {data}")
        return data
    
    def write(self, data: bytes) -> int:
        """Write data to the Bluetooth connection"""
        if not self._connected:
            raise RuntimeError("Not connected to Bluetooth device")
        
        if not self.channel:
            raise RuntimeError("RFCOMM channel not available")
        
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        print(f"[{timestamp}] write {len(data)} bytes: {data}")
        
        # Convert bytes to NSData
        ns_data = NSData.dataWithBytes_length_(data, len(data))
        
        # Write data to RFCOMM channel
        result = self.channel.writeSync_length_(ns_data, len(data))
        
        if result != 0:  # kIOReturnSuccess
            raise RuntimeError(f"Failed to write data: {result}")
        
        return len(data)
    
    def close(self):
        """Close the Bluetooth connection"""
        if self.channel:
            self.channel.closeChannel()
            self.channel = None
        self._connected = False
        print("Bluetooth connection closed")
    
    def __del__(self):
        """Cleanup when transport is destroyed"""
        self.close()
