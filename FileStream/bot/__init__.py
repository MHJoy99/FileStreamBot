from ..config import Telegram
from pyrogram import Client

if Telegram.SECONDARY:
    plugins=None
    no_updates=True
else:    
    plugins={"root": "FileStream/bot/plugins"}
    no_updates=None

FileStream = Client(
    name="FileStream",
    api_id=Telegram.API_ID,
    api_hash=Telegram.API_HASH,
    workdir="FileStream",
    plugins=plugins,
    bot_token=Telegram.BOT_TOKEN,
    sleep_threshold=Telegram.SLEEP_THRESHOLD,
    workers=Telegram.WORKERS,
    no_updates=no_updates
)

LibraryScannerClient = None
if Telegram.USER_SESSION_STRING:
    LibraryScannerClient = Client(
        name="FileStreamScanner",
        api_id=Telegram.API_ID,
        api_hash=Telegram.API_HASH,
        session_string=Telegram.USER_SESSION_STRING,
        sleep_threshold=Telegram.SLEEP_THRESHOLD,
        no_updates=True,
        in_memory=True,
    )

multi_clients = {}
work_loads = {}
