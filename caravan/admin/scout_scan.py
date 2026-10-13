"""Finding the scouts on the local network: the 🔍 on the board's Add scout row."""
import ipaddress
import json
import re
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from caravan.common.errors import AppError


class ScoutScan:
    """Which machines of a private network answer as a caravan-scout (the owner, 2026-10-11).

    A scout answers GET /api/pairing on its port without a token — the open door
    "Add scout" itself knocks on (caravan/admin/scout_pairing.py) — and names its
    machine, its version and whether a controller holds it. The scan knocks on
    every address of the networks asked, at most MAX_ADDRESSES of them, and only
    of private networks: the home network, never the internet. Without networks
    it scans the controller's own: the /24 of the address it reaches the network
    from, and of the address the fleet reaches it at.

    A found scout is "here" when its machine is on this board, "taken" when
    another controller holds it (it must be let go there first), and "free"
    otherwise. Nothing is changed: the operator picks one, and Connect pairs it.

    The network comes in through `connect` and `ask`, parameters so a test can
    stand in for a network without one.
    """

    DEFAULT_PORT = 8092
    MAX_ADDRESSES = 1024
    CONNECT_TIMEOUT = 0.4
    ASK_TIMEOUT = 2.0
    WORKERS = 64

    def __init__(self, known=None, own=None, connect=None, ask=None):
        self.known = known or (lambda: set())      # () -> host ids on this board
        self.own = own or (lambda: [])             # () -> the controller's own addresses
        self.connect = connect or self._connect    # (address, port, timeout) -> bool
        self.ask = ask or self._ask                # (url, timeout) -> dict

    # ── what to scan ────────────────────────────────────────────────────────

    def networks(self, raw):
        """The networks to scan: what the operator typed — networks (10.0.30.0/24)
        or single addresses, by commas or spaces — or, when nothing, the controller's
        own /24s. Refused: something that is not an address, a network that is not
        private, more than MAX_ADDRESSES addresses in all."""
        words = [w for w in re.split(r"[\s,;]+", str(raw or "").strip()) if w]
        if not words:
            words = [f"{address}/24" for address in self.own() if address]
        nets = []
        for word in words:
            try:
                net = ipaddress.ip_network(word, strict=False)
            except ValueError:
                raise AppError(f"{word!r} is not a network — write it as 10.0.30.0/24 or an address", 400)
            if net.version != 4 or not net.is_private or net.is_loopback:
                raise AppError(f"{word} is not a private network: the scan looks only in the home network", 400)
            if net not in nets:
                nets.append(net)
        if not nets:
            raise AppError("no network to scan: write one, e.g. 10.0.30.0/24", 400)
        if sum(net.num_addresses for net in nets) > self.MAX_ADDRESSES:
            raise AppError(f"too many addresses: at most {self.MAX_ADDRESSES} in one scan (four /24 networks)", 400)
        return nets

    @classmethod
    def port(cls, raw):
        text = str(raw if raw not in (None, "") else cls.DEFAULT_PORT).strip()
        if not text.isdigit() or not 1 <= int(text) <= 65535:
            raise AppError("the port must be a number from 1 to 65535", 400)
        return int(text)

    @staticmethod
    def addresses(nets):
        """Every address a scout could have in `nets`: a network's hosts, or the one
        address a /32 names."""
        out = []
        for net in nets:
            hosts = list(net.hosts()) or [net.network_address]
            out.extend(str(address) for address in hosts if str(address) not in out)
        return out

    # ── the scan ────────────────────────────────────────────────────────────

    def scan(self, raw_networks=None, raw_port=None):
        """`{networks, port, scanned, found}`: every scout that answered, in
        address order, each `{address, port, hostId, name, version, state}`."""
        nets = self.networks(raw_networks)
        port = self.port(raw_port)
        addresses = self.addresses(nets)
        with ThreadPoolExecutor(self.WORKERS) as pool:
            reachable = [a for a, ok in zip(addresses, pool.map(
                lambda a: self._safe_connect(a, port), addresses)) if ok]
            found = [f for f in pool.map(lambda a: self.identify(a, port), reachable) if f]
        found.sort(key=lambda f: ipaddress.ip_address(f["address"]))
        return {"networks": [str(n) for n in nets], "port": port, "scanned": len(addresses), "found": found}

    def identify(self, address, port):
        """What answers at `address:port`, when it is a caravan-scout; None otherwise."""
        try:
            info = self.ask(f"http://{address}:{port}/api/pairing", self.ASK_TIMEOUT)
        except Exception:  # noqa: BLE001 — a port that answers something else is no scout
            return None
        if not isinstance(info, dict) or info.get("service") != "caravan-scout":
            return None
        host_id = str(info.get("hostId") or "").strip()
        if host_id and host_id in self.known():
            state = "here"
        elif str(info.get("controllerUrl") or "").strip():
            state = "taken"
        else:
            state = "free"
        return {"address": address, "port": port, "hostId": host_id,
                "name": str(info.get("hostname") or host_id or address), "version": str(info.get("version") or ""),
                "state": state}

    def _safe_connect(self, address, port):
        try:
            return bool(self.connect(address, port, self.CONNECT_TIMEOUT))
        except Exception:  # noqa: BLE001 — an address that cannot be reached is no scout
            return False

    # ── plumbing ────────────────────────────────────────────────────────────

    @staticmethod
    def _connect(address, port, timeout):
        with socket.create_connection((address, port), timeout=timeout):
            return True

    @staticmethod
    def _ask(url, timeout):
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    @staticmethod
    def own_addresses(advertised_ip=""):
        """The controller's own addresses: the one it reaches the network from (the
        UDP-connect trick: no packet is sent) and the one the fleet reaches it at."""
        out = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 9))
                out.append(sock.getsockname()[0])
        except OSError:
            pass
        if advertised_ip and advertised_ip not in out:
            out.append(advertised_ip)
        return [a for a in out if a and not a.startswith("127.")]
