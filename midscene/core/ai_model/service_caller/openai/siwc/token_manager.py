"""Shared SIWC token manager (upstream openai/siwc/token-manager.ts)."""

import asyncio
import time
from typing import Any, cast

from midscene.core.ai_model.service_caller.openai.siwc import (
    credential_storage,
    network,
    refresh,
)
from midscene.core.ai_model.service_caller.openai.siwc.errors import SiwcError


class SiwcTokenManager:
    """Read/refresh stored SIWC credentials; refreshes are shared."""

    def __init__(self) -> None:
        self._pending_refresh: asyncio.Task[str] | None = None

    async def get_access_token(self) -> str:
        storage = credential_storage.get_credential_storage()
        record = await asyncio.to_thread(storage.read)
        # Let the server reject expired tokens instead of trusting local clocks.
        return cast(str, record["credentials"]["access_token"])

    def refresh_access_token(
        self,
        previous_access_token: str,
        proxy: network.SiwcProxyConfig | None = None,
    ) -> "asyncio.Task[str]":
        if self._pending_refresh is None:
            self._pending_refresh = asyncio.create_task(
                self._refresh_and_save(previous_access_token, proxy)
            )
            self._pending_refresh.add_done_callback(
                lambda _t: setattr(self, "_pending_refresh", None)
            )
        return self._pending_refresh

    async def _refresh_and_save(
        self,
        previous_access_token: str,
        proxy: network.SiwcProxyConfig | None = None,
    ) -> str:
        storage = credential_storage.get_credential_storage()
        record = await asyncio.to_thread(storage.read)
        saved = cast(dict[str, Any], record.get("credentials", {}))
        if saved.get("access_token") != previous_access_token:
            return cast(str, saved["access_token"])
        try:
            credentials = await refresh.refresh_siwc_credentials(
                saved, None, {"proxy": proxy}
            )
        except Exception as cause:
            raise SiwcError(
                "Unable to refresh SIWC credentials: "
                f"{cause} {storage.reauthorization_hint}"
            ) from cause
        await asyncio.to_thread(
            storage.save,
            {
                **record,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "credentials": credentials,
            },
        )
        return cast(str, credentials["access_token"])


siwc_token_manager = SiwcTokenManager()
