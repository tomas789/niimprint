import abc
import enum
import logging
import math
import platform
import socket
import struct
import time

import serial
from PIL import Image, ImageOps
from serial.tools.list_ports import comports as list_comports

from niimprint.packet import NiimbotPacket

# OSX-specific imports
if platform.system() == "Darwin":
    try:
        import objc
        from Foundation import NSDate, NSDefaultRunLoopMode, NSObject, NSRunLoop
        from IOBluetooth import IOBluetoothDevice

        OSX_BLUETOOTH_AVAILABLE = True
    except ImportError:
        OSX_BLUETOOTH_AVAILABLE = False
else:
    OSX_BLUETOOTH_AVAILABLE = False


class InfoEnum(enum.IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    LANGUAGETYPE = 6
    AUTOSHUTDOWNTIME = 7
    DEVICETYPE = 8
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12


class RequestCodeEnum(enum.IntEnum):
    GET_INFO = 64  # 0x40
    GET_RFID = 26  # 0x1A
    HEARTBEAT = 220  # 0xDC
    SET_LABEL_TYPE = 35  # 0x23
    SET_LABEL_DENSITY = 33  # 0x21
    START_PRINT = 1  # 0x01
    END_PRINT = 243  # 0xF3
    START_PAGE_PRINT = 3  # 0x03
    END_PAGE_PRINT = 227  # 0xE3
    ALLOW_PRINT_CLEAR = 32  # 0x20
    SET_DIMENSION = 19  # 0x13
    SET_QUANTITY = 21  # 0x15
    GET_PRINT_STATUS = 163  # 0xA3


def _packet_to_int(x):
    return int.from_bytes(x.data, "big")


class BaseTransport(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def read(self, length: int) -> bytes:
        raise NotImplementedError

    @abc.abstractmethod
    def write(self, data: bytes):
        raise NotImplementedError


class BluetoothTransport(BaseTransport):
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

    def write(self, data: bytes):
        print(f"write {len(data)} bytes: {data}")
        return self._sock.send(data)


class BluetoothOSXTransport(BaseTransport):
    """
    macOS-specific Bluetooth transport using PyObjC and IOBluetooth framework.
    This transport uses RFCOMM (classic Bluetooth) similar to the Linux implementation.
    """
    
    def __init__(self, address: str):
        if not OSX_BLUETOOTH_AVAILABLE:
            raise RuntimeError(
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
    
    def write(self, data: bytes):
        """Write data to the Bluetooth connection"""
        if not self._connected:
            raise RuntimeError("Not connected to Bluetooth device")
        
        if not self.channel:
            raise RuntimeError("RFCOMM channel not available")
        
        timestamp = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        print(f"[{timestamp}] write {len(data)} bytes: {data}")
        
        # Convert bytes to NSData
        from Foundation import NSData
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


class SerialTransport(BaseTransport):
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

    def write(self, data: bytes):
        return self._serial.write(data)


class PrinterClient:
    def __init__(self, transport):
        self._transport = transport
        self._packetbuf = bytearray()

    def print_image(self, image: Image, density: int = 3):
        self.set_label_density(density)
        self.set_label_type(1)
        self.start_print()
        # self.allow_print_clear()  # Something unsupported in protocol decoding (B21)
        self.start_page_print()
        self.set_dimension(image.height, image.width)
        # self.set_quantity(1)  # Same thing (B21)
        for pkt in self._encode_image(image):
            self._send(pkt)
        self.end_page_print()
        time.sleep(0.3)  # FIXME: Check get_print_status()
        while not self.end_print():
            time.sleep(0.1)

    def _encode_image(self, image: Image):
        img = ImageOps.invert(image.convert("L")).convert("1")
        for y in range(img.height):
            line_data = [img.getpixel((x, y)) for x in range(img.width)]
            line_data = "".join("0" if pix == 0 else "1" for pix in line_data)
            line_data = int(line_data, 2).to_bytes(math.ceil(img.width / 8), "big")
            counts = (0, 0, 0)  # It seems like you can always send zeros
            header = struct.pack(">H3BB", y, *counts, 1)
            pkt = NiimbotPacket(0x85, header + line_data)
            yield pkt

    def _recv(self):
        packets = []
        self._packetbuf.extend(self._transport.read(1024))
        while len(self._packetbuf) > 4:
            pkt_len = self._packetbuf[3] + 7
            if len(self._packetbuf) >= pkt_len:
                packet = NiimbotPacket.from_bytes(self._packetbuf[:pkt_len])
                self._log_buffer("recv", packet.to_bytes())
                packets.append(packet)
                del self._packetbuf[:pkt_len]
        return packets

    def _send(self, packet):
        self._transport.write(packet.to_bytes())

    def _log_buffer(self, prefix: str, buff: bytes):
        msg = ":".join(f"{i:#04x}"[-2:] for i in buff)
        logging.debug(f"{prefix}: {msg}")

    def _transceive(self, reqcode, data, respoffset=1):
        respcode = respoffset + reqcode
        packet = NiimbotPacket(reqcode, data)
        self._log_buffer("send", packet.to_bytes())
        self._send(packet)
        resp = None
        for _ in range(6):
            for packet in self._recv():
                if packet.type == 219:
                    raise ValueError
                elif packet.type == 0:
                    raise NotImplementedError
                elif packet.type == respcode:
                    resp = packet
            if resp:
                return resp
            time.sleep(0.1)
        return resp

    def get_info(self, key):
        if packet := self._transceive(RequestCodeEnum.GET_INFO, bytes((key,)), key):
            match key:
                case InfoEnum.DEVICESERIAL:
                    return packet.data.hex()
                case InfoEnum.SOFTVERSION:
                    return _packet_to_int(packet) / 100
                case InfoEnum.HARDVERSION:
                    return _packet_to_int(packet) / 100
                case _:
                    return _packet_to_int(packet)
        else:
            return None

    def get_rfid(self):
        packet = self._transceive(RequestCodeEnum.GET_RFID, b"\x01")
        data = packet.data

        if data[0] == 0:
            return None
        uuid = data[0:8].hex()
        idx = 8

        barcode_len = data[idx]
        idx += 1
        barcode = data[idx : idx + barcode_len].decode()

        idx += barcode_len
        serial_len = data[idx]
        idx += 1
        serial = data[idx : idx + serial_len].decode()

        idx += serial_len
        total_len, used_len, type_ = struct.unpack(">HHB", data[idx:])
        return {
            "uuid": uuid,
            "barcode": barcode,
            "serial": serial,
            "used_len": used_len,
            "total_len": total_len,
            "type": type_,
        }

    def heartbeat(self):
        packet = self._transceive(RequestCodeEnum.HEARTBEAT, b"\x01")
        closingstate = None
        powerlevel = None
        paperstate = None
        rfidreadstate = None

        match len(packet.data):
            case 20:
                paperstate = packet.data[18]
                rfidreadstate = packet.data[19]
            case 13:
                closingstate = packet.data[9]
                powerlevel = packet.data[10]
                paperstate = packet.data[11]
                rfidreadstate = packet.data[12]
            case 19:
                closingstate = packet.data[15]
                powerlevel = packet.data[16]
                paperstate = packet.data[17]
                rfidreadstate = packet.data[18]
            case 10:
                closingstate = packet.data[8]
                powerlevel = packet.data[9]
                rfidreadstate = packet.data[8]
            case 9:
                closingstate = packet.data[8]

        return {
            "closingstate": closingstate,
            "powerlevel": powerlevel,
            "paperstate": paperstate,
            "rfidreadstate": rfidreadstate,
        }

    def set_label_type(self, n):
        assert 1 <= n <= 3
        packet = self._transceive(RequestCodeEnum.SET_LABEL_TYPE, bytes((n,)), 16)
        return bool(packet.data[0])

    def set_label_density(self, n):
        assert 1 <= n <= 5  # B21 has 5 levels, not sure for D11
        packet = self._transceive(RequestCodeEnum.SET_LABEL_DENSITY, bytes((n,)), 16)
        return bool(packet.data[0])

    def start_print(self):
        packet = self._transceive(RequestCodeEnum.START_PRINT, b"\x01")
        return bool(packet.data[0])

    def end_print(self):
        packet = self._transceive(RequestCodeEnum.END_PRINT, b"\x01")
        return bool(packet.data[0])

    def start_page_print(self):
        packet = self._transceive(RequestCodeEnum.START_PAGE_PRINT, b"\x01")
        return bool(packet.data[0])

    def end_page_print(self):
        packet = self._transceive(RequestCodeEnum.END_PAGE_PRINT, b"\x01")
        return bool(packet.data[0])

    def allow_print_clear(self):
        packet = self._transceive(RequestCodeEnum.ALLOW_PRINT_CLEAR, b"\x01", 16)
        return bool(packet.data[0])

    def set_dimension(self, w, h):
        packet = self._transceive(
            RequestCodeEnum.SET_DIMENSION, struct.pack(">HH", w, h)
        )
        return bool(packet.data[0])

    def set_quantity(self, n):
        packet = self._transceive(RequestCodeEnum.SET_QUANTITY, struct.pack(">H", n))
        return bool(packet.data[0])

    def get_print_status(self):
        packet = self._transceive(RequestCodeEnum.GET_PRINT_STATUS, b"\x01", 16)
        page, progress1, progress2 = struct.unpack(">HBB", packet.data)
        return {"page": page, "progress1": progress1, "progress2": progress2}
