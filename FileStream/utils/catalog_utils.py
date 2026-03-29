import asyncio
import re
from collections import OrderedDict
from contextlib import nullcontext

import aiohttp

from FileStream.config import Telegram

SEASON_EPISODE_PATTERNS = [
    re.compile(r"\[?\s*[Ss](?P<season>\d{1,2})\s*[-_. ]?[Ee](?P<episode>\d{1,4})\s*\]?", re.IGNORECASE),
    re.compile(r"(?P<season>\d{1,2})[ ._-]*[xXeE][ ._-]*(?P<episode>\d{1,4})", re.IGNORECASE),
]
SEASON_PACK_PATTERN = re.compile(r"(?:^|[ ._\-\[])[Ss](?P<season>\d{1,2})(?=$|[ ._\-\]])")
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
HANDLE_PATTERN = re.compile(r"@\w+")
LEADING_HANDLES_PATTERN = re.compile(r"^(?:@\w+[_ .-]*)+")
BRACKET_PATTERN = re.compile(r"[\(\{].*?[\)\}]")
SQUARE_BRACKET_PATTERN = re.compile(r"\[[^\]]*\]")
NOISE_PATTERN = re.compile(
    r"\b("
    r"1080p|2160p|720p|480p|x264|x265|h264|h265|hevc|bluray|blu-ray|webrip|web-dl|webdl|amzn|nf|dsnp|hdr|dv|"
    r"ddp[0-9.]*|aac[0-9.]*|esub|multi|proper|repack|remux|shortbredhd|shortbred|brrip|hdrip|complete|season|"
    r"series|episode|ep|combined|pack|sub|dubbed|eng|english|subs|rip|uncut|v\d+|av1|joy"
    r"|mkv|mp4|avi|wmv"
    r")\b",
    re.IGNORECASE,
)
MULTISPACE_PATTERN = re.compile(r"\s+")
PROMO_TOKEN_PATTERN = re.compile(
    r"^(?:"
    r"tg|new|movies?|movie|firstontg|1stontg|mhjoybots?|mhjoymovies?|bdmusicboss|net|kdrama|highway100bittu"
    r")$",
    re.IGNORECASE,
)
ALPHANUMERIC_HASH_PATTERN = re.compile(r"^[a-f0-9]{16,}$", re.IGNORECASE)
KNOWN_PREFIXES_PATTERN = re.compile(r"^(?:tg|mhjoybots?|mhjoymovies?|bdmusicboss|highway100bittu)\W*", re.IGNORECASE)

catalog_locks = {}


def _get_db():
    from FileStream.utils.database import Database

    return Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)


def _clean_title(raw_name: str) -> str:
    title = raw_name.rsplit(".", 1)[0]
    title = re.sub(LEADING_HANDLES_PATTERN, " ", title)
    title = re.sub(HANDLE_PATTERN, " ", title)
    title = re.sub(BRACKET_PATTERN, " ", title)
    title = re.sub(SQUARE_BRACKET_PATTERN, " ", title)
    title = re.sub(r"[._]+", " ", title)
    for pattern in SEASON_EPISODE_PATTERNS:
        title = re.sub(pattern, " ", title)
    title = re.sub(SEASON_PACK_PATTERN, " ", title)
    title = re.sub(YEAR_PATTERN, " ", title, count=1)
    title = re.sub(NOISE_PATTERN, " ", title)
    title = re.sub(r"\b\d{1,4}\b", " ", title)
    title = MULTISPACE_PATTERN.sub(" ", title).strip(" -._")
    return title


def _clean_title_loose(raw_name: str) -> str:
    title = raw_name.rsplit(".", 1)[0]
    title = title.replace("@", " ")
    title = re.sub(BRACKET_PATTERN, " ", title)
    title = re.sub(SQUARE_BRACKET_PATTERN, " ", title)
    title = re.sub(r"[._]+", " ", title)
    for pattern in SEASON_EPISODE_PATTERNS:
        title = re.sub(pattern, " ", title)
    title = re.sub(SEASON_PACK_PATTERN, " ", title)
    title = re.sub(YEAR_PATTERN, " ", title, count=1)
    title = re.sub(NOISE_PATTERN, " ", title)
    title = re.sub(r"\b\d{1,4}\b", " ", title)
    title = MULTISPACE_PATTERN.sub(" ", title).strip(" -._")
    return title


def _strip_prefixed_handles(raw_name: str) -> str:
    value = raw_name.strip()
    while value.startswith("@"):
        value = value[1:]
        if "_" not in value:
            break
        _, value = value.split("_", 1)
        value = value.lstrip(" ._-")
    return re.sub(r"^[^A-Za-z0-9]+", "", value)


def _drop_promo_tokens(title: str) -> str:
    tokens = [token for token in re.split(r"[\s._-]+", title) if token]
    while len(tokens) > 1 and (PROMO_TOKEN_PATTERN.match(tokens[0]) or (tokens[0].isupper() and len(tokens[0]) <= 3)):
        tokens.pop(0)
    while len(tokens) > 1 and PROMO_TOKEN_PATTERN.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def _strip_known_prefixes(title: str) -> str:
    return re.sub(KNOWN_PREFIXES_PATTERN, "", title).strip()


def _season_episode_match(file_name: str):
    for pattern in SEASON_EPISODE_PATTERNS:
        match = pattern.search(file_name)
        if match:
            return match
    return None


def _looks_like_hash(name: str) -> bool:
    stem = name.rsplit(".", 1)[0]
    stem = stem.strip()
    return bool(ALPHANUMERIC_HASH_PATTERN.fullmatch(stem))


def _is_meaningful_title(title: str) -> bool:
    if not (title and len(title) >= 3 and re.search(r"[A-Za-z]", title)):
        return False
    alpha_only = re.sub(r"[^A-Za-z]", "", title)
    tokens = [token for token in title.split() if re.search(r"[A-Za-z]", token)]
    if len(tokens) <= 1 and len(alpha_only) <= 3:
        return False
    return True


def _candidate_score(title: str) -> tuple[int, int, int]:
    if not _is_meaningful_title(title):
        return (-1, -1, -1)
    tokens = [token for token in title.split() if re.search(r"[A-Za-z]", token)]
    alpha_chars = len(re.sub(r"[^A-Za-z]", "", title))
    penalty = 1 if len(tokens) == 1 and len(tokens[0]) <= 3 and tokens[0].isupper() else 0
    return (len(tokens) - penalty, alpha_chars - penalty * 10, len(title))


def _has_complete_hint(stem: str) -> bool:
    tokens = [token.lower() for token in re.split(r"[\s._-]+", stem) if token]
    return any(token in {"complete", "combined", "season", "series", "pack"} for token in tokens)


def _best_title_from_sources(*sources: str) -> str:
    best_title = ""
    best_score = (-1, -1, -1)
    for source in sources:
        if not source:
            continue
        stripped_source = _strip_prefixed_handles(source)
        strict_candidate = _strip_known_prefixes(_drop_promo_tokens(_clean_title(stripped_source)))
        cleaned_variants = [strict_candidate]
        if "@" not in source or not _is_meaningful_title(strict_candidate):
            cleaned_variants.append(_strip_known_prefixes(_drop_promo_tokens(_clean_title_loose(stripped_source))))
        for candidate in cleaned_variants:
            score = _candidate_score(candidate)
            if score > best_score:
                best_title = candidate
                best_score = score
    return best_title


def parse_media_name(file_name: str) -> dict:
    if _looks_like_hash(file_name):
        stem = file_name.rsplit(".", 1)[0]
        normalized_title = stem.lower()
        return {
            "title": stem,
            "normalized_title": normalized_title,
            "media_kind": "movie",
            "year": None,
            "season": None,
            "episode": None,
            "group_key": f"movie:{normalized_title}:na",
        }

    season = episode = None
    stem = file_name.rsplit(".", 1)[0]
    season_match = _season_episode_match(stem)
    if season_match:
        season = int(season_match.group("season"))
        episode = int(season_match.group("episode"))

    season_pack_match = SEASON_PACK_PATTERN.search(stem)
    year_match = YEAR_PATTERN.search(stem)
    year = int(year_match.group(0)) if year_match else None
    alternate_title_source = ""
    if season_match:
        left_source = stem[:season_match.start()]
        right_source = stem[season_match.end():]
        title_source = left_source if season_match.start() > 3 else right_source
        alternate_title_source = right_source if title_source == left_source else left_source
        year = None
    elif season_pack_match and _has_complete_hint(stem):
        season = int(season_pack_match.group("season"))
        episode = None
        left_source = stem[:season_pack_match.start()]
        right_source = stem[season_pack_match.end():]
        title_source = left_source if season_pack_match.start() > 3 else right_source
        alternate_title_source = right_source if title_source == left_source else left_source
        year = None
    elif year_match:
        title_source = stem[:year_match.start()]
    else:
        title_source = stem

    if season is not None:
        title = _best_title_from_sources(title_source)
        if not _is_meaningful_title(title) and alternate_title_source:
            title = _best_title_from_sources(alternate_title_source)
        if not _is_meaningful_title(title):
            title = _best_title_from_sources(stem)
    else:
        title = _best_title_from_sources(title_source, alternate_title_source, stem)
    if not _is_meaningful_title(title):
        title = stem.replace("_", " ").replace(".", " ").strip()
    normalized_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    media_kind = "tv" if season is not None else "movie"
    group_key = f"{media_kind}:{normalized_title}:{year or 'na'}"

    return {
        "title": title,
        "normalized_title": normalized_title,
        "media_kind": media_kind,
        "year": year,
        "season": season,
        "episode": episode,
        "group_key": group_key,
    }


async def _fetch_tmdb_json(session: aiohttp.ClientSession, path: str, params: dict):
    headers = {}
    if Telegram.TMDB_READ_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {Telegram.TMDB_READ_ACCESS_TOKEN}"
    async with session.get(f"https://api.themoviedb.org/3/{path}", params=params, headers=headers, timeout=20) as response:
        if response.status != 200:
            return None
        return await response.json()


async def fetch_tmdb_metadata(parsed: dict, session: aiohttp.ClientSession | None = None) -> dict | None:
    if not Telegram.TMDB_API_KEY:
        return None

    media_kind = parsed["media_kind"]
    title = parsed["title"]
    year = parsed.get("year")
    search_path = "search/tv" if media_kind == "tv" else "search/movie"
    params = {
        "query": title,
        "include_adult": "false",
    }
    if Telegram.TMDB_API_KEY and not Telegram.TMDB_READ_ACCESS_TOKEN:
        params["api_key"] = Telegram.TMDB_API_KEY
    if year:
        params["first_air_date_year" if media_kind == "tv" else "year"] = year

    session_context = nullcontext(session) if session else aiohttp.ClientSession()
    async with session_context as active_session:
        payload = await _fetch_tmdb_json(active_session, search_path, params)
        if not payload or not payload.get("results"):
            if media_kind == "movie":
                payload = await _fetch_tmdb_json(
                    active_session,
                    "search/tv",
                    {
                        "query": title,
                        "include_adult": "false",
                        **({"api_key": Telegram.TMDB_API_KEY} if Telegram.TMDB_API_KEY and not Telegram.TMDB_READ_ACCESS_TOKEN else {}),
                    },
                )
                media_kind = "tv" if payload and payload.get("results") else media_kind
            elif media_kind == "tv":
                payload = await _fetch_tmdb_json(
                    active_session,
                    "search/movie",
                    {
                        "query": title,
                        "include_adult": "false",
                        **({"api_key": Telegram.TMDB_API_KEY} if Telegram.TMDB_API_KEY and not Telegram.TMDB_READ_ACCESS_TOKEN else {}),
                    },
                )
                media_kind = "movie" if payload and payload.get("results") else media_kind

        if not payload or not payload.get("results"):
            return None

        best = payload["results"][0]
        image_base = "https://image.tmdb.org/t/p/"
        poster_path = best.get("poster_path")
        backdrop_path = best.get("backdrop_path")
        return {
            "title": best.get("name") or best.get("title") or title,
            "overview": best.get("overview", ""),
            "tmdb_id": best.get("id"),
            "tmdb_media_type": media_kind,
            "poster_url": f"{image_base}w500{poster_path}" if poster_path else "",
            "backdrop_url": f"{image_base}w780{backdrop_path}" if backdrop_path else "",
            "release_year": (best.get("first_air_date") or best.get("release_date") or "")[:4],
        }


async def search_tmdb_candidates(query: str, media_kind: str = "tv", limit: int = 8) -> list[dict]:
    if not Telegram.TMDB_API_KEY:
        return []

    search_path = "search/tv" if media_kind == "tv" else "search/movie"
    params = {
        "query": query,
        "include_adult": "false",
    }
    if Telegram.TMDB_API_KEY and not Telegram.TMDB_READ_ACCESS_TOKEN:
        params["api_key"] = Telegram.TMDB_API_KEY

    async with aiohttp.ClientSession() as session:
        payload = await _fetch_tmdb_json(session, search_path, params)
        results = payload.get("results", []) if payload else []
        image_base = "https://image.tmdb.org/t/p/"
        candidates = []
        for item in results[:limit]:
            poster_path = item.get("poster_path")
            backdrop_path = item.get("backdrop_path")
            candidates.append(
                {
                    "title": item.get("name") or item.get("title") or query,
                    "overview": item.get("overview", ""),
                    "tmdb_id": item.get("id"),
                    "tmdb_media_type": media_kind,
                    "poster_url": f"{image_base}w500{poster_path}" if poster_path else "",
                    "backdrop_url": f"{image_base}w780{backdrop_path}" if backdrop_path else "",
                    "release_year": (item.get("first_air_date") or item.get("release_date") or "")[:4],
                }
            )
        return candidates


async def fetch_tmdb_by_id(tmdb_id: int | str, media_kind: str = "tv") -> dict | None:
    if not Telegram.TMDB_API_KEY:
        return None

    media_kind = "tv" if str(media_kind).lower() == "tv" else "movie"
    params = {}
    if Telegram.TMDB_API_KEY and not Telegram.TMDB_READ_ACCESS_TOKEN:
        params["api_key"] = Telegram.TMDB_API_KEY

    async with aiohttp.ClientSession() as session:
        payload = await _fetch_tmdb_json(session, f"{media_kind}/{int(tmdb_id)}", params)
        if not payload:
            return None

        image_base = "https://image.tmdb.org/t/p/"
        poster_path = payload.get("poster_path")
        backdrop_path = payload.get("backdrop_path")
        return {
            "title": payload.get("name") or payload.get("title") or "",
            "overview": payload.get("overview", ""),
            "tmdb_id": payload.get("id"),
            "tmdb_media_type": media_kind,
            "poster_url": f"{image_base}w500{poster_path}" if poster_path else "",
            "backdrop_url": f"{image_base}w780{backdrop_path}" if backdrop_path else "",
            "release_year": (payload.get("first_air_date") or payload.get("release_date") or "")[:4],
        }


async def ensure_catalog_metadata(parsed: dict, session: aiohttp.ClientSession | None = None) -> dict:
    db = _get_db()
    key = parsed["group_key"]
    existing = await db.get_catalog_entry(key)
    if existing and (existing.get("locked") or existing.get("poster_url") is not None):
        return existing

    lock = catalog_locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = await db.get_catalog_entry(key)
        if existing and (existing.get("locked") or existing.get("poster_url") is not None):
            return existing

        metadata = await fetch_tmdb_metadata(parsed, session=session)
        payload = {
            "title": parsed["title"],
            "normalized_title": parsed["normalized_title"],
            "media_kind": parsed["media_kind"],
            "year": parsed.get("year"),
            "poster_url": "",
            "backdrop_url": "",
            "overview": "",
            "tmdb_id": None,
            "tmdb_media_type": parsed["media_kind"],
            "release_year": str(parsed.get("year") or ""),
            "lock_mode": "auto",
        }
        if metadata:
            payload.update(metadata)
        return await db.upsert_catalog_entry(key, payload)


async def build_library_groups(files: list[dict], page: int, per_page: int = 18, confidence_filter: str = "all") -> dict:
    grouped = OrderedDict()
    db = _get_db()
    for file_info in files:
        parsed = parse_media_name(file_info.get("file_name", ""))
        group = grouped.setdefault(
            parsed["group_key"],
            {
                "key": parsed["group_key"],
                "parsed": parsed,
                "title": parsed["title"],
                "media_kind": parsed["media_kind"],
                "year": parsed.get("year"),
                "count": 0,
                "files": [],
                "total_size": 0,
                "source_titles": set(),
            },
        )
        group["count"] += 1
        group["total_size"] += int(file_info.get("file_size", 0) or 0)
        source_title = file_info.get("source_chat_title") or "Manual Upload"
        group["source_titles"].add(source_title)
        group["files"].append(
            {
                "id": str(file_info["_id"]),
                "name": file_info.get("file_name", "Telegram File"),
                "source_chat_title": source_title,
                "source_chat_id": str(file_info.get("source_chat_id", "")),
                "created_at": file_info.get("time"),
                "file_size": int(file_info.get("file_size", 0) or 0),
                "season": parsed.get("season"),
                "episode": parsed.get("episode"),
            }
        )

    ordered_groups = sorted(
        grouped.values(),
        key=lambda item: (
            0 if item["media_kind"] == "tv" else 1,
            item["title"].lower(),
            -(item["year"] or 0),
        ),
    )

    catalog_map = {}
    if confidence_filter != "all":
        catalog_map = await db.get_catalog_entries([group["key"] for group in ordered_groups])
        filtered_groups = []
        for group in ordered_groups:
            existing = catalog_map.get(group["key"])
            if existing and existing.get("poster_url") and existing.get("overview"):
                confidence = "strong"
            elif existing and (existing.get("poster_url") or existing.get("backdrop_url") or existing.get("title")):
                confidence = "medium"
            else:
                confidence = "filename"
            group["confidence"] = confidence
            if confidence_filter == "trusted" and confidence in {"strong", "medium"}:
                filtered_groups.append(group)
            elif confidence_filter == "review" and confidence in {"medium", "filename"}:
                filtered_groups.append(group)
            elif confidence_filter == "filename" and confidence == "filename":
                filtered_groups.append(group)
        ordered_groups = filtered_groups

    total_groups = len(ordered_groups)
    total_pages = max(1, (total_groups + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)
    visible_groups = ordered_groups[(page - 1) * per_page: page * per_page]

    semaphore = asyncio.Semaphore(6)

    async def _load_group_metadata(group):
        async with semaphore:
            return await ensure_catalog_metadata(group["parsed"], session=session)

    async with aiohttp.ClientSession() as session:
        metadata_rows = await asyncio.gather(*(_load_group_metadata(group) for group in visible_groups))

    for group, metadata in zip(visible_groups, metadata_rows):
        group["display_title"] = metadata.get("title") or group["title"]
        group["overview"] = metadata.get("overview", "")
        group["poster_url"] = metadata.get("poster_url", "")
        group["backdrop_url"] = metadata.get("backdrop_url", "")
        group["release_year"] = metadata.get("release_year") or (str(group["year"]) if group["year"] else "")
        group["locked"] = bool(metadata.get("locked"))
        group["lock_mode"] = metadata.get("lock_mode", "tmdb" if metadata.get("locked") else "auto")
        group["tmdb_id"] = metadata.get("tmdb_id")
        group["tmdb_media_type"] = metadata.get("tmdb_media_type") or group["media_kind"]
        if group["poster_url"] and group["overview"]:
            group["confidence"] = "strong"
        elif group["poster_url"] or group["backdrop_url"] or metadata.get("title"):
            group["confidence"] = "medium"
        else:
            group["confidence"] = "filename"
        group["source_titles"] = sorted(group["source_titles"])
        group["files"].sort(
            key=lambda item: (
                item["season"] if item["season"] is not None else 999,
                item["episode"] if item["episode"] is not None else 999,
                item["name"].lower(),
            )
        )

    return {
        "groups": visible_groups,
        "total_groups": total_groups,
        "total_pages": total_pages,
        "current_page": page,
    }
