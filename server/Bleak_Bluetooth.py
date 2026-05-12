# pip install bleak
import asyncio
from bleak import BleakScanner
from datetime import datetime
from db import create_user
import sqlite3

async def scan_bluetooth_devices():
    print("Scanning for bluetooth devices...")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        devices = await BleakScanner.discover()

        print(f"\nScan completed at {scan_time}")
        print(f"Found {len(devices)} devices:\n")

        for device in devices:
            print(f"Device Name: {device.name}")
            if device.address is not None:
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()
                cursor.execute(f"SELECT cook_name, cook_address, expirence FROM cook WHERE expirence = ?", ("expert",))
                cook = cursor.fetchone()
                if cook is None:
                    create_user("str(device.name)", str(device.address), "expert", conn)
                else:
                    return cook

            print(f"MAC Address: {device.address}")

        return False

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False


async def main():
    print("Starting Bluetooth scan...")
    c = await scan_bluetooth_devices()
    print(c)

if __name__ == "__main__":
    # Run the async function
    asyncio.run(main())
