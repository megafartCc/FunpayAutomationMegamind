import os
import time
import hmac
import json
import struct
import base64
import requests
from hashlib import sha1
import argparse


def getQueryTime():
    try:
        request = requests.post(
            "https://api.steampowered.com/ITwoFactorService/QueryTime/v0001", timeout=30
        )
        json_data = request.json()
        server_time = int(json_data["response"]["server_time"]) - time.time()
        return server_time
    except:
        return 0


def getGuardCode(shared_secret):
    symbols = "23456789BCDFGHJKMNPQRTVWXY"
    code = ""
    timestamp = time.time() + getQueryTime()
    _hmac = hmac.new(
        base64.b64decode(shared_secret), struct.pack(">Q", int(timestamp / 30)), sha1
    ).digest()
    _ord = ord(_hmac[19:20]) & 0xF
    value = struct.unpack(">I", _hmac[_ord : _ord + 4])[0] & 0x7FFFFFFF
    for i in range(5):
        code += symbols[value % len(symbols)]
        value = int(value / len(symbols))
    return code


def get_steam_guard_code(mafile_path=None, mafile_json=None):
    try:
        data = None
        if mafile_json:
            if isinstance(mafile_json, dict):
                data = mafile_json
            else:
                data = json.loads(mafile_json)
        elif mafile_path:
            with open(mafile_path, "r") as file:
                data = json.loads(file.read())
        else:
            return {"success": False, "error": "Missing .maFile data"}

        code = getGuardCode(data["shared_secret"])
        return code

    except FileNotFoundError:
        return {"success": False, "error": "File not found"}
    except json.JSONDecodeError:
        return {"success": False, "error": "Invalid .maFile format"}
    except KeyError:
        return {"success": False, "error": "Missing required data in .maFile"}
    except Exception as e:
        return {"success": False, "error": str(e)}
