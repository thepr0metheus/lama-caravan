"""Who sent a request: the peer, or the address a proxy on this host names for it."""
import ipaddress


class ClientAddress:
    """The sender of a request, as the proxy's journal and the admin's sign-in know it.

    On the NAS every request reaches the caravan through the DSM's nginx: it
    connects from 127.0.0.1 and names the real sender — it appends the sender's
    address to X-Forwarded-For and puts it in X-Real-IP (the DSM reverse proxy
    rules, 2026-10-11). Read from the connection alone, every consumer was
    127.0.0.1 in the journal, and five wrong passwords from anyone locked the
    sign-in for everyone: the lock is kept per address.

    Only a proxy on this host is believed. A sender on the network could write
    any address into the header, so a peer that is not a loopback address is the
    sender itself, whatever the headers say. Of X-Forwarded-For only the last
    entry counts: that is the one the proxy appended, and anything before it
    the sender wrote. An address that does not read as one is no address, and
    the peer stays.
    """

    FORWARDED = "X-Forwarded-For"
    REAL_IP = "X-Real-IP"

    @staticmethod
    def _ip(text):
        try:
            return ipaddress.ip_address(str(text or "").strip())
        except ValueError:
            return None

    @classmethod
    def is_local(cls, peer):
        """Whether the peer is this host — a proxy in front of the caravan, not a sender.
        ipaddress reads ::ffff:127.0.0.1 as loopback too (Python 3.12.15 on the NAS, 3.13 here)."""
        ip = cls._ip(peer)
        return bool(ip is not None and ip.is_loopback)

    @classmethod
    def of(cls, peer, headers):
        """The sender's address: the peer's, unless the peer is a proxy on this host
        that names the sender. `headers` is the request's (anything with .get)."""
        peer = str(peer or "")
        if not cls.is_local(peer) or headers is None:
            return peer
        chain = [part.strip() for part in str(headers.get(cls.FORWARDED) or "").split(",") if part.strip()]
        named = chain[-1] if chain else str(headers.get(cls.REAL_IP) or "").strip()
        ip = cls._ip(named)
        return str(ip) if ip is not None else peer
