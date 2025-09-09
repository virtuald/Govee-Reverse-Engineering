#!/usr/bin/python3
import asyncio
import logging
import time
from bleak import BleakClient
from utils import find_device, compute_xor, SEND_CHARACTERISTIC_UUID, RECV_CHARACTERISTIC_UUID
from pprint import pprint
import codecs
import sqlite3

## Configuration
DEVICE_NAME = "GVH508668B9"  # the name of the device we want to pair with
AUTH_KEY = "5d0f273ef04b9f4f"  # Obtain this using pair.py

MSG_TURN_ON = "3301ff00000000000000000000000000000000cd"
MSG_TURN_OFF = "3301f000000000000000000000000000000000c2"

devices = {
  'GVH508668B9' : '5d0f273ef04b9f4f',
}

commands = {
  'MSG_SND_PWR_DATA'  : "aa000000000000000000000000000000000000aa",
  'MSG_GET_FWARE_VER' : "aa060000000000000000000000000000000000ac",
  'MSG_GET_HWARE_VER' : "aa070300000000000000000000000000000000ae"
}

logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)-15s %(levelname)s: %(message)s",
    )
logger = logging.getLogger(__name__)
# logger.level = logging.DEBUG

db = sqlite3.connect('H5086_CN.db')

async def main():
  logger.info(f"Searching for device {DEVICE_NAME}")
  device, adv_data = await find_device(DEVICE_NAME)
  #logger.info(f"Adv Data: {adv_data}")
  if device is None:
    logger.error(f"Could not find a device!")
    return

  logger.info(f"Connecting...")

  # Connect 
  async with BleakClient(device.address) as client:
    logger.info(f"Connected to {client.address}")
    
    # events to control execution flow
    on_auth_ready = asyncio.Event()

    async def handle_notification(c, data):
      logger.debug(f"Raw data: {data}")
      if data[0] == 0x33 and data[1] == 0xB2:
        on_auth_ready.set()
      elif (data.hex()[0:4] == "aa06"):
        fwver = codecs.decode(data.hex()[4:18], "hex").decode('utf-8')
        logger.info(f"Firmware version: {fwver}")
        on_get_data_ready.set()
      elif (data.hex()[0:4] == "aa07"):
        hwver = codecs.decode(data.hex()[6:20], "hex").decode('utf-8')
        logger.info(f"Hardware version: {hwver}")
        on_get_data_ready.set()
      elif (data.hex()[0:4] != "ee19"):
        # It appears that commands which return data are echoed prior to the data being sent. -CN
        cmd = data.hex()[0:4]
        logger.info(f"Discarding packet: {cmd}")
      else:
        powerData = {
          "mac"         : client.address,
          "timestamp"   : time.time(),
          "runtime"     : int(data.hex()[4:10],16),
          "kwh"         : int(data.hex()[10:16],16)/10000,
          "e"           : int(data.hex()[16:20],16)/100,
          "i"           : int(data.hex()[20:24],16)/100,
          "p"           : int(data.hex()[26:30],16)/100,
          "pf"          : int(data.hex()[30:32],16)
        }
        logger.info(f"Current power data:")
        pprint(powerData, indent=4, sort_dicts=False)
        c = db.cursor()
        c.execute('INSERT INTO data (mac, timestamp, runtime, kwh, e, i, p, pf) VALUES (:mac, :timestamp, :runtime, :kwh, :e, :i, :p, :pf);', powerData)
        db.commit()
        on_get_data_ready.set()

    await client.start_notify(RECV_CHARACTERISTIC_UUID, handle_notification)
    
    await authenticate(client, AUTH_KEY)
    await on_auth_ready.wait()

    # Loop through the commands and execute each one.
    for key, value in commands.items():
      on_get_data_ready = asyncio.Event()
      logger.info(f"Executing {key}.")
      await get_data(client, value)
      await on_get_data_ready.wait()

    await client.stop_notify(RECV_CHARACTERISTIC_UUID)

    c = db.cursor()
    c.execute('SELECT * FROM data;')
    r = c.fetchall()
    for row in r:
        print(row)
    db.close()

    logger.info("Finished")

async def authenticate(client, auth_key):
  logger.info("Authenticating")
  # Create the message
  ba = bytearray([0x33, 0xB2]) + bytearray.fromhex(auth_key).ljust(17, b'\0')
  ba.append(compute_xor(ba))  
  logger.debug(f"SEND {ba.hex()}")
  await client.write_gatt_char(SEND_CHARACTERISTIC_UUID, ba)

async def get_data(c, cmd):
  logger.info(f"Retrieving data.")
  # Send the command
  ba = bytearray.fromhex(cmd)
  logger.debug(f"SEND {ba.hex()}")
  await c.write_gatt_char(SEND_CHARACTERISTIC_UUID, ba)
  logger.info(f"Done retrieving data.")

asyncio.run(main())
