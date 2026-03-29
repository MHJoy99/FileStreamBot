import asyncio
import os
import time

from FileStream.bot import LibraryScannerClient
from FileStream.config import Telegram
from FileStream.utils.database import Database
from FileStream.utils.file_properties import get_media_from_message, get_name


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}

db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)
scan_lock = asyncio.Lock()
scan_task = None
auto_sync_task = None
scan_state = {
    "running": False,
    "chat_id": None,
    "chat_title": None,
    "mode": "full",
    "started_at": None,
    "finished_at": None,
    "total_messages": 0,
    "scanned_messages": 0,
    "matched_videos": 0,
    "imported_files": 0,
    "duplicate_files": 0,
    "skipped_messages": 0,
    "last_file_name": "",
    "error": "",
}
AUTO_SYNC_INTERVAL = 60
AUTO_SYNC_FETCH_LIMIT = 200


def get_scan_status():
    payload = dict(scan_state)
    if payload["started_at"] and payload["running"]:
        payload["elapsed_seconds"] = int(time.time() - payload["started_at"])
    elif payload["started_at"] and payload["finished_at"]:
        payload["elapsed_seconds"] = int(payload["finished_at"] - payload["started_at"])
    else:
        payload["elapsed_seconds"] = 0
    total_messages = int(payload.get("total_messages") or 0)
    scanned_messages = int(payload.get("scanned_messages") or 0)
    if total_messages > 0:
        payload["progress_percent"] = round(min(100, (scanned_messages / total_messages) * 100), 1)
    elif payload.get("running"):
        payload["progress_percent"] = None
    elif payload.get("chat_id"):
        payload["progress_percent"] = 100.0
    else:
        payload["progress_percent"] = 0.0

    elapsed_seconds = payload["elapsed_seconds"]
    payload["messages_per_second"] = round(scanned_messages / elapsed_seconds, 1) if elapsed_seconds else 0.0
    return payload


def _reset_scan_state(chat_id, chat_title, mode="full"):
    scan_state.update(
        {
            "running": True,
            "chat_id": str(chat_id),
            "chat_title": chat_title or str(chat_id),
            "mode": mode,
            "started_at": time.time(),
            "finished_at": None,
            "total_messages": 0,
            "scanned_messages": 0,
            "matched_videos": 0,
            "imported_files": 0,
            "duplicate_files": 0,
            "skipped_messages": 0,
            "last_file_name": "",
            "error": "",
        }
    )


def _finish_scan_state(error_message=""):
    scan_state["running"] = False
    scan_state["finished_at"] = time.time()
    scan_state["error"] = error_message


def _normalize_chat_id(chat_id):
    try:
        return int(str(chat_id).strip())
    except (TypeError, ValueError):
        return chat_id


def _is_video_like_message(message) -> bool:
    if getattr(message, "video", None):
        return True

    document = getattr(message, "document", None)
    if not document:
        return False

    mime_type = (getattr(document, "mime_type", "") or "").lower()
    file_name = (getattr(document, "file_name", "") or get_name(message)).lower()
    extension = os.path.splitext(file_name)[1].lower()
    return mime_type.startswith("video/") or extension in VIDEO_EXTENSIONS


def _build_library_file_info(message):
    media = get_media_from_message(message)
    return {
        "user_id": Telegram.OWNER_ID,
        "file_id": getattr(media, "file_id", ""),
        "file_unique_id": getattr(media, "file_unique_id", ""),
        "file_name": get_name(message),
        "file_size": getattr(media, "file_size", 0),
        "mime_type": getattr(media, "mime_type", "video/unknown"),
        "source_chat_id": message.chat.id,
        "source_chat_title": getattr(message.chat, "title", "") or str(message.chat.id),
        "source_message_id": message.id,
        "source_scan": True,
    }


async def _scan_chat(chat_id):
    global scan_task

    async with scan_lock:
        history_client = LibraryScannerClient
        if not history_client:
            raise RuntimeError("Full chat scanning needs USER_SESSION_STRING because Telegram blocks history access for bots.")

        resolved_chat_id = _normalize_chat_id(chat_id)
        _reset_scan_state(chat_id, str(chat_id), mode="full")
        highest_message_id = 0

        try:
            try:
                scan_state["total_messages"] = int(await history_client.get_chat_history_count(resolved_chat_id))
            except Exception:
                scan_state["total_messages"] = 0

            async for message in history_client.get_chat_history(resolved_chat_id):
                highest_message_id = max(highest_message_id, getattr(message, "id", 0) or 0)
                if scan_state["chat_title"] == str(chat_id):
                    scan_state["chat_title"] = getattr(message.chat, "title", None) or str(chat_id)
                scan_state["scanned_messages"] += 1

                if not message or not message.media or not _is_video_like_message(message):
                    scan_state["skipped_messages"] += 1
                    continue

                media = get_media_from_message(message)
                unique_id = getattr(media, "file_unique_id", "")
                if not unique_id:
                    scan_state["skipped_messages"] += 1
                    continue

                scan_state["matched_videos"] += 1
                scan_state["last_file_name"] = get_name(message)

                existing = await db.get_file_by_fileuniqueid(Telegram.OWNER_ID, unique_id)
                if existing:
                    scan_state["duplicate_files"] += 1
                    continue

                file_info = _build_library_file_info(message)
                inserted_id = await db.add_file(file_info)
                await db.update_file_ids(
                    inserted_id,
                    {str(LibraryScannerClient.id): getattr(media, "file_id", "")},
                )

                scan_state["imported_files"] += 1

            await db.upsert_library_source(
                resolved_chat_id,
                chat_title=scan_state["chat_title"],
                auto_sync=True,
                enabled=True,
                last_message_id=highest_message_id,
                last_synced_at=time.time(),
                last_error="",
            )
        except Exception as error:
            await db.upsert_library_source(
                resolved_chat_id,
                chat_title=scan_state["chat_title"],
                auto_sync=True,
                enabled=True,
                last_message_id=highest_message_id,
                last_synced_at=time.time(),
                last_error=str(error),
            )
            _finish_scan_state(str(error))
            scan_task = None
            return

        _finish_scan_state("")
        scan_task = None


async def _sync_tracked_chat(chat_id):
    global scan_task

    async with scan_lock:
        history_client = LibraryScannerClient
        if not history_client:
            raise RuntimeError("Syncing tracked sources needs USER_SESSION_STRING.")

        resolved_chat_id = _normalize_chat_id(chat_id)
        source_doc = await db.get_library_source(resolved_chat_id)
        if not source_doc:
            raise RuntimeError("Source is not tracked yet.")

        _reset_scan_state(
            resolved_chat_id,
            source_doc.get("chat_title") or str(resolved_chat_id),
            mode="sync",
        )

        last_message_id = int(source_doc.get("last_message_id") or 0)
        seen_max_id = last_message_id
        pending_messages = []

        try:
            async for message in history_client.get_chat_history(resolved_chat_id):
                message_id = getattr(message, "id", 0) or 0
                if message_id <= last_message_id:
                    break
                pending_messages.append(message)
                if message_id > seen_max_id:
                    seen_max_id = message_id

            scan_state["total_messages"] = len(pending_messages)
            pending_messages.reverse()

            for message in pending_messages:
                scan_state["scanned_messages"] += 1

                if not message or not message.media or not _is_video_like_message(message):
                    scan_state["skipped_messages"] += 1
                    continue

                media = get_media_from_message(message)
                unique_id = getattr(media, "file_unique_id", "")
                if not unique_id:
                    scan_state["skipped_messages"] += 1
                    continue

                scan_state["matched_videos"] += 1
                scan_state["last_file_name"] = get_name(message)

                existing = await db.get_file_by_fileuniqueid(Telegram.OWNER_ID, unique_id)
                if existing:
                    scan_state["duplicate_files"] += 1
                    continue

                file_info = _build_library_file_info(message)
                inserted_id = await db.add_file(file_info)
                await db.update_file_ids(
                    inserted_id,
                    {str(LibraryScannerClient.id): getattr(media, "file_id", "")},
                )
                scan_state["imported_files"] += 1

            await db.update_library_source(
                resolved_chat_id,
                chat_title=source_doc.get("chat_title") or str(resolved_chat_id),
                last_message_id=seen_max_id,
                last_synced_at=time.time(),
                last_error="",
            )
        except Exception as error:
            await db.update_library_source(
                resolved_chat_id,
                last_synced_at=time.time(),
                last_error=str(error),
            )
            _finish_scan_state(str(error))
            scan_task = None
            return

        _finish_scan_state("")
        scan_task = None


async def start_library_scan(chat_id, full_rescan=False):
    global scan_task

    if scan_task and not scan_task.done():
        raise RuntimeError("A library scan is already running.")

    if not LibraryScannerClient:
        raise RuntimeError("USER_SESSION_STRING is required for full history scans.")

    resolved_chat_id = _normalize_chat_id(chat_id)
    existing_source = await db.get_library_source(resolved_chat_id)

    if existing_source and not full_rescan:
        scan_task = asyncio.create_task(_sync_tracked_chat(resolved_chat_id))
    else:
        scan_task = asyncio.create_task(_scan_chat(resolved_chat_id))

    return get_scan_status()


async def _sync_source(source_doc):
    async with scan_lock:
        history_client = LibraryScannerClient
        if not history_client:
            return

        chat_id = int(source_doc["chat_id"])
        last_message_id = int(source_doc.get("last_message_id") or 0)
        seen_max_id = last_message_id
        pending_messages = []

        async for message in history_client.get_chat_history(chat_id, limit=AUTO_SYNC_FETCH_LIMIT):
            message_id = getattr(message, "id", 0) or 0
            if message_id <= last_message_id:
                break
            pending_messages.append(message)
            if message_id > seen_max_id:
                seen_max_id = message_id

        pending_messages.reverse()

        for message in pending_messages:
            if not message or not message.media or not _is_video_like_message(message):
                continue

            media = get_media_from_message(message)
            unique_id = getattr(media, "file_unique_id", "")
            if not unique_id:
                continue

            existing = await db.get_file_by_fileuniqueid(Telegram.OWNER_ID, unique_id)
            if existing:
                continue

            file_info = _build_library_file_info(message)
            inserted_id = await db.add_file(file_info)
            await db.update_file_ids(
                inserted_id,
                {str(LibraryScannerClient.id): getattr(media, "file_id", "")},
            )

        await db.update_library_source(
            chat_id,
            chat_title=source_doc.get("chat_title") or str(chat_id),
            last_message_id=seen_max_id,
            last_synced_at=time.time(),
            last_error="",
        )


async def _auto_sync_loop():
    while True:
        try:
            if LibraryScannerClient:
                sources = await db.get_library_sources(enabled_only=True)
                for source in sources:
                    if not source.get("auto_sync", True):
                        continue
                    try:
                        await _sync_source(source)
                    except Exception as error:
                        await db.update_library_source(
                            source["chat_id"],
                            last_synced_at=time.time(),
                            last_error=str(error),
                        )
        except Exception:
            pass

        await asyncio.sleep(AUTO_SYNC_INTERVAL)


async def bootstrap_library_sources():
    rows = await db.get_source_bootstrap_rows(Telegram.OWNER_ID)
    for row in rows:
        chat_id = int(row["_id"])
        existing = await db.get_library_source(chat_id)
        if existing:
            continue
        await db.upsert_library_source(
            chat_id,
            chat_title=row.get("chat_title") or str(chat_id),
            auto_sync=True,
            enabled=True,
            last_message_id=row.get("last_message_id", 0),
            last_synced_at=None,
            last_error="",
        )


async def start_auto_sync():
    global auto_sync_task

    if auto_sync_task and not auto_sync_task.done():
        return auto_sync_task

    if not LibraryScannerClient:
        return None

    await bootstrap_library_sources()
    auto_sync_task = asyncio.create_task(_auto_sync_loop())
    return auto_sync_task
