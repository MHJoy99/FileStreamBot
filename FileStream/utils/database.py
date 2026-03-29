import pymongo
import secrets
import time
import re
import asyncio
import motor.motor_asyncio
from bson.objectid import ObjectId
from bson.errors import InvalidId
from FileStream.server.exceptions import FIleNotFound

class Database:
    _index_lock = None
    _indexed_databases = set()

    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.black = self.db.blacklist
        self.file = self.db.file
        self.playlists = self.db.playlists
        self.tg_bundles = self.db.telegram_bundles
        self.sources = self.db.library_sources
        self.catalog = self.db.catalog
        self.admin_users = self.db.admin_users

    async def ensure_indexes(self):
        db_name = self.db.name
        if db_name in self._indexed_databases:
            return

        if Database._index_lock is None:
            Database._index_lock = asyncio.Lock()

        async with Database._index_lock:
            if db_name in self._indexed_databases:
                return

            await asyncio.gather(
                self.col.create_index([("id", pymongo.ASCENDING)]),
                self.black.create_index([("id", pymongo.ASCENDING)]),
                self.file.create_index([("user_id", pymongo.ASCENDING), ("time", pymongo.DESCENDING)]),
                self.file.create_index([("user_id", pymongo.ASCENDING), ("source_chat_id", pymongo.ASCENDING), ("time", pymongo.DESCENDING)]),
                self.file.create_index([("user_id", pymongo.ASCENDING), ("file_name", pymongo.ASCENDING)]),
                self.file.create_index([("user_id", pymongo.ASCENDING), ("file_unique_id", pymongo.ASCENDING)]),
                self.file.create_index([("source_chat_id", pymongo.ASCENDING), ("source_message_id", pymongo.ASCENDING)]),
                self.playlists.create_index([("token", pymongo.ASCENDING)]),
                self.tg_bundles.create_index([("token", pymongo.ASCENDING)]),
                self.sources.create_index([("chat_id", pymongo.ASCENDING)]),
                self.sources.create_index([("enabled", pymongo.ASCENDING), ("chat_title", pymongo.ASCENDING)]),
                self.catalog.create_index([("key", pymongo.ASCENDING)]),
                self.catalog.create_index([("updated_at", pymongo.DESCENDING)]),
                self.admin_users.create_index([("username", pymongo.ASCENDING)], unique=True),
            )
            self._indexed_databases.add(db_name)

#---------------------[ NEW USER ]---------------------#
    def new_user(self, id):
        return dict(
            id=id,
            join_date=time.time(),
            Links=0
        )

# ---------------------[ ADD USER ]---------------------#
    async def add_user(self, id):
        user = self.new_user(id)
        await self.col.insert_one(user)

# ---------------------[ GET USER ]---------------------#
    async def get_user(self, id):
        user = await self.col.find_one({'id': int(id)})
        return user

# ---------------------[ CHECK USER ]---------------------#
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    async def get_all_users(self):
        all_users = self.col.find({})
        return all_users

# ---------------------[ REMOVE USER ]---------------------#
    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})

# ---------------------[ BAN, UNBAN USER ]---------------------#
    def black_user(self, id):
        return dict(
            id=id,
            ban_date=time.time()
        )

    async def ban_user(self, id):
        user = self.black_user(id)
        await self.black.insert_one(user)

    async def unban_user(self, id):
        await self.black.delete_one({'id': int(id)})

    async def is_user_banned(self, id):
        user = await self.black.find_one({'id': int(id)})
        return True if user else False

    async def total_banned_users_count(self):
        count = await self.black.count_documents({})
        return count
        
# ---------------------[ ADD FILE TO DB ]---------------------#
    async def add_file(self, file_info):
        file_info["time"] = time.time()
        fetch_old = await self.get_file_by_fileuniqueid(file_info["user_id"], file_info["file_unique_id"])
        if fetch_old:
            return fetch_old["_id"]
        await self.count_links(file_info["user_id"], "+")
        return (await self.file.insert_one(file_info)).inserted_id

# ---------------------[ FIND FILE IN DB ]---------------------#
    async def find_files(self, user_id, range):
        user_files=self.file.find({"user_id": user_id})
        user_files.skip(range[0] - 1)
        user_files.limit(range[1] - range[0] + 1)
        user_files.sort('_id', pymongo.DESCENDING)
        total_files = await self.file.count_documents({"user_id": user_id})
        return user_files, total_files

    async def get_all_files_by_user(self, user_id, sort_field="time", sort_order=pymongo.ASCENDING):
        return self.file.find({"user_id": user_id}).sort(sort_field, sort_order)

    def _build_search_pattern(self, search_query):
        normalized = str(search_query or "").strip()
        if not normalized:
            return None

        tokens = [re.escape(token) for token in re.split(r"[^A-Za-z0-9]+", normalized) if token]
        if not tokens:
            return re.escape(normalized)

        # Treat spaces, dots, underscores, and dashes as equivalent separators
        # so searches like "the order" match "The_Order" and "The.Order".
        return r"[\s._-]*".join(tokens)

    async def get_files_page(self, user_id, page=1, per_page=25, search_query="", source_chat_id=None):
        page = max(int(page), 1)
        per_page = max(int(per_page), 1)
        skip = (page - 1) * per_page
        query = {"user_id": user_id}
        if search_query:
            query["file_name"] = {"$regex": self._build_search_pattern(search_query), "$options": "i"}
        if source_chat_id not in (None, "", "all"):
            try:
                query["source_chat_id"] = int(source_chat_id)
            except (TypeError, ValueError):
                query["source_chat_id"] = source_chat_id

        cursor = self.file.find(query).sort("_id", pymongo.DESCENDING).skip(skip).limit(per_page)
        files = [file_info async for file_info in cursor]
        total_files = await self.file.count_documents(query)
        return files, total_files

    async def get_library_sources(self, enabled_only=False):
        query = {"enabled": True} if enabled_only else {}
        cursor = self.sources.find(query).sort("chat_title", pymongo.ASCENDING)
        return [source async for source in cursor]

    async def get_library_source(self, chat_id):
        return await self.sources.find_one({"chat_id": int(chat_id)})

    async def upsert_library_source(
        self,
        chat_id,
        chat_title="",
        auto_sync=True,
        enabled=True,
        last_message_id=0,
        last_synced_at=None,
        last_error="",
    ):
        now = time.time()
        payload = {
            "chat_id": int(chat_id),
            "chat_title": chat_title or str(chat_id),
            "auto_sync": bool(auto_sync),
            "enabled": bool(enabled),
            "last_message_id": int(last_message_id or 0),
            "last_synced_at": last_synced_at,
            "last_error": last_error or "",
            "updated_at": now,
        }
        await self.sources.update_one(
            {"chat_id": int(chat_id)},
            {
                "$set": payload,
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return await self.get_library_source(chat_id)

    async def update_library_source(self, chat_id, **fields):
        payload = dict(fields)
        payload["updated_at"] = time.time()
        await self.sources.update_one({"chat_id": int(chat_id)}, {"$set": payload})
        return await self.get_library_source(chat_id)

    async def get_source_overview(self, user_id):
        pipeline = [
            {"$match": {"user_id": user_id, "source_chat_id": {"$exists": True}}},
            {
                "$group": {
                    "_id": "$source_chat_id",
                    "chat_title": {"$last": "$source_chat_title"},
                    "count": {"$sum": 1},
                    "total_size": {"$sum": "$file_size"},
                }
            },
            {"$sort": {"count": -1, "chat_title": 1}},
        ]
        return await self.file.aggregate(pipeline).to_list(length=None)

    async def get_source_bootstrap_rows(self, user_id):
        pipeline = [
            {"$match": {"user_id": user_id, "source_chat_id": {"$exists": True}, "source_message_id": {"$exists": True}}},
            {
                "$group": {
                    "_id": "$source_chat_id",
                    "chat_title": {"$last": "$source_chat_title"},
                    "last_message_id": {"$max": "$source_message_id"},
                }
            },
            {"$sort": {"chat_title": 1}},
        ]
        return await self.file.aggregate(pipeline).to_list(length=None)

    def _build_file_query(self, user_id, search_query="", source_chat_id=None):
        query = {"user_id": user_id}
        if search_query:
            query["file_name"] = {"$regex": self._build_search_pattern(search_query), "$options": "i"}
        if source_chat_id not in (None, "", "all"):
            try:
                query["source_chat_id"] = int(source_chat_id)
            except (TypeError, ValueError):
                query["source_chat_id"] = source_chat_id
        return query

    async def get_filtered_files(self, user_id, search_query="", source_chat_id=None, limit=None, projection=None):
        query = self._build_file_query(user_id, search_query, source_chat_id)
        cursor = self.file.find(query, projection).sort("_id", pymongo.DESCENDING)
        if limit:
            cursor = cursor.limit(limit)
        return [file_info async for file_info in cursor]

    async def count_filtered_files(self, user_id, search_query="", source_chat_id=None):
        query = self._build_file_query(user_id, search_query, source_chat_id)
        return await self.file.count_documents(query)

    async def get_filtered_files_page(
        self,
        user_id,
        page=1,
        per_page=100,
        search_query="",
        source_chat_id=None,
        sort_field="time",
        sort_order=pymongo.DESCENDING,
        projection=None,
    ):
        page = max(int(page), 1)
        per_page = max(int(per_page), 1)
        skip = (page - 1) * per_page
        query = self._build_file_query(user_id, search_query, source_chat_id)
        cursor = self.file.find(query, projection).sort(sort_field, sort_order).skip(skip).limit(per_page)
        files = [file_info async for file_info in cursor]
        total_files = await self.file.count_documents(query)
        return files, total_files

    async def get_files_by_ids(self, user_id, file_ids):
        object_ids = []
        for file_id in file_ids:
            try:
                object_ids.append(ObjectId(file_id))
            except InvalidId:
                continue

        if not object_ids:
            return []

        cursor = self.file.find({"user_id": user_id, "_id": {"$in": object_ids}})
        files = [file_info async for file_info in cursor]
        files_by_id = {str(file_info["_id"]): file_info for file_info in files}
        return [files_by_id[file_id] for file_id in file_ids if file_id in files_by_id]

    async def total_file_size(self, user_id=None):
        match = {"user_id": user_id} if user_id is not None else {}
        result = await self.file.aggregate(
            [
                {"$match": match},
                {"$group": {"_id": None, "total": {"$sum": "$file_size"}}},
            ]
        ).to_list(length=1)
        return int(result[0]["total"]) if result else 0

    async def create_playlist(self, user_id, title, file_ids):
        payload = {
            "token": secrets.token_urlsafe(24),
            "user_id": user_id,
            "title": title,
            "file_ids": file_ids,
            "created_at": time.time(),
        }
        await self.playlists.insert_one(payload)
        return payload

    async def get_playlist(self, token):
        return await self.playlists.find_one({"token": token})

    async def create_tg_bundle(self, user_id, title, file_ids):
        payload = {
            "token": secrets.token_urlsafe(24),
            "user_id": user_id,
            "title": title,
            "file_ids": file_ids,
            "created_at": time.time(),
        }
        await self.tg_bundles.insert_one(payload)
        return payload

    async def get_tg_bundle(self, token):
        return await self.tg_bundles.find_one({"token": str(token)})

    async def get_file(self, _id):
        try:
            file_info=await self.file.find_one({"_id": ObjectId(_id)})
            if not file_info:
                raise FIleNotFound
            return file_info
        except InvalidId:
            raise FIleNotFound
    
    async def get_file_by_fileuniqueid(self, id, file_unique_id, many=False):
        if many:
            return self.file.find({"file_unique_id": file_unique_id})
        else:
            file_info=await self.file.find_one({"user_id": id, "file_unique_id": file_unique_id})
        if file_info:
            return file_info
        return False

# ---------------------[ TOTAL FILES ]---------------------#
    async def total_files(self, id=None):
        if id:
            return await self.file.count_documents({"user_id": id})
        return await self.file.count_documents({})

# ---------------------[ DELETE FILES ]---------------------#
    async def delete_one_file(self, _id):
        await self.file.delete_one({'_id': ObjectId(_id)})

# ---------------------[ UPDATE FILES ]---------------------#
    async def update_file_ids(self, _id, file_ids: dict):
        await self.file.update_one({"_id": ObjectId(_id)}, {"$set": {"file_ids": file_ids}})

    async def get_catalog_entry(self, key):
        return await self.catalog.find_one({"key": key})

    async def get_catalog_entries(self, keys):
        unique_keys = [key for key in dict.fromkeys(keys or []) if key]
        if not unique_keys:
            return {}
        cursor = self.catalog.find({"key": {"$in": unique_keys}})
        entries = [entry async for entry in cursor]
        return {entry["key"]: entry for entry in entries}

    async def upsert_catalog_entry(self, key, payload):
        document = dict(payload)
        document["key"] = key
        document["updated_at"] = time.time()
        await self.catalog.update_one(
            {"key": key},
            {
                "$set": document,
                "$setOnInsert": {"created_at": time.time()},
            },
            upsert=True,
        )
        return await self.get_catalog_entry(key)

    async def delete_catalog_entry(self, key):
        return await self.catalog.delete_one({"key": key})

    async def get_admin_user(self, username):
        return await self.admin_users.find_one({"username": str(username)})

    async def list_admin_users(self):
        cursor = self.admin_users.find({}).sort("username", pymongo.ASCENDING)
        return [user async for user in cursor]

    async def upsert_admin_user(self, username, password_hash, created_by=""):
        now = time.time()
        payload = {
            "username": str(username).strip(),
            "password_hash": str(password_hash),
            "created_by": str(created_by or ""),
            "updated_at": now,
        }
        await self.admin_users.update_one(
            {"username": payload["username"]},
            {"$set": payload, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return await self.get_admin_user(payload["username"])

    async def delete_admin_user(self, username):
        return await self.admin_users.delete_one({"username": str(username).strip()})

# ---------------------[ PAID SYS ]---------------------#
#     async def link_available(self, id):
#         user = await self.col.find_one({"id": id})
#         if user.get("Plan") == "Plus":
#             return "Plus"
#         elif user.get("Plan") == "Free":
#             files = await self.file.count_documents({"user_id": id})
#             if files < 11:
#                 return True
#             return False
        
    async def count_links(self, id, operation: str):
        if operation == "-":
            await self.col.update_one({"id": id}, {"$inc": {"Links": -1}})
        elif operation == "+":
            await self.col.update_one({"id": id}, {"$inc": {"Links": 1}})
