"""Family-scoped authentication.

There is still no login screen — but there is no single shared account either.
Each family code deterministically derives its own Supabase account, signed
into silently. This restores real, database-enforced isolation between
families (Row Level Security keyed on auth.uid(), same as before) while the
user only ever types the family code they already had to type anyway.

Why a shared account (the previous version of this file) wasn't good enough:
every device authenticated as the SAME user regardless of family code, so RLS
correctly enforced "authenticated users only" but had nothing to distinguish
one family from another. The family code was just a client-side filter —
anyone with the app and the public Supabase key could query past it. Deriving
the account FROM the family code closes that gap: different codes are
genuinely different, isolated accounts.

The derivation is deterministic so the same code always reaches the same
account from any PC, and one-way (sha256) so the stored email/password aren't
simply the code in plain text.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from ..core.config import normalise_family_code
from ..core.log import get_logger
from .config import RemoteConfig
from .models import Session
from .transport import AuthError, OfflineError, RemoteError, RemoteTransport

logger = get_logger("remote.auth")


def family_account_email(family_code: str) -> str:
    """Deterministic, family-specific synthetic email.

    Hashed rather than used directly so the account identifier doesn't just
    echo the family code back in plain text.
    """
    normalised = normalise_family_code(family_code)
    digest = hashlib.sha256(f"filesender-email-v1:{normalised}".encode()).hexdigest()[:24]
    return f"family-{digest}@filesender.local"


def family_account_password(family_code: str) -> str:
    """Deterministic, family-specific password.

    Derived with a different salt/prefix than the email so one can't be
    trivially reconstructed from the other.
    """
    normalised = normalise_family_code(family_code)
    digest = hashlib.sha256(f"filesender-password-v1:{normalised}".encode()).hexdigest()
    # Supabase (bcrypt) rejects passwords longer than 72 characters. The full
    # 64-character digest plus a prefix came to 77 and every sign-up failed
    # with "Password cannot be longer than 72 characters". 48 hex characters
    # is still 192 bits - far more than enough.
    # The "Fs1-" prefix supplies an uppercase letter, a digit and a symbol, so
    # the password also passes Supabase's optional "password requirements"
    # setting (lowercase + uppercase + digits + symbols) if it's ever enabled.
    return f"Fs1-{digest[:48]}"


#: Supabase's password limit (bcrypt only uses the first 72 bytes).
MAX_PASSWORD_LENGTH = 72


class AuthService:
    """Signs in silently to the account for whichever family code is given."""

    def __init__(self, transport: RemoteTransport, config: RemoteConfig) -> None:
        self.transport = transport
        self.config = config
        self._session: Optional[Session] = None
        self._signed_in_family: str = ""

    @property
    def session(self) -> Optional[Session]:
        return self._session

    @property
    def signed_in(self) -> bool:
        return self._session is not None and self._session.valid

    @property
    def user_id(self) -> str:
        return self._session.user_id if self._session else ""

    # -- the only operation the app needs ---------------------------------
    def ensure_signed_in(self, family_code: str) -> bool:
        """Sign into this family's account, creating it on first use.

        Returns True on success. Never raises for ordinary failures (offline,
        empty code) — the caller shows a friendly message and retries later.
        Re-authenticates if the family code has changed since the last call,
        so switching codes in Settings takes effect on the next attempt
        without needing any other state to be cleared.
        """
        normalised = normalise_family_code(family_code)
        if not normalised:
            logger.warning("cannot sign in without a family code")
            return False

        if self.signed_in and self._signed_in_family == normalised:
            return True

        email = family_account_email(normalised)
        password = family_account_password(normalised)

        try:
            self._session = self.transport.sign_in(email, password)
            self._signed_in_family = normalised
            logger.info("signed in to family account")
            return True
        except AuthError:
            # First time this family code has ever been used: the account
            # doesn't exist yet, so create it.
            try:
                self._session = self.transport.sign_up(email, password)
                self._signed_in_family = normalised
                logger.info("created a new family account")
                return True
            except OfflineError:
                logger.warning("cannot reach the cloud; will retry")
                return False
            except Exception as exc:                          # noqa: BLE001
                text = str(exc).lower()
                if "session" in text or "confirm" in text:
                    # Supabase created the account but returned no session:
                    # "Confirm email" is still switched on.
                    logger.error("could not create the family account: %s - "
                                 "turn OFF 'Confirm email' in Supabase "
                                 "(see docs/SUPABASE_CHECKLIST.txt, Step 3)", exc)
                else:
                    logger.error("could not create the family account: %s", exc)
                return False
        except OfflineError as exc:
            logger.warning("cannot reach the cloud (%s); will retry", exc)
            return False
        except RemoteError as exc:
            logger.error("sign-in failed: %s", exc)
            return False

    def sign_out(self) -> None:
        try:
            self.transport.sign_out()
        finally:
            self._session = None
            self._signed_in_family = ""