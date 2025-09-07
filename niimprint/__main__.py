import logging
import platform
import re

import click
from PIL import Image

from niimprint.printer import PrinterClient
from niimprint.transport import get_transport


@click.command("print")
@click.option(
    "-m",
    "--model",
    type=click.Choice(["b1", "b18", "b21", "d11", "d110"], False),
    default="b21",
    show_default=True,
    help="Niimbot printer model",
)
@click.option(
    "-c",
    "--conn",
    type=click.Choice(["usb", "bluetooth", "ble"]),
    default="usb",
    show_default=True,
    help="Connection type",
)
@click.option(
    "-a",
    "--addr",
    help="Bluetooth/BLE MAC address OR serial device path",
)
@click.option(
    "-d",
    "--density",
    type=click.IntRange(1, 5),
    default=5,
    show_default=True,
    help="Print density",
)
@click.option(
    "-r",
    "--rotate",
    type=click.Choice(["0", "90", "180", "270"]),
    default="0",
    show_default=True,
    help="Image rotation (clockwise)",
)
@click.option(
    "-i",
    "--image",
    type=click.Path(exists=True),
    required=True,
    help="Image path",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "-b",
    "--batch-size",
    type=click.IntRange(1, 50),
    default=10,
    show_default=True,
    help="Number of packets to batch together for better performance",
)
def print_cmd(model, conn, addr, density, rotate, image, verbose, batch_size):
    logging.basicConfig(
        level="DEBUG" if verbose else "INFO",
        format="%(asctime)s.%(msecs)03d | %(levelname)s | %(module)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%H:%M:%S",
    )

    if conn == "bluetooth":
        assert addr is not None, "--addr argument required for bluetooth connection"
        addr = addr.upper()
        assert re.fullmatch(r"([0-9A-F]{2}:){5}([0-9A-F]{2})", addr), "Bad MAC address"

        # Use OSX-specific transport on macOS, fallback to Linux transport otherwise
        if platform.system() == "Darwin":
            try:
                transport = get_transport("bluetooth_osx", address=addr)
            except ImportError as e:
                if "PyObjC IOBluetooth framework not available" in str(e):
                    logging.warning(
                        "PyObjC IOBluetooth not available, falling back to standard Bluetooth transport"
                    )
                    transport = get_transport("bluetooth", address=addr)
                else:
                    raise
        else:
            transport = get_transport("bluetooth", address=addr)
    elif conn == "ble":
        assert addr is not None, "--addr argument required for BLE connection"
        addr = addr.upper()
        # BLE addresses can be MAC format or UUID format (especially on macOS)
        is_mac = re.fullmatch(r"([0-9A-F]{2}:){5}([0-9A-F]{2})", addr)
        is_uuid = re.fullmatch(
            r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", addr
        )
        assert is_mac or is_uuid, (
            "Bad BLE address format (expected MAC address or UUID)"
        )
        transport = get_transport("ble", address=addr)
    elif conn == "usb":
        port = addr if addr is not None else "auto"
        transport = get_transport("serial", port=port)

    if model in ("b1", "b18", "b21"):
        max_width_px = 384
    if model in ("d11", "d110"):
        max_width_px = 96

    if model in ("b18", "d11", "d110") and density > 3:
        logging.warning(f"{model.upper()} only supports density up to 3")
        density = 3

    image = Image.open(image)
    if rotate != "0":
        # PIL library rotates counter clockwise, so we need to multiply by -1
        image = image.rotate(-int(rotate), expand=True)
    if image.width > max_width_px:
        raise ValueError(
            f"Image width too big for {model.upper()}. Maximum width is {max_width_px} "
            f"pixels but the image width is {image.width} pixels"
        )

    printer = PrinterClient(transport)
    printer.print_image(image, density=density, batch_size=batch_size)


if __name__ == "__main__":
    print_cmd()
