from io import BytesIO

from FileStream.config import Server


def _clean_title(value: str, fallback: str) -> str:
    cleaned = " ".join((value or "").replace("\n", " ").split()).strip()
    return cleaned or fallback


def build_playlist_text(file_docs, playlist_name: str = "FileStream Playlist") -> str:
    lines = ["#EXTM3U", f"#PLAYLIST:{_clean_title(playlist_name, 'FileStream Playlist')}"]
    for file_info in file_docs:
        file_name = _clean_title(file_info.get("file_name", ""), "Telegram File")
        lines.append(f"#EXTINF:-1,{file_name}")
        lines.append(f"{Server.URL}dl/{file_info['_id']}")
    return "\n".join(lines) + "\n"


def build_playlist_buffer(file_docs, playlist_name: str = "filestream_playlist") -> BytesIO | None:
    file_docs = list(file_docs)
    if not file_docs:
        return None

    playlist_data = build_playlist_text(file_docs, playlist_name)
    playlist_file = BytesIO(playlist_data.encode("utf-8"))
    safe_name = _clean_title(playlist_name, "filestream_playlist").replace(" ", "_")
    playlist_file.name = f"{safe_name}.m3u"
    return playlist_file
