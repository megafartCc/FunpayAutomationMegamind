import json
import os
import secrets
import string
import sys


sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.logger import logger
from steampassword.chpassword import SteamPasswordChange
from steampassword.steam import CustomSteam


def generate_password(length: int = 12) -> str:
    """
    Generate a secure random password.

    Args:
        length (int): Length of the password. Default is 12.

    Returns:
        str: A randomly generated password.
    """
    if length < 8:
        raise ValueError("Password length should be at least 8 characters.")

    # Define the character pool
    alphabet = string.ascii_letters + string.digits
    # Generate a secure random password
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


async def changeSteamPassword(
    path_to_maFile: str | None,
    password: str,
    mafile_json: str | dict | None = None,
    new_password: str | None = None,
    steam_login: str | None = None,
) -> str:

    logger.info("Started changing password")

    data = None
    if mafile_json:
        data = mafile_json if isinstance(mafile_json, dict) else json.loads(mafile_json)
    elif path_to_maFile:
        with open(path_to_maFile, "r") as f:
            data = json.load(f)
    else:
        raise ValueError("Missing .maFile data")

    steam_username = steam_login or data.get("account_name")
    if not steam_username:
        raise ValueError("Missing Steam login in .maFile data")

    logger.info(f"Started changing password for {steam_username}")
    steam = CustomSteam(
        login=steam_username,
        password=password,
        shared_secret=data["shared_secret"],
        identity_secret=data["identity_secret"],
        device_id=data["device_id"],
        steamid=int(data["Session"]["SteamID"]),
    )

    if new_password is None:
        new_password = generate_password(12)

    await SteamPasswordChange(steam).change(new_password)

    logger.info(f"{steam_username} password changed successfully")

    return new_password
