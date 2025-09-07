#!/usr/bin/env python3
"""
BLE Device Scanner for NIIMBOT Printers

This script helps you discover NIIMBOT printers and their BLE addresses/UUIDs.
Run this script to find the correct address to use with the -a parameter.

Usage:
    uv run python scan_ble_devices.py [--timeout SECONDS] [--show-all]

Examples:
    uv run python scan_ble_devices.py                    # Scan for 10 seconds, show NIIMBOT printers only
    uv run python scan_ble_devices.py --timeout 5        # Scan for 5 seconds
    uv run python scan_ble_devices.py --show-all         # Show all BLE devices found
"""

import argparse
import asyncio
import sys
from typing import List, Dict, Any

try:
    from bleak import BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False


async def scan_ble_devices(timeout: float = 10.0, show_all: bool = False) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Scan for BLE devices and categorize them.
    
    Args:
        timeout: Scan timeout in seconds
        show_all: Whether to return all devices or just NIIMBOT printers
    
    Returns:
        Tuple of (niimbot_devices, other_devices)
    """
    print(f"🔍 Scanning for BLE devices (timeout: {timeout}s)...")
    
    found_devices = {}
    
    def detection_callback(device, advertisement_data):
        found_devices[device.address] = {
            'address': device.address,
            'name': device.name or 'Unknown',
            'rssi': advertisement_data.rssi
        }
    
    # Use callback-based scanning to get RSSI data reliably
    scanner = BleakScanner(detection_callback=detection_callback)
    
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    
    niimbot_devices = []
    other_devices = []
    
    for device_info in found_devices.values():
        # Check if this looks like a NIIMBOT printer
        name = device_info['name']
        if any(keyword in name.upper() for keyword in ['NIIMBOT', 'D110', 'D11', 'B21', 'B18', 'B1']):
            niimbot_devices.append(device_info)
        else:
            other_devices.append(device_info)
    
    # Sort by signal strength (RSSI, higher is better)
    niimbot_devices.sort(key=lambda x: x['rssi'], reverse=True)
    other_devices.sort(key=lambda x: x['rssi'], reverse=True)
    
    return niimbot_devices, other_devices


def main():
    parser = argparse.ArgumentParser(
        description="Scan for NIIMBOT BLE printers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--timeout', '-t',
        type=float,
        default=10.0,
        help='Scan timeout in seconds (default: 10.0)'
    )
    parser.add_argument(
        '--show-all', '-a',
        action='store_true',
        help='Show all BLE devices, not just NIIMBOT printers'
    )
    
    args = parser.parse_args()
    
    if not BLEAK_AVAILABLE:
        print("❌ Error: Bleak library not available.")
        print("Install it with: uv sync")
        sys.exit(1)
    
    print("=== NIIMBOT BLE Device Scanner ===")
    
    try:
        niimbot_devices, other_devices = asyncio.run(
            scan_ble_devices(timeout=args.timeout, show_all=args.show_all)
        )
        
        if niimbot_devices:
            print(f"\n🖨️  Found {len(niimbot_devices)} NIIMBOT printer(s):")
            print("┌─────────────────────────────────────────┬──────────────────┬──────┐")
            print("│ Address/UUID                            │ Name             │ RSSI │")
            print("├─────────────────────────────────────────┼──────────────────┼──────┤")
            for device in niimbot_devices:
                name = device['name'][:16].ljust(16) if len(device['name']) <= 16 else device['name'][:13] + "..."
                print(f"│ {device['address']:<39} │ {name:<16} │ {device['rssi']:>4} │")
            print("└─────────────────────────────────────────┴──────────────────┴──────┘")
            
            print("\n💡 Usage:")
            best_device = niimbot_devices[0]
            print(f"   uv run python -m niimprint -m d110 -c ble -a {best_device['address']} -i your_image.png")
        else:
            print("\n❌ No NIIMBOT printers found")
            print("   • Make sure your printer is turned on")
            print("   • Check that the printer is in pairing/discoverable mode")
            print("   • Try increasing the scan timeout with --timeout 20")
        
        if args.show_all and other_devices:
            print(f"\n📱 Other BLE devices found ({len(other_devices)}):")
            print("┌─────────────────────────────────────────┬──────────────────┬──────┐")
            print("│ Address/UUID                            │ Name             │ RSSI │")
            print("├─────────────────────────────────────────┼──────────────────┼──────┤")
            for device in other_devices[:15]:  # Show first 15
                name = device['name'][:16].ljust(16) if len(device['name']) <= 16 else device['name'][:13] + "..."
                print(f"│ {device['address']:<39} │ {name:<16} │ {device['rssi']:>4} │")
            if len(other_devices) > 15:
                print(f"│ ... and {len(other_devices) - 15} more devices          │                  │      │")
            print("└─────────────────────────────────────────┴──────────────────┴──────┘")
        
        print(f"\n📊 Scan completed: {len(niimbot_devices)} NIIMBOT printer(s), {len(other_devices)} other device(s)")
        
    except Exception as e:
        print(f"❌ Error during BLE scan: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
