import asyncio
import math
import logging
import mimetypes
import json
import time
import traceback
import urllib.parse

from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from pyrogram.errors import FileReferenceExpired

from FileStream import StartTime, __version__, utils
from FileStream.bot import FileStream, multi_clients, work_loads
from FileStream.config import Server, Telegram
from FileStream.server.exceptions import FIleNotFound, InvalidHash
from FileStream.utils.database import Database
from FileStream.utils.catalog_utils import build_library_groups, fetch_tmdb_by_id, parse_media_name, search_tmdb_candidates
from FileStream.utils.file_properties import get_media_from_message
from FileStream.utils.human_readable import humanbytes
from FileStream.utils.library_scan import get_scan_status, start_library_scan
from FileStream.utils.playlist_utils import build_playlist_buffer
from FileStream.utils.render_template import (
    render_admin_dashboard,
    render_admin_login,
    render_page,
)
from FileStream.utils.web_admin import (
    attach_admin_session,
    clear_admin_session,
    get_admin_username,
    hash_password,
    is_admin_authenticated,
    verify_password,
)

routes = web.RouteTableDef()
db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)
class_cache = {}
normalization_locks = {}
normalization_failures = {}
ADMIN_PAGE_SIZE = 25
WALL_PAGE_SIZES = (12, 24, 48)
FILE_PAGE_SIZES = (50, 100, 250, 500)
ADMIN_STATS_TTL = 30
NORMALIZATION_RETRY_TTL = 900
admin_stats_cache = {}
ADMIN_FILE_PROJECTION = {
    "_id": 1,
    "file_name": 1,
    "file_size": 1,
    "time": 1,
    "source_chat_id": 1,
    "source_chat_title": 1,
}


def _require_admin(request: web.Request):
    if not is_admin_authenticated(request):
        raise web.HTTPFound("/admin/login")


def _safe_page(value, default=1):
    try:
        page = int(value)
    except (TypeError, ValueError):
        page = default
    return max(page, 1)


def _safe_view_mode(value, search_query=""):
    view_mode = str(value or "").strip().lower()
    if view_mode in {"wall", "files"}:
        return view_mode
    return "files" if search_query else "wall"


def _safe_per_page(value, view_mode: str):
    allowed = FILE_PAGE_SIZES if view_mode == "files" else WALL_PAGE_SIZES
    default = 100 if view_mode == "files" else 12
    try:
        per_page = int(value)
    except (TypeError, ValueError):
        per_page = default
    return per_page if per_page in allowed else default


def _safe_confidence_filter(value):
    match_filter = str(value or "").strip().lower()
    if match_filter in {"all", "trusted", "review", "filename"}:
        return match_filter
    return "all"


def _safe_sort_mode(value, view_mode: str):
    if view_mode != "files":
        return "smart"
    sort_mode = str(value or "").strip().lower()
    if sort_mode in {"newest", "name", "size", "season"}:
        return sort_mode
    return "newest"


def _resolve_sort_mode(sort_mode: str):
    mapping = {
        "newest": ("time", -1),
        "name": ("file_name", 1),
        "size": ("file_size", -1),
        "season": ("file_name", 1),
    }
    return mapping.get(sort_mode, ("time", -1))


def _format_file_time(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
    return "-"


async def _build_admin_context(page: int):
    return await _build_admin_context_with_filters(page, "", "all", "wall", 12, "all", "smart")


def _cache_get(cache_key: str, ttl: int):
    entry = admin_stats_cache.get(cache_key)
    if not entry:
        return None
    if time.time() - entry["time"] > ttl:
        admin_stats_cache.pop(cache_key, None)
        return None
    return entry["value"]


def _cache_set(cache_key: str, value):
    admin_stats_cache[cache_key] = {"time": time.time(), "value": value}
    return value


async def _get_admin_stats():
    owner_key = str(Telegram.OWNER_ID)
    cached = _cache_get(f"admin-stats:{owner_key}", ADMIN_STATS_TTL)
    if cached is not None:
        return cached

    total_size, source_overview, tracked_sources, library_total_files = await asyncio.gather(
        db.total_file_size(Telegram.OWNER_ID),
        db.get_source_overview(Telegram.OWNER_ID),
        db.get_library_sources(),
        db.total_files(Telegram.OWNER_ID),
    )
    return _cache_set(
        f"admin-stats:{owner_key}",
        {
            "total_size": total_size,
            "source_overview": source_overview,
            "tracked_sources": tracked_sources,
            "library_total_files": library_total_files,
        },
    )


async def _build_admin_context_with_filters(page: int, search_query: str, source_chat_id: str, view_mode: str, per_page: int, confidence_filter: str, sort_mode: str):
    await db.ensure_indexes()
    total_files = 0
    groups = []
    file_rows = []
    total_groups = 0
    admin_stats_task = asyncio.create_task(_get_admin_stats())
    custom_admin_users_task = asyncio.create_task(db.list_admin_users())

    if view_mode == "files":
        sort_field, sort_order = _resolve_sort_mode(sort_mode)
        visible_files, total_files = await db.get_filtered_files_page(
            Telegram.OWNER_ID,
            page=page,
            per_page=per_page,
            search_query=search_query,
            source_chat_id=source_chat_id,
            sort_field=sort_field,
            sort_order=sort_order,
            projection=ADMIN_FILE_PROJECTION,
        )
        total_pages = max(1, math.ceil(total_files / per_page)) if per_page else 1
        page = min(page, total_pages)
        visible_links = []
        for file_info in visible_files:
            parsed = parse_media_name(file_info.get("file_name", ""))
            download_url = f"{Server.URL}dl/{file_info['_id']}"
            visible_links.append(download_url)
            file_rows.append(
                {
                    "id": str(file_info["_id"]),
                    "name": file_info.get("file_name", ""),
                    "size": humanbytes(file_info.get("file_size", 0)),
                    "download_url": download_url,
                    "watch_url": f"{Server.URL}watch/{file_info['_id']}",
                    "source_title": file_info.get("source_chat_title") or str(file_info.get("source_chat_id", "")),
                    "source_chat_id": str(file_info.get("source_chat_id", "")),
                    "parsed_title": parsed.get("title") or file_info.get("file_name", ""),
                    "media_kind": parsed.get("media_kind", "movie"),
                    "season": parsed.get("season"),
                    "episode": parsed.get("episode"),
                    "confidence": "filename",
                }
            )
    else:
        files = await db.get_filtered_files(
            Telegram.OWNER_ID,
            search_query=search_query,
            source_chat_id=source_chat_id,
            projection=ADMIN_FILE_PROJECTION,
        )
        total_files = len(files)
        grouped_payload = await build_library_groups(files, page, per_page=per_page, confidence_filter=confidence_filter)
        groups = grouped_payload["groups"]
        total_groups = grouped_payload["total_groups"]
        total_pages = grouped_payload["total_pages"]
        page = grouped_payload["current_page"]
        visible_links = []
        group_rows = []
        for group in groups:
            item_rows = []
            for file_info in group["files"]:
                download_url = f"{Server.URL}dl/{file_info['id']}"
                visible_links.append(download_url)
                item_rows.append(
                    {
                        "id": file_info["id"],
                        "name": file_info["name"],
                        "size": humanbytes(file_info.get("file_size", 0)),
                        "season": file_info.get("season"),
                        "episode": file_info.get("episode"),
                        "download_url": download_url,
                        "watch_url": f"{Server.URL}watch/{file_info['id']}",
                    }
                )

            group_rows.append(
                {
                    "key": group["key"],
                    "display_title": group["display_title"],
                    "overview": group["overview"],
                    "poster_url": group["poster_url"],
                    "backdrop_url": group["backdrop_url"],
                    "release_year": group["release_year"],
                    "media_kind": group["media_kind"],
                    "confidence": group.get("confidence", "filename"),
                    "count": group["count"],
                    "total_size": humanbytes(group["total_size"]),
                    "source_titles": group["source_titles"],
                    "files": item_rows,
                }
            )
        groups = group_rows

    admin_stats = await admin_stats_task
    total_size = admin_stats["total_size"]
    source_overview = admin_stats["source_overview"]
    tracked_sources = admin_stats["tracked_sources"]
    custom_admin_users = await custom_admin_users_task

    visible_links_text = "\n".join(visible_links)
    base_query = {}
    if search_query:
        base_query["q"] = search_query
    if source_chat_id not in ("", "all"):
        base_query["source"] = source_chat_id
    if view_mode != _safe_view_mode("", search_query):
        base_query["view"] = view_mode
    if per_page != _safe_per_page(None, view_mode):
        base_query["per_page"] = per_page
    if view_mode == "wall" and confidence_filter != "all":
        base_query["match"] = confidence_filter
    if view_mode == "files" and sort_mode != "newest":
        base_query["sort"] = sort_mode

    prev_page_url = None
    next_page_url = None
    if page > 1:
        prev_query = dict(base_query)
        prev_query["page"] = page - 1
        prev_page_url = "/admin?" + urllib.parse.urlencode(prev_query)
    if page < total_pages:
        next_query = dict(base_query)
        next_query["page"] = page + 1
        next_page_url = "/admin?" + urllib.parse.urlencode(next_query)

    source_options = [
        {
            "chat_id": "all",
            "chat_title": "All Sources",
            "count": total_files,
            "selected": source_chat_id in ("", "all"),
        }
    ]
    for source in source_overview:
        source_id = str(source["_id"])
        source_options.append(
            {
                "chat_id": source_id,
                "chat_title": source.get("chat_title") or source_id,
                "count": source.get("count", 0),
                "selected": source_chat_id == source_id,
            }
        )

    tracked_source_rows = [
        {
            "chat_id": str(source["chat_id"]),
            "chat_title": source.get("chat_title") or str(source["chat_id"]),
            "last_message_id": source.get("last_message_id", 0),
            "last_synced_at": _format_file_time(source.get("last_synced_at")),
            "last_error": source.get("last_error", ""),
            "auto_sync": source.get("auto_sync", True),
            "enabled": source.get("enabled", True),
        }
        for source in tracked_sources
    ]
    env_admin_rows = [
        {
            "username": username,
            "source": "env",
            "protected": True,
        }
        for username in sorted(Telegram.ADMIN_CREDENTIALS.keys())
    ]
    custom_admin_rows = [
        {
            "username": user.get("username", ""),
            "source": "panel",
            "protected": False,
            "created_by": user.get("created_by", ""),
        }
        for user in custom_admin_users
    ]
    payload = {
        "site_url": Server.URL,
        "dashboard_title": "FileStream Control Room",
        "username": Telegram.ADMIN_USERNAME,
        "session_username": "",
        "total_files": total_files,
        "total_groups": total_groups,
        "library_total_files": admin_stats["library_total_files"],
        "total_size": humanbytes(total_size),
        "current_page": page,
        "total_pages": total_pages,
        "prev_page_url": prev_page_url,
        "next_page_url": next_page_url,
        "search_query": search_query,
        "active_source_chat_id": source_chat_id,
        "view_mode": view_mode,
        "per_page": per_page,
        "per_page_options": list(FILE_PAGE_SIZES if view_mode == "files" else WALL_PAGE_SIZES),
        "confidence_filter": confidence_filter if view_mode == "wall" else "all",
        "confidence_options": [
            {"value": "all", "label": "All Matches"},
            {"value": "trusted", "label": "Trusted Only"},
            {"value": "review", "label": "Needs Review"},
            {"value": "filename", "label": "Filename Only"},
        ],
        "sort_mode": sort_mode,
        "sort_options": [
            {"value": "newest", "label": "Newest First"},
            {"value": "name", "label": "Filename A-Z"},
            {"value": "size", "label": "Largest First"},
            {"value": "season", "label": "Season / Episode"},
        ],
        "source_options": source_options,
        "tracked_sources": tracked_source_rows,
        "groups": groups,
        "file_rows": file_rows,
        "wall_view_url": "/admin?" + urllib.parse.urlencode(
            {
                **({"q": search_query} if search_query else {}),
                **({"source": source_chat_id} if source_chat_id not in ("", "all") else {}),
                "view": "wall",
            }
        ),
        "files_view_url": "/admin?" + urllib.parse.urlencode(
            {
                **({"q": search_query} if search_query else {}),
                **({"source": source_chat_id} if source_chat_id not in ("", "all") else {}),
                "view": "files",
                "per_page": 100,
            }
        ),
        "create_playlist_endpoint": "/admin/api/playlists",
        "create_tg_bundle_endpoint": "/admin/api/tg-bundles",
        "all_playlist_url": "/admin/export/all.m3u",
        "all_links_url": "/admin/export/all.txt",
        "logout_url": "/admin/logout",
        "visible_links_text": visible_links_text,
        "scan_start_endpoint": "/admin/api/scans/start",
        "scan_status_endpoint": "/admin/api/scans/status",
        "scan_status": get_scan_status(),
        "scan_status_json": json.dumps(get_scan_status()),
        "catalog_search_endpoint": "/admin/api/catalog/search",
        "catalog_lookup_endpoint": "/admin/api/catalog/lookup",
        "catalog_override_endpoint": "/admin/api/catalog/override",
        "catalog_clear_endpoint": "/admin/api/catalog/clear",
        "admin_users_endpoint": "/admin/api/admin-users",
        "admin_users": env_admin_rows + custom_admin_rows,
    }
    payload["initial_data"] = dict(payload)
    return payload


@routes.get("/status", allow_head=True)
async def root_route_handler(_):
    return web.json_response(
        {
            "server_status": "running",
            "uptime": utils.get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + FileStream.username,
            "connected_bots": len(multi_clients),
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(
                    sorted(work_loads.items(), key=lambda x: x[1], reverse=True)
                )
            ),
            "version": __version__,
        }
    )


@routes.get("/admin/login")
async def admin_login_page(_request: web.Request):
    if is_admin_authenticated(_request):
        raise web.HTTPFound("/admin")

    return web.Response(text=render_admin_login(), content_type="text/html")


@routes.post("/admin/login")
async def admin_login_submit(request: web.Request):
    await db.ensure_indexes()
    if not Telegram.ADMIN_CREDENTIALS and not await db.list_admin_users():
        raise web.HTTPServiceUnavailable(text="Admin web login is not configured.")

    form = await request.post()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    valid_login = Telegram.ADMIN_CREDENTIALS.get(username) == password
    if not valid_login:
        admin_user = await db.get_admin_user(username)
        valid_login = bool(admin_user and verify_password(password, admin_user.get("password_hash", "")))

    if not valid_login:
        return web.Response(
            text=render_admin_login("Wrong username or password."),
            content_type="text/html",
            status=401,
        )

    response = web.HTTPFound("/admin")
    attach_admin_session(response, username)
    return response


@routes.post("/admin/logout")
async def admin_logout(request: web.Request):
    _require_admin(request)
    response = web.HTTPFound("/admin/login")
    clear_admin_session(response)
    return response


@routes.get("/admin")
async def admin_dashboard(request: web.Request):
    _require_admin(request)
    page = _safe_page(request.query.get("page"))
    search_query = str(request.query.get("q", "")).strip()
    source_chat_id = str(request.query.get("source", "all")).strip() or "all"
    view_mode = _safe_view_mode(request.query.get("view"), search_query)
    per_page = _safe_per_page(request.query.get("per_page"), view_mode)
    confidence_filter = _safe_confidence_filter(request.query.get("match"))
    sort_mode = _safe_sort_mode(request.query.get("sort"), view_mode)
    context = await _build_admin_context_with_filters(page, search_query, source_chat_id, view_mode, per_page, confidence_filter, sort_mode)
    context["username"] = get_admin_username(request) or Telegram.ADMIN_USERNAME
    context["session_username"] = context["username"]
    context["initial_data"]["username"] = context["username"]
    context["initial_data"]["session_username"] = context["session_username"]
    return web.Response(text=render_admin_dashboard(**context), content_type="text/html")


@routes.get("/admin/export/all.m3u")
async def export_all_playlist(request: web.Request):
    _require_admin(request)
    file_docs = [file_info async for file_info in await db.get_all_files_by_user(Telegram.OWNER_ID, sort_order=-1)]
    playlist_buffer = build_playlist_buffer(file_docs, "filestream_all_files")
    if playlist_buffer is None:
        raise web.HTTPNotFound(text="No files found.")

    return web.Response(
        body=playlist_buffer.getvalue(),
        content_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{playlist_buffer.name}"'},
    )


@routes.get("/admin/export/all.txt")
async def export_all_links(request: web.Request):
    _require_admin(request)
    file_docs = [file_info async for file_info in await db.get_all_files_by_user(Telegram.OWNER_ID, sort_order=-1)]
    if not file_docs:
        raise web.HTTPNotFound(text="No files found.")

    payload = "\n".join(f"{Server.URL}dl/{file_info['_id']}" for file_info in file_docs) + "\n"
    return web.Response(
        text=payload,
        content_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="filestream_all_links.txt"'},
    )


@routes.post("/admin/api/playlists")
async def create_playlist(request: web.Request):
    _require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    title = " ".join(str(payload.get("title", "")).split()).strip() or f"playlist_{int(time.time())}"
    selected_ids = payload.get("file_ids") or []
    selected_ids = list(dict.fromkeys(str(file_id) for file_id in selected_ids if file_id))

    if not selected_ids:
        return web.json_response({"ok": False, "error": "Select at least one file."}, status=400)

    if len(selected_ids) > 500:
        return web.json_response({"ok": False, "error": "Select 500 files or fewer per playlist."}, status=400)

    file_docs = await db.get_files_by_ids(Telegram.OWNER_ID, selected_ids)
    if not file_docs:
        return web.json_response({"ok": False, "error": "No valid files found in your selection."}, status=404)

    playlist = await db.create_playlist(
        Telegram.OWNER_ID,
        title,
        [str(file_info["_id"]) for file_info in file_docs],
    )
    playlist_url = urllib.parse.urljoin(Server.URL, f"playlist/{playlist['token']}.m3u")

    return web.json_response(
        {
            "ok": True,
            "playlist_url": playlist_url,
            "title": title,
            "count": len(file_docs),
        }
    )


@routes.post("/admin/api/tg-bundles")
async def create_tg_bundle(request: web.Request):
    _require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    title = " ".join(str(payload.get("title", "")).split()).strip() or f"telegram_bundle_{int(time.time())}"
    selected_ids = payload.get("file_ids") or []
    selected_ids = list(dict.fromkeys(str(file_id) for file_id in selected_ids if file_id))

    if not selected_ids:
        return web.json_response({"ok": False, "error": "Select at least one file."}, status=400)

    if len(selected_ids) > 100:
        return web.json_response({"ok": False, "error": "Select 100 files or fewer per Telegram bundle."}, status=400)

    file_docs = await db.get_files_by_ids(Telegram.OWNER_ID, selected_ids)
    if not file_docs:
        return web.json_response({"ok": False, "error": "No valid files found in your selection."}, status=404)

    bundle = await db.create_tg_bundle(
        Telegram.OWNER_ID,
        title,
        [str(file_info["_id"]) for file_info in file_docs],
    )
    deep_link = f"https://t.me/{FileStream.username}?start=tgpack_{bundle['token']}"

    return web.json_response(
        {
            "ok": True,
            "telegram_url": deep_link,
            "title": title,
            "count": len(file_docs),
        }
    )


@routes.get("/admin/api/scans/status")
async def admin_scan_status(request: web.Request):
    _require_admin(request)
    return web.json_response({"ok": True, "scan": get_scan_status()})


@routes.post("/admin/api/scans/start")
async def admin_start_scan(request: web.Request):
    _require_admin(request)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    chat_id = str(payload.get("chat_id", "")).strip()
    full_rescan = bool(payload.get("full_rescan"))
    if not chat_id:
        return web.json_response({"ok": False, "error": "Chat ID is required."}, status=400)

    try:
        state = await start_library_scan(chat_id, full_rescan=full_rescan)
    except RuntimeError as error:
        return web.json_response({"ok": False, "error": str(error), "scan": get_scan_status()}, status=409)
    except Exception as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)

    return web.json_response({"ok": True, "scan": state})


@routes.get("/admin/api/catalog/search")
async def admin_catalog_search(request: web.Request):
    _require_admin(request)
    query = str(request.query.get("q", "")).strip()
    media_kind = str(request.query.get("kind", "tv")).strip().lower() or "tv"
    if not query:
        return web.json_response({"ok": False, "error": "Search query is required."}, status=400)
    if media_kind not in {"tv", "movie"}:
        media_kind = "tv"
    results = await search_tmdb_candidates(query, media_kind=media_kind)
    return web.json_response({"ok": True, "results": results})


@routes.get("/admin/api/catalog/lookup")
async def admin_catalog_lookup(request: web.Request):
    _require_admin(request)
    tmdb_id = str(request.query.get("id", "")).strip()
    media_kind = str(request.query.get("kind", "tv")).strip().lower() or "tv"
    if not tmdb_id or not tmdb_id.isdigit():
        return web.json_response({"ok": False, "error": "A numeric TMDb ID is required."}, status=400)
    if media_kind not in {"tv", "movie"}:
        media_kind = "tv"
    result = await fetch_tmdb_by_id(int(tmdb_id), media_kind=media_kind)
    if not result:
        return web.json_response({"ok": False, "error": "TMDb title not found for that ID."}, status=404)
    return web.json_response({"ok": True, "result": result})


@routes.post("/admin/api/catalog/override")
async def admin_catalog_override(request: web.Request):
    _require_admin(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    group_key = str(payload.get("group_key", "")).strip()
    title = str(payload.get("title", "")).strip()
    media_kind = str(payload.get("media_kind", "tv")).strip().lower() or "tv"
    if not group_key or not title:
        return web.json_response({"ok": False, "error": "Group key and title are required."}, status=400)

    override_payload = {
        "title": title,
        "normalized_title": str(payload.get("normalized_title", "")).strip() or parse_media_name(title).get("normalized_title", ""),
        "media_kind": media_kind,
        "year": payload.get("year"),
        "poster_url": str(payload.get("poster_url", "")),
        "backdrop_url": str(payload.get("backdrop_url", "")),
        "overview": str(payload.get("overview", "")),
        "tmdb_id": payload.get("tmdb_id"),
        "tmdb_media_type": str(payload.get("tmdb_media_type", media_kind)),
        "release_year": str(payload.get("release_year", "")),
        "locked": True,
        "lock_mode": str(payload.get("lock_mode", "tmdb" if payload.get("tmdb_id") else "filename")),
    }
    entry = await db.upsert_catalog_entry(group_key, override_payload)
    return web.json_response({"ok": True, "entry": entry})


@routes.post("/admin/api/catalog/clear")
async def admin_catalog_clear(request: web.Request):
    _require_admin(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    group_key = str(payload.get("group_key", "")).strip()
    if not group_key:
        return web.json_response({"ok": False, "error": "Group key is required."}, status=400)

    await db.delete_catalog_entry(group_key)
    return web.json_response({"ok": True})


@routes.get("/admin/api/admin-users")
async def admin_users_list(request: web.Request):
    _require_admin(request)
    rows = await db.list_admin_users()
    return web.json_response(
        {
            "ok": True,
            "users": [
                {"username": username, "source": "env", "protected": True}
                for username in sorted(Telegram.ADMIN_CREDENTIALS.keys())
            ] + [
                {
                    "username": row.get("username", ""),
                    "source": "panel",
                    "protected": False,
                    "created_by": row.get("created_by", ""),
                }
                for row in rows
            ],
        }
    )


@routes.post("/admin/api/admin-users")
async def admin_users_create(request: web.Request):
    _require_admin(request)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request body."}, status=400)

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        return web.json_response({"ok": False, "error": "Username and password are required."}, status=400)
    if len(username) < 3:
        return web.json_response({"ok": False, "error": "Username must be at least 3 characters."}, status=400)
    if len(password) < 8:
        return web.json_response({"ok": False, "error": "Password must be at least 8 characters."}, status=400)
    if username in Telegram.ADMIN_CREDENTIALS:
        return web.json_response({"ok": False, "error": "That username is reserved by server config."}, status=409)

    await db.upsert_admin_user(
        username,
        hash_password(password),
        created_by=get_admin_username(request) or Telegram.ADMIN_USERNAME,
    )
    return web.json_response({"ok": True})


@routes.delete("/admin/api/admin-users/{username}")
async def admin_users_delete(request: web.Request):
    _require_admin(request)
    username = str(request.match_info.get("username", "")).strip()
    current_username = get_admin_username(request) or Telegram.ADMIN_USERNAME
    if not username:
        return web.json_response({"ok": False, "error": "Username is required."}, status=400)
    if username in Telegram.ADMIN_CREDENTIALS:
        return web.json_response({"ok": False, "error": "Protected server login users cannot be deleted here."}, status=403)
    if username == current_username:
        return web.json_response({"ok": False, "error": "You cannot delete the account you are currently using."}, status=403)

    result = await db.delete_admin_user(username)
    if not result.deleted_count:
        return web.json_response({"ok": False, "error": "Admin user not found."}, status=404)
    return web.json_response({"ok": True})


@routes.get("/playlist/{token}.m3u", allow_head=True)
async def serve_playlist(request: web.Request):
    playlist = await db.get_playlist(request.match_info["token"])
    if not playlist:
        raise web.HTTPNotFound(text="Playlist not found.")

    file_docs = await db.get_files_by_ids(playlist["user_id"], playlist.get("file_ids", []))
    playlist_buffer = build_playlist_buffer(file_docs, playlist.get("title", "filestream_playlist"))
    if playlist_buffer is None:
        raise web.HTTPNotFound(text="Playlist is empty.")

    return web.Response(
        body=playlist_buffer.getvalue(),
        content_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'inline; filename="{playlist_buffer.name}"'},
    )


@routes.get("/watch/{path}", allow_head=True)
async def watch_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return web.Response(text=await render_page(path), content_type="text/html")
    except InvalidHash as error:
        raise web.HTTPForbidden(text=error.message)
    except FIleNotFound as error:
        raise web.HTTPNotFound(text=error.message)
    except (AttributeError, BadStatusLine, ConnectionResetError) as error:
        traceback.print_exc()
        raise web.HTTPInternalServerError(text=str(error))


@routes.get("/dl/{path}", allow_head=True)
async def download_handler(request: web.Request):
    try:
        path = request.match_info["path"]
        return await media_streamer(request, path)
    except InvalidHash as error:
        raise web.HTTPForbidden(text=error.message)
    except FIleNotFound as error:
        raise web.HTTPNotFound(text=error.message)
    except (AttributeError, BadStatusLine, ConnectionResetError) as error:
        traceback.print_exc()
        raise web.HTTPInternalServerError(text=str(error))
    except Exception as error:
        traceback.print_exc()
        logging.critical(error.with_traceback(None))
        logging.debug(traceback.format_exc())
        raise web.HTTPInternalServerError(text=str(error))


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    value = range_header.strip()
    if not value.startswith("bytes="):
        raise ValueError("Unsupported range unit")

    start_text, end_text = value[6:].split("-", 1)

    if start_text == "" and end_text == "":
        raise ValueError("Invalid range")

    if start_text == "":
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Invalid suffix range")
        from_bytes = max(file_size - suffix_length, 0)
        until_bytes = file_size - 1
    else:
        from_bytes = int(start_text)
        until_bytes = int(end_text) if end_text else file_size - 1

    return from_bytes, until_bytes


async def media_streamer(request: web.Request, db_id: str):
    range_header = request.headers.get("Range", 0)
    file_doc = await db.get_file(db_id)
    if isinstance(file_doc, dict):
        file_doc = await _ensure_bot_file_id(file_doc)
    available_file_ids = file_doc.get("file_ids", {}) if isinstance(file_doc, dict) else {}

    preferred_indexes = [
        index for index, client in multi_clients.items()
        if str(client.id) in available_file_ids
    ]
    candidate_indexes = preferred_indexes or list(multi_clients.keys())
    index = min(candidate_indexes, key=lambda client_index: (work_loads.get(client_index, 0), client_index))
    faster_client = multi_clients[index]

    if Telegram.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.headers.get('X-FORWARDED-FOR', request.remote)}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect

    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(db_id, multi_clients)
    logging.debug("after calling get_file_properties")

    file_size = file_id.file_size

    try:
        if range_header:
            from_bytes, until_bytes = parse_range_header(range_header, file_size)
        else:
            from_bytes = request.http_range.start or 0
            until_bytes = (request.http_range.stop or file_size) - 1
    except ValueError:
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = (until_bytes // chunk_size) - (offset // chunk_size) + 1
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    mime_type = file_id.mime_type
    file_name = utils.get_name(file_id)
    disposition = "attachment"

    if not mime_type:
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    if mime_type.startswith(("video/", "audio/")):
        disposition = "inline"

    quoted_file_name = urllib.parse.quote(file_name)

    is_partial = bool(range_header)
    response_headers = {
        "Content-Type": f"{mime_type}",
        "Content-Length": str(req_length),
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quoted_file_name}",
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "X-Accel-Buffering": "no",
    }
    if is_partial:
        response_headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"

    response = web.StreamResponse(
        status=206 if is_partial else 200,
        headers=response_headers,
    )
    if request.method == "HEAD":
        await response.prepare(request)
        await response.write_eof()
        return response

    first_chunk = b""
    try:
        try:
            first_chunk = await anext(body)
        except FileReferenceExpired:
            logging.warning("Refreshing expired Telegram file reference for %s", db_id)
            tg_connect.drop_file_cache(db_id)
            file_id = await tg_connect.get_file_properties(db_id, multi_clients, force_refresh=True)
            body = tg_connect.yield_file(
                file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
            )
            first_chunk = await anext(body)
        except StopAsyncIteration:
            first_chunk = b""

        await response.prepare(request)
        if first_chunk:
            await response.write(first_chunk)

        async for chunk in body:
            await response.write(chunk)
    except (asyncio.CancelledError, ConnectionError, ConnectionResetError, BrokenPipeError):
        pass
    except FileReferenceExpired as error:
        logging.critical(error)
    finally:
        try:
            await response.write_eof()
        except (ConnectionError, ConnectionResetError, BrokenPipeError, RuntimeError):
            pass

    return response


async def _ensure_bot_file_id(file_doc: dict) -> dict:
    bot_client_id = str(FileStream.id)
    file_ids = file_doc.setdefault("file_ids", {})
    if bot_client_id in file_ids:
        normalization_failures.pop(str(file_doc.get("_id", "")), None)
        return file_doc

    source_chat_id = file_doc.get("source_chat_id")
    source_message_id = file_doc.get("source_message_id")
    if source_chat_id is None or source_message_id is None:
        return file_doc

    db_id = str(file_doc["_id"])
    last_failed_at = normalization_failures.get(db_id)
    if last_failed_at and time.time() - last_failed_at < NORMALIZATION_RETRY_TTL:
        return file_doc

    lock = normalization_locks.setdefault(db_id, asyncio.Lock())
    async with lock:
        refreshed = await db.get_file(db_id)
        if not isinstance(refreshed, dict):
            return file_doc

        refreshed_file_ids = refreshed.setdefault("file_ids", {})
        if bot_client_id in refreshed_file_ids:
            normalization_failures.pop(db_id, None)
            return refreshed

        try:
            copied = await FileStream.copy_message(
                Telegram.FLOG_CHANNEL,
                int(source_chat_id),
                int(source_message_id),
            )
            if not copied:
                return refreshed

            copied_message = await FileStream.get_messages(Telegram.FLOG_CHANNEL, copied.id)
            media = get_media_from_message(copied_message)
            copied_file_id = getattr(media, "file_id", "")
            if not copied_file_id:
                return refreshed

            refreshed_file_ids[bot_client_id] = copied_file_id
            await db.update_file_ids(db_id, refreshed_file_ids)
            refreshed["file_ids"] = refreshed_file_ids
            normalization_failures.pop(db_id, None)
            logging.info("Normalized scanned file %s onto bot delivery path", db_id)
            return refreshed
        except Exception as error:
            normalization_failures[db_id] = time.time()
            logging.warning("Could not normalize scanned file %s: %s", db_id, error)
            return refreshed
