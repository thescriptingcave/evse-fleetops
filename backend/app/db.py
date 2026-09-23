"""Asyncio Couchbase store. Thin async wrapper over acouchbase."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, AsyncIterator, Callable

from couchbase.exceptions import CasMismatchException, DocumentExistsException, DocumentNotFoundException

from .config import get_settings


class Store:
    def __init__(self) -> None:
        from .config import Settings

        self.settings: Settings = get_settings()
        self._cluster: Any | None = None
        self._bucket: Any | None = None
        self._collections: dict[str, Any] = {}

    async def connect(self) -> None:
        from acouchbase.cluster import Cluster
        from couchbase.auth import PasswordAuthenticator
        from couchbase.options import ClusterOptions, ClusterTimeoutOptions

        if self._bucket is not None:
            return
        auth = PasswordAuthenticator(self.settings.cb_username, self.settings.cb_password)
        opts = ClusterOptions(auth, timeout_options=ClusterTimeoutOptions(timeout=timedelta(seconds=15)))
        cluster = await Cluster.connect(self.settings.connection_string, opts)
        try:
            bucket = cluster.bucket(self.settings.bucket)
            await bucket.on_connect()
        except Exception:
            # Don't keep a half-open cluster around: a retry must start from scratch.
            await cluster.close()
            raise
        self._cluster = cluster
        self._bucket = bucket
        for name in self.settings.collection_names:
            self._collections[name] = bucket.scope(self.settings.scope).collection(name)

    async def close(self) -> None:
        if self._cluster is not None:
            await self._cluster.close()
        self._cluster = None
        self._bucket = None
        self._collections = {}

    @property
    def connected(self) -> bool:
        return self._bucket is not None

    def coll(self, name: str) -> Any:
        return self._collections[name]

    async def upsert(self, collection: str, key: str, doc: dict, ttl: timedelta | None = None) -> None:
        coll = self.coll(collection)
        if ttl is None:
            await coll.upsert(key, doc)
        else:
            await coll.upsert(key, doc, expiry=ttl)

    async def insert(self, collection: str, key: str, doc: dict) -> bool:
        """Insert a document, returning False if it already exists."""
        try:
            await self.coll(collection).insert(key, doc)
            return True
        except DocumentExistsException:
            return False

    async def get(self, collection: str, key: str) -> dict | None:
        try:
            res = await self.coll(collection).get(key)
        except DocumentNotFoundException:
            return None
        return res.content_as[dict]

    async def mutate(
        self, collection: str, key: str, fn: Callable[[dict], None], retries: int = 8
    ) -> dict | None:
        """Read-modify-write with CAS so concurrent writers (e.g. mobile sync) aren't clobbered.

        `fn` mutates the doc in place. Returns the stored doc, or None if it doesn't exist.
        """
        from couchbase.options import ReplaceOptions

        coll = self.coll(collection)
        for _ in range(retries):
            try:
                res = await coll.get(key)
            except DocumentNotFoundException:
                return None
            doc = res.content_as[dict]
            fn(doc)
            try:
                await coll.replace(key, doc, ReplaceOptions(cas=res.cas))
                return doc
            except CasMismatchException:
                await asyncio.sleep(0.01)
        raise RuntimeError(f"could not update {collection}/{key}: too much write contention")

    async def remove(self, collection: str, key: str) -> bool:
        try:
            await self.coll(collection).remove(key)
            return True
        except DocumentNotFoundException:
            return False

    async def query(self, statement: str, **params: Any) -> AsyncIterator[dict]:
        from couchbase.options import QueryOptions
        from couchbase.n1ql import QueryScanConsistency

        res = self._cluster.query(
            statement,
            QueryOptions(
                named_parameters=params or None,
                scan_consistency=QueryScanConsistency.REQUEST_PLUS,
            ),
        )
        async for row in res:
            yield row


async def build_store() -> Store:
    store = Store()
    await store.connect()
    return store


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)
