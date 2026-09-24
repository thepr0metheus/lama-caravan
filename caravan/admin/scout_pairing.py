"""Adding a machine's scout from the board, and letting it go."""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request

from caravan.common.errors import AppError
from caravan.common.fetch import post_json


class ScoutPairing:
    """The one way a machine joins the fleet as a scout host.

    The machine only installs its scout (caravan-scout `./install.sh`), which
    then waits, unpaired, on its port. The operator enters the machine's
    address on the board; the controller reads the scout's open
    /api/pairing, hands it the controller's own address and — when sign-in is
    on — the fleet token (POST /api/controller-url), and the scout beats once,
    which creates the machine's host record. Adding a paired scout again is
    the connection test, and it is also how a regenerated token reaches it.

    Letting go asks the scout to forget the controller (POST /api/unpair) and
    then forgets the machine. A scout that does not answer is forgotten all
    the same — and comes back with its next heartbeat if it still holds the
    controller's address; the board says so before it is done.

    A scout on the controller's own machine is added at 127.0.0.1 like any
    other, and is handed the controller at 127.0.0.1.

    The network is reached through `http_get` / `http_post`, parameters so a
    test can stand in for a scout without one.
    """

    DEFAULT_PORT = 8092
    _HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")

    def __init__(self, store, save, headers, admin_port, advertised_ip="",
                 http_get=None, http_post=None, facing_ip=None):
        self.store = store                  # () -> the topology store
        self.save = save                    # () -> persists it
        self.headers = headers              # () -> {"X-Caravan-Token": …} or {}
        self.admin_port = int(admin_port)
        self.advertised_ip = str(advertised_ip or "").strip()
        self.http_get = http_get or self._get
        self.http_post = http_post or post_json
        self.facing_ip = facing_ip or self._facing_ip

    # ── addresses ────────────────────────────────────────────────────────────

    @classmethod
    def scout_url(cls, raw_address, raw_port=None) -> str:
        """http://host:port of a scout from what the operator typed: a name or
        an address, with or without a scheme or a port of its own."""
        text = str(raw_address or "").strip()
        text = re.sub(r"^[a-z]+://", "", text, flags=re.I).split("/", 1)[0]
        host, _, typed_port = text.partition(":")
        port = str(raw_port or typed_port or cls.DEFAULT_PORT).strip()
        if not host or not cls._HOST_RE.match(host):
            raise AppError("enter the machine's address — an IP or a host name", 400)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise AppError("the port must be a number from 1 to 65535", 400)
        return f"http://{host}:{int(port)}"

    @staticmethod
    def is_loopback(host: str) -> bool:
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def controller_url_for(self, scout_url: str) -> str:
        """The controller as the scout will reach it. A scout on this machine
        gets 127.0.0.1; any other gets the configured LAN address, or else the
        address of the interface that routes towards it."""
        host = scout_url.split("://", 1)[1].rsplit(":", 1)[0]
        if self.is_loopback(host):
            ip = "127.0.0.1"
        elif self.advertised_ip and not self.is_loopback(self.advertised_ip):
            ip = self.advertised_ip
        else:
            ip = self.facing_ip(host)
        return f"http://{ip}:{self.admin_port}"

    @staticmethod
    def _facing_ip(host: str) -> str:
        """UDP-connect: no packet is sent; the kernel names the interface that
        routes towards `host`."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((host, 9))
                return sock.getsockname()[0]
        except OSError as exc:
            raise AppError(f"no route from the controller to {host}: {exc}", 502)

    # ── adding ───────────────────────────────────────────────────────────────

    def connect(self, raw_address, raw_port=None) -> dict:
        url = self.scout_url(raw_address, raw_port)
        info = self._pairing_info(url)
        controller = self.controller_url_for(url)
        headers = self.headers()
        payload = {"url": controller, "token": headers.get("X-Caravan-Token", "")}
        try:
            answer = self.http_post(f"{url}/api/controller-url", payload, timeout=20, headers=headers)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise AppError(f"the scout at {url} is paired with another controller (it holds a different "
                               f"fleet token) — take it off there first, or on that machine run "
                               f"./uninstall.sh and ./install.sh", 409)
            raise AppError(f"the scout at {url} refused: {self._words(exc)}", 502)
        except OSError as exc:
            raise AppError(f"the scout at {url} stopped answering: {getattr(exc, 'reason', None) or exc}", 502)
        beat = answer.get("heartbeat") if isinstance(answer, dict) else None
        beat = beat if isinstance(beat, dict) else {}
        if beat.get("state") != "ok":
            raise AppError(f"the scout at {url} took the controller's address ({controller}) but cannot reach "
                           f"it: {beat.get('error') or 'no answer'} — open port {self.admin_port} on the "
                           f"controller to that machine", 502)
        host = ((beat.get("result") or {}).get("host") or {}) if isinstance(beat.get("result"), dict) else {}
        return {"ok": True, "hostId": host.get("id") or info.get("hostId") or "",
                "name": host.get("name") or info.get("hostId") or "",
                "scoutVersion": host.get("scoutVersion") or info.get("version") or "",
                "scoutUrl": url, "controllerUrl": controller}

    def _pairing_info(self, url: str) -> dict:
        """What the scout says about itself before anything is changed: that it
        is a caravan-scout, and new enough to be added from here."""
        try:
            info = self.http_get(f"{url}/api/pairing", timeout=5)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AppError(f"a scout older than 2.0 answers at {url} — update it: git pull and "
                               f"./install.sh on that machine", 409)
            raise AppError(f"{url} answered {exc.code} — not a caravan-scout", 502)
        except OSError as exc:
            raise AppError(f"no scout answers at {url}: {getattr(exc, 'reason', None) or exc} — is "
                           f"./install.sh done there, and is the port open?", 502)
        except ValueError:
            raise AppError(f"something other than a caravan-scout answers at {url}", 502)
        if not isinstance(info, dict) or info.get("service") != "caravan-scout":
            raise AppError(f"something other than a caravan-scout answers at {url}", 502)
        return info

    # ── letting go ───────────────────────────────────────────────────────────

    def disconnect(self, host_id) -> dict:
        host_id = str(host_id or "").strip()
        if not host_id:
            raise AppError("hostId is required", 400)
        store = self.store()
        host = store["hosts"].get(host_id)
        if host is None:
            raise AppError(f"host not found: {host_id}", 404)
        agent_url = str(host.get("agentUrl") or "").rstrip("/")
        unpaired = False
        if agent_url:
            try:
                self.http_post(f"{agent_url}/api/unpair", {}, timeout=10, headers=self.headers())
                unpaired = True
            except urllib.error.HTTPError as exc:
                if exc.code != 404:      # 404: a scout older than 2.1 — it cannot be told
                    raise AppError(f"the scout of {host_id} refused to let go: {self._words(exc)}", 502)
            except OSError:
                pass                     # silent: forgotten here, and says so
        del store["hosts"][host_id]
        self.save()
        return {"ok": True, "hostId": host_id, "unpaired": unpaired}

    # ── plumbing ─────────────────────────────────────────────────────────────

    @staticmethod
    def _get(url, timeout=5):
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    @staticmethod
    def _words(exc) -> str:
        """The scout's own reason from its answer, or the status line."""
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
            return str(body.get("error") or exc)
        except Exception:  # noqa: BLE001
            return str(exc)
