import logging
import math
import contextlib
from FileStream import __version__
from FileStream.bot import FileStream, LibraryScannerClient
from FileStream.server.exceptions import FIleNotFound
from FileStream.utils.bot_utils import gen_linkx, verify_user
from FileStream.config import Telegram, Server
from FileStream.utils.database import Database
from FileStream.utils.playlist_utils import build_playlist_buffer
from FileStream.utils.translation import LANG, BUTTON
from pyrogram import filters, Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.enums.parse_mode import ParseMode
import asyncio

db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)


def _pick_bot_usable_file_id(file_doc: dict, bot_id: int) -> str:
    available_file_ids = file_doc.get("file_ids") or {}
    bot_file_id = available_file_ids.get(str(bot_id))
    if bot_file_id:
        return bot_file_id
    if not file_doc.get("source_chat_id"):
        return file_doc.get("file_id") or ""
    return ""


async def _send_bundle_files(bot: Client, message: Message, bundle: dict):
    file_docs = await db.get_files_by_ids(bundle["user_id"], bundle.get("file_ids", []))
    if not file_docs:
        await message.reply_text("**No valid files were found inside this Telegram bundle.**")
        return

    status_chat_id = message.chat.id
    destination_chat_id = Telegram.BUNDLE_FALLBACK_CHAT or Telegram.ULOG_CHANNEL or Telegram.FLOG_CHANNEL or message.chat.id
    destination_header_sent = False
    progress = await message.reply_text(
        f"**Sending {len(file_docs)} selected files to Telegram destination...**\n\n`{bundle.get('title', 'Telegram bundle')}`",
        quote=True,
    )
    sent_count = 0
    destination_count = 0
    failed_count = 0

    for index, file_doc in enumerate(file_docs, start=1):
        file_id = _pick_bot_usable_file_id(file_doc, bot.id)
        source_chat_id = file_doc.get("source_chat_id")
        source_message_id = file_doc.get("source_message_id")
        file_name = file_doc.get("file_name", f"File {index}")

        try:
            if destination_chat_id == status_chat_id:
                if file_id:
                    sent_message = await bot.send_cached_media(
                        chat_id=destination_chat_id,
                        file_id=file_id,
                        caption=f"**{file_name}**",
                    )
                    if not sent_message:
                        raise RuntimeError("Bot send_cached_media returned no message")
                elif source_chat_id and source_message_id:
                    sent_message = await bot.copy_message(
                        chat_id=destination_chat_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                    )
                    if not sent_message:
                        raise RuntimeError("Bot copy_message returned no message")
                else:
                    raise RuntimeError("No bot-safe file path exists")
            else:
                if file_id:
                    sent_message = await bot.send_cached_media(
                        chat_id=destination_chat_id,
                        file_id=file_id,
                        caption=f"**{file_name}**",
                    )
                    if not sent_message:
                        raise RuntimeError("Bot send_cached_media returned no message")
                elif source_chat_id and source_message_id and LibraryScannerClient:
                    if not destination_header_sent:
                        await LibraryScannerClient.send_message(
                            destination_chat_id,
                            f"Telegram website bundle\n{bundle.get('title', 'Telegram bundle')}\nSelected files are being delivered here from the website bundle link.",
                        )
                        destination_header_sent = True
                    sent_message = await LibraryScannerClient.copy_message(
                        destination_chat_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                    )
                    if not sent_message:
                        raise RuntimeError("Scanner copy_message returned no message")
                elif source_chat_id and source_message_id:
                    sent_message = await bot.copy_message(
                        chat_id=destination_chat_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id,
                    )
                    if not sent_message:
                        raise RuntimeError("Bot copy_message returned no message")
                else:
                    raise RuntimeError("No destination delivery path exists")

            sent_count += 1
            destination_count += 1
            logging.info("Delivered bundle file %s to bundle destination %s", file_doc.get("_id"), destination_chat_id)

            if index == 1 or index == len(file_docs) or index % 10 == 0:
                with contextlib.suppress(Exception):
                    await progress.edit_text(
                        f"**Sending Telegram bundle...**\n\n`{bundle.get('title', 'Telegram bundle')}`\n"
                        f"`{sent_count}/{len(file_docs)} delivered`\n"
                        f"`{destination_count}` sent to destination `{destination_chat_id}`"
                    )
            await asyncio.sleep(0.2)
        except Exception as error:
            sent_via_route = False

            if not sent_via_route and destination_chat_id and source_chat_id and source_message_id and LibraryScannerClient:
                try:
                    if not destination_header_sent:
                        await LibraryScannerClient.send_message(
                            destination_chat_id,
                            f"Telegram website bundle\n{bundle.get('title', 'Telegram bundle')}\nSelected files are being copied here because the primary resend path failed.",
                        )
                        destination_header_sent = True
                    copied = await LibraryScannerClient.copy_message(
                            destination_chat_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id,
                        )
                    if not copied:
                        raise RuntimeError("Scanner copy_message to destination returned no message")
                    sent_count += 1
                    destination_count += 1
                    sent_via_route = True
                    logging.warning(
                        "Delivered bundle file %s to destination chat %s via scanner after primary path failed: %s",
                        file_doc.get("_id"), destination_chat_id, error
                    )
                except Exception as destination_copy_error:
                    logging.error(
                        "Could not deliver bundle file %s via primary path (%s) or scanner destination path (%s)",
                        file_doc.get("_id"), error, destination_copy_error
                    )

            if not sent_via_route and destination_chat_id:
                try:
                    if file_id:
                        fallback_message = await bot.send_cached_media(
                            chat_id=destination_chat_id,
                            file_id=file_id,
                            caption=f"**{file_name}**",
                        )
                    elif source_chat_id and source_message_id:
                        fallback_message = await bot.copy_message(
                            chat_id=destination_chat_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id,
                        )
                    else:
                        raise RuntimeError("No destination fallback path exists")
                    if not fallback_message:
                        raise RuntimeError("Fallback send returned no message")
                    sent_count += 1
                    destination_count += 1
                    sent_via_route = True
                    logging.warning(
                        "Delivered bundle file %s to destination chat %s after primary failure: %s",
                        file_doc.get("_id"), destination_chat_id, error
                    )
                except Exception as destination_error:
                    logging.error(
                        "Could not send bundle file %s via destination chat after primary path failure (%s): %s",
                        file_doc.get("_id"), error, destination_error
                    )

            if not sent_via_route:
                failed_count += 1
                logging.error("Could not send bundle file %s: %s", file_doc.get("_id"), error)

    with contextlib.suppress(Exception):
        await progress.edit_text(
            f"**Telegram bundle finished**\n\n`{bundle.get('title', 'Telegram bundle')}`\n`{sent_count}/{len(file_docs)} files sent`"
            + (f"\n`{destination_count}` sent to destination chat `{destination_chat_id}`" if destination_count else "")
            + (f"\n`{failed_count}` failed" if failed_count else "")
        )

@FileStream.on_message(filters.command('start') & filters.private)
async def start(bot: Client, message: Message):
    if not await verify_user(bot, message):
        return
    start_arg = ""
    if getattr(message, "command", None) and len(message.command) > 1:
        start_arg = str(message.command[1]).strip()
    elif message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            start_arg = parts[1].strip()

    if not start_arg:
        if Telegram.START_PIC:
            await message.reply_photo(
                photo=Telegram.START_PIC,
                caption=LANG.START_TEXT.format(message.from_user.mention, FileStream.username),
                parse_mode=ParseMode.HTML,
                reply_markup=BUTTON.START_BUTTONS
            )
        else:
            await message.reply_text(
                text=LANG.START_TEXT.format(message.from_user.mention, FileStream.username),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=BUTTON.START_BUTTONS
            )
    else:
        if start_arg.startswith("stream_"):
            try:
                db_id_arg = start_arg.removeprefix("stream_")
                file_check = await db.get_file(db_id_arg)
                file_id = str(file_check['_id'])
                if file_id == db_id_arg:
                    reply_markup, stream_text = await gen_linkx(m=message, _id=file_id,
                                                                name=[FileStream.username, FileStream.fname])
                    await message.reply_text(
                        text=stream_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                        quote=True
                    )

            except FIleNotFound as e:
                await message.reply_text("File Not Found")
            except Exception as e:
                await message.reply_text("Something Went Wrong")
                logging.error(e)

        elif start_arg.startswith("file_"):
            try:
                db_id_arg = start_arg.removeprefix("file_")
                file_check = await db.get_file(db_id_arg)
                db_id = str(file_check['_id'])
                file_id = _pick_bot_usable_file_id(file_check, bot.id)
                file_name = file_check['file_name']
                if db_id == db_id_arg:
                    filex = await message.reply_cached_media(file_id=file_id, caption=f'**{file_name}**')
                    await asyncio.sleep(3600)
                    try:
                        await filex.delete()
                        await message.delete()
                    except Exception:
                        pass

            except FIleNotFound as e:
                await message.reply_text("**File Not Found**")
            except Exception as e:
                await message.reply_text("Something Went Wrong")
                logging.error(e)

        elif start_arg.startswith("tgpack_"):
            try:
                bundle_token = start_arg.removeprefix("tgpack_")
                bundle = await db.get_tg_bundle(bundle_token)
                if not bundle:
                    await message.reply_text("**Telegram bundle not found.**")
                    return
                await _send_bundle_files(bot, message, bundle)
            except Exception as e:
                await message.reply_text("Something Went Wrong")
                logging.error(e)

        else:
            await message.reply_text(f"**Invalid Command**")

@FileStream.on_message(filters.private & filters.command(["about"]))
async def start(bot, message):
    if not await verify_user(bot, message):
        return
    if Telegram.START_PIC:
        await message.reply_photo(
            photo=Telegram.START_PIC,
            caption=LANG.ABOUT_TEXT.format(FileStream.fname, __version__),
            parse_mode=ParseMode.HTML,
            reply_markup=BUTTON.ABOUT_BUTTONS
        )
    else:
        await message.reply_text(
            text=LANG.ABOUT_TEXT.format(FileStream.fname, __version__),
            disable_web_page_preview=True,
            reply_markup=BUTTON.ABOUT_BUTTONS
        )

@FileStream.on_message((filters.command('help')) & filters.private)
async def help_handler(bot, message):
    if not await verify_user(bot, message):
        return
    if Telegram.START_PIC:
        await message.reply_photo(
            photo=Telegram.START_PIC,
            caption=LANG.HELP_TEXT.format(Telegram.OWNER_ID),
            parse_mode=ParseMode.HTML,
            reply_markup=BUTTON.HELP_BUTTONS
        )
    else:
        await message.reply_text(
            text=LANG.HELP_TEXT.format(Telegram.OWNER_ID),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=BUTTON.HELP_BUTTONS
        )

# ---------------------------------------------------------------------------------------------------

@FileStream.on_message(filters.command('files') & filters.private)
async def my_files(bot: Client, message: Message):
    if not await verify_user(bot, message):
        return
    user_files, total_files = await db.find_files(message.from_user.id, [1, 10])

    file_list = []
    async for x in user_files:
        file_list.append([InlineKeyboardButton(x["file_name"], callback_data=f"myfile_{x['_id']}_{1}")])
    if total_files > 10:
        file_list.append(
            [
                InlineKeyboardButton("◄", callback_data="N/A"),
                InlineKeyboardButton(f"1/{math.ceil(total_files / 10)}", callback_data="N/A"),
                InlineKeyboardButton("►", callback_data="userfiles_2")
            ],
        )
    if not file_list:
        file_list.append(
            [InlineKeyboardButton("ᴇᴍᴘᴛʏ", callback_data="N/A")],
        )
    file_list.append([InlineKeyboardButton("ᴘʟᴀʏʟɪsᴛ ᴍ𝟹ᴜ", callback_data="sendplaylist")])
    file_list.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")])
    await message.reply_photo(photo=Telegram.FILE_PIC,
                              caption="Total files: {}".format(total_files),
                              reply_markup=InlineKeyboardMarkup(file_list))


@FileStream.on_message(filters.command(['playlist', 'm3u']) & filters.private)
async def send_playlist(bot: Client, message: Message):
    if not await verify_user(bot, message):
        return

    playlist_buffer = await build_m3u_playlist(message.from_user.id)
    if playlist_buffer is None:
        await message.reply_text("**No files found to build a playlist.**")
        return

    await message.reply_document(
        document=playlist_buffer,
        caption=LANG.PLAYLIST_TEXT,
        quote=True
    )


async def build_m3u_playlist(user_id: int):
    user_files = await db.get_all_files_by_user(user_id)
    file_docs = [file_info async for file_info in user_files]
    return build_playlist_buffer(file_docs, f"filestream_playlist_{user_id}")
