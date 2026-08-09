"""Concurrency-safe OAuth credential refresh for Withings and Strava.

OAuth secrets are always read directly from Secrets Manager.  In particular,
they do not use the ingest Lambda's warm-process secret cache: both providers
rotate refresh tokens, so a cached value can become unsafe in another Lambda
execution environment.

Refreshes are serialized with a short lease in ``fitness-user-config``.  The
lease is deliberately fail-closed; if DynamoDB cannot establish exclusive
ownership, this service does not call a provider token endpoint.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError


logger = logging.getLogger("oauth_service")


@dataclass(frozen=True)
class VendorConfig:
    secret_id: str
    token_url: str
    refresh_buffer_seconds: int
    default_expires_in: int


VENDORS = {
    "withings": VendorConfig(
        secret_id="withings-oauth",
        token_url="https://wbsapi.withings.net/v2/oauth2",
        refresh_buffer_seconds=600,
        default_expires_in=10_800,
    ),
    "strava": VendorConfig(
        secret_id="strava-oauth",
        token_url="https://www.strava.com/oauth/token",
        refresh_buffer_seconds=3_600,
        default_expires_in=21_600,
    ),
}


class OAuthRefreshError(RuntimeError):
    """Sanitized refresh failure safe to log and return without credentials."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OAuthCredentialCheckError(OAuthRefreshError):
    """One or more vendors failed during the scheduled credential check."""

    def __init__(self, results: dict):
        failed = sorted(vendor for vendor, result in results.items() if result["state"] == "error")
        super().__init__("credential_check_failed", f"OAuth credential check failed for: {', '.join(failed)}")
        self.results = results


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class OAuthService:
    LEASE_SECONDS = 45
    PEER_WAIT_ATTEMPTS = 6
    PEER_WAIT_SECONDS = 0.5

    def __init__(
        self,
        secrets_client,
        user_config_table: Callable[[], object],
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        urlopen: Callable = urllib.request.urlopen,
    ):
        self._secrets = secrets_client
        self._user_config_table = user_config_table
        self._now = now
        self._sleep = sleep
        self._urlopen = urlopen

    def get_secret(self, vendor: str) -> dict:
        """Read the current OAuth secret without a process-local cache."""
        config = self._config(vendor)
        try:
            response = self._secrets.get_secret_value(SecretId=config.secret_id)
            secret = json.loads(response["SecretString"])
        except Exception as exc:
            raise OAuthRefreshError(
                "secret_read_failed", f"{vendor} OAuth credentials are unavailable"
            ) from exc
        if not isinstance(secret, dict):
            raise OAuthRefreshError(
                "secret_malformed", f"{vendor} OAuth credentials are malformed"
            )
        return secret

    def ensure_access_token(
        self,
        vendor: str,
        *,
        force: bool = False,
        failed_access_token: str | None = None,
    ) -> str:
        """Return a usable access token, refreshing exactly once when needed.

        ``failed_access_token`` identifies a token that received a provider
        authentication error.  If another invocation has already replaced it,
        the newer token is returned without rotating again.
        """
        config = self._config(vendor)
        observed = self.get_secret(vendor)
        if self._can_reuse(observed, config, force, failed_access_token):
            return observed["access_token"]

        owner = uuid.uuid4().hex
        table = self._user_config_table()
        if not self._acquire_lease(table, vendor, owner):
            return self._wait_for_peer_refresh(
                vendor,
                config,
                observed,
                force=force,
                failed_access_token=failed_access_token,
            )

        try:
            # The lease protects the vendor call, but the secret must be read
            # again after acquisition in case the preceding owner refreshed it.
            current = self.get_secret(vendor)
            if self._can_reuse_after_lease(
                current,
                observed,
                config,
                force=force,
                failed_access_token=failed_access_token,
            ):
                return current["access_token"]

            self._record_status_safely(
                vendor,
                state="refreshing",
                last_attempt_at=self._now_iso(),
                access_expires_at=_safe_int(current.get("expires_at")),
            )
            updated = self._refresh(vendor, config, current)
            self._persist_secret(config.secret_id, updated)
            self._record_status_safely(
                vendor,
                state="healthy",
                last_success_at=self._now_iso(),
                access_expires_at=_safe_int(updated.get("expires_at")),
                failure_code="",
            )
            return updated["access_token"]
        except OAuthRefreshError as exc:
            self._record_status_safely(
                vendor,
                state="error",
                last_failure_at=self._now_iso(),
                failure_code=exc.code,
            )
            raise
        except Exception as exc:
            wrapped = OAuthRefreshError(
                "refresh_failed", f"{vendor} OAuth token refresh failed"
            )
            self._record_status_safely(
                vendor,
                state="error",
                last_failure_at=self._now_iso(),
                failure_code=wrapped.code,
            )
            raise wrapped from exc
        finally:
            self._release_lease(table, vendor, owner)

    def check_credentials(self, vendors: Iterable[str] = ("withings", "strava")) -> dict:
        """Run the daily idempotent credential check for each configured vendor."""
        results = {}
        for vendor in vendors:
            try:
                config = self._config(vendor)
                before = self.get_secret(vendor)
                refresh_due = not self._token_is_usable(before, config)
                self.ensure_access_token(vendor)
                after = self.get_secret(vendor) if refresh_due else before
                state = "refreshed" if refresh_due else "valid"
                results[vendor] = {
                    "state": state,
                    "expires_at": _safe_int(after.get("expires_at")),
                }
                self._record_status_safely(
                    vendor,
                    state="healthy",
                    last_checked_at=self._now_iso(),
                    access_expires_at=results[vendor]["expires_at"],
                    last_check_result=state,
                    failure_code="",
                )
            except OAuthRefreshError as exc:
                results[vendor] = {"state": "error", "code": exc.code}
                self._record_status_safely(
                    vendor,
                    state="error",
                    last_checked_at=self._now_iso(),
                    last_check_result="error",
                    failure_code=exc.code,
                )

        if any(result["state"] == "error" for result in results.values()):
            raise OAuthCredentialCheckError(results)
        return results

    def _config(self, vendor: str) -> VendorConfig:
        try:
            return VENDORS[vendor]
        except KeyError as exc:
            raise OAuthRefreshError("unknown_vendor", f"Unsupported OAuth vendor: {vendor}") from exc

    def _token_is_usable(self, secret: dict, config: VendorConfig) -> bool:
        token = secret.get("access_token")
        expires_at = _safe_int(secret.get("expires_at"))
        return bool(token) and expires_at - int(self._now()) > config.refresh_buffer_seconds

    def _can_reuse(
        self,
        secret: dict,
        config: VendorConfig,
        force: bool,
        failed_access_token: str | None,
    ) -> bool:
        token = secret.get("access_token")
        if force:
            return bool(failed_access_token and token and token != failed_access_token)
        return self._token_is_usable(secret, config)

    def _can_reuse_after_lease(
        self,
        current: dict,
        observed: dict,
        config: VendorConfig,
        *,
        force: bool,
        failed_access_token: str | None,
    ) -> bool:
        if self._can_reuse(current, config, force, failed_access_token):
            return True
        if force and failed_access_token is None:
            return bool(
                current.get("access_token")
                and (
                    current.get("access_token") != observed.get("access_token")
                    or current.get("refresh_token") != observed.get("refresh_token")
                )
            )
        return False

    def _acquire_lease(self, table, vendor: str, owner: str) -> bool:
        now = int(self._now())
        conditional_failure = table.meta.client.exceptions.ConditionalCheckFailedException
        try:
            table.update_item(
                Key={"key": f"oauth_refresh_lease#{vendor}"},
                UpdateExpression=(
                    "SET lease_owner = :owner, lease_expires_at = :lease_expires_at, "
                    "updated_at = :updated_at"
                ),
                ConditionExpression=(
                    Attr("lease_expires_at").not_exists()
                    | Attr("lease_expires_at").lt(now)
                ),
                ExpressionAttributeValues={
                    ":owner": owner,
                    ":lease_expires_at": now + self.LEASE_SECONDS,
                    ":updated_at": self._now_iso(),
                },
            )
            return True
        except conditional_failure:
            return False
        except ClientError as exc:
            raise OAuthRefreshError(
                "lease_unavailable", f"{vendor} OAuth refresh lease is unavailable"
            ) from exc
        except Exception as exc:
            raise OAuthRefreshError(
                "lease_unavailable", f"{vendor} OAuth refresh lease is unavailable"
            ) from exc

    def _release_lease(self, table, vendor: str, owner: str) -> None:
        try:
            table.update_item(
                Key={"key": f"oauth_refresh_lease#{vendor}"},
                UpdateExpression=(
                    "SET updated_at = :updated_at REMOVE lease_owner, lease_expires_at"
                ),
                ConditionExpression=Attr("lease_owner").eq(owner),
                ExpressionAttributeValues={
                    ":updated_at": self._now_iso(),
                },
            )
        except Exception:
            logger.warning("failed to release OAuth refresh lease vendor=%s", vendor)

    def _wait_for_peer_refresh(
        self,
        vendor: str,
        config: VendorConfig,
        observed: dict,
        *,
        force: bool,
        failed_access_token: str | None,
    ) -> str:
        for _ in range(self.PEER_WAIT_ATTEMPTS):
            self._sleep(self.PEER_WAIT_SECONDS)
            current = self.get_secret(vendor)
            if self._can_reuse_after_lease(
                current,
                observed,
                config,
                force=force,
                failed_access_token=failed_access_token,
            ):
                return current["access_token"]
        raise OAuthRefreshError(
            "lease_busy", f"{vendor} OAuth token refresh is already in progress"
        )

    def _refresh(self, vendor: str, config: VendorConfig, secret: dict) -> dict:
        client_id = secret.get("client_id")
        client_secret = secret.get("client_secret")
        refresh_token = secret.get("refresh_token")
        if not (client_id and client_secret and refresh_token):
            raise OAuthRefreshError(
                "missing_credentials", f"{vendor} OAuth credentials are incomplete"
            )

        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if vendor == "withings":
            fields["action"] = "requesttoken"

        request = urllib.request.Request(
            config.token_url,
            data=urllib.parse.urlencode(fields).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._urlopen(request, timeout=15) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise OAuthRefreshError(
                f"vendor_http_{exc.code}", f"{vendor} OAuth provider rejected token refresh"
            ) from exc
        except Exception as exc:
            raise OAuthRefreshError(
                "vendor_request_failed", f"{vendor} OAuth provider request failed"
            ) from exc

        if not isinstance(payload, dict):
            raise OAuthRefreshError(
                "vendor_response_malformed", f"{vendor} OAuth provider response was malformed"
            )
        if vendor == "withings":
            status = payload.get("status")
            if status != 0:
                raise OAuthRefreshError(
                    f"vendor_status_{status}", "withings OAuth provider rejected token refresh"
                )
            payload = payload.get("body")
            if not isinstance(payload, dict):
                raise OAuthRefreshError(
                    "vendor_response_malformed", "withings OAuth provider response was malformed"
                )

        access_token = payload.get("access_token")
        if not access_token:
            raise OAuthRefreshError(
                "vendor_response_missing_token", f"{vendor} OAuth response omitted access token"
            )

        updated = dict(secret)
        updated["access_token"] = access_token
        updated["refresh_token"] = payload.get("refresh_token") or refresh_token
        expires_at = _safe_int(payload.get("expires_at"))
        if not expires_at:
            expires_at = int(self._now()) + _safe_int(
                payload.get("expires_in"), config.default_expires_in
            )
        updated["expires_at"] = expires_at
        if vendor == "withings" and payload.get("userid") is not None:
            updated["userid"] = str(payload["userid"])
        return updated

    def _persist_secret(self, secret_id: str, updated: dict) -> None:
        for attempt in range(3):
            try:
                self._secrets.update_secret(
                    SecretId=secret_id,
                    SecretString=json.dumps(updated),
                )
                return
            except Exception as exc:
                if attempt == 2:
                    raise OAuthRefreshError(
                        "secret_write_failed", "OAuth token rotation could not be persisted"
                    ) from exc
                self._sleep(0.1 * (2**attempt))

    def _record_status(self, vendor: str, **fields) -> None:
        fields = {name: value for name, value in fields.items() if value is not None}
        if not fields:
            return
        names = {}
        values = {}
        assignments = []
        for index, (name, value) in enumerate(fields.items()):
            name_key = f"#f{index}"
            value_key = f":v{index}"
            names[name_key] = name
            values[value_key] = value
            assignments.append(f"{name_key} = {value_key}")
        self._user_config_table().update_item(
            Key={"key": f"oauth_status#{vendor}"},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def _record_status_safely(self, vendor: str, **fields) -> None:
        try:
            self._record_status(vendor, **fields)
        except Exception:
            logger.warning("failed to record OAuth status vendor=%s", vendor)

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._now(), tz=timezone.utc).isoformat()
