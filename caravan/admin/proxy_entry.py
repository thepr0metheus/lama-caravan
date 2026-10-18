"""The board's side of the entry for keys: its port, the address consumers use, and what a consumer gets."""
import base64
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

from caravan.admin.paths import AGENT_PROXY_STATE_FILE
from caravan.admin.proxies_config import (
    _all_taken_ports,
    load_agent_proxy_config,
    port_is_listening,
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.common.errors import AppError
from caravan.common.key_entry import KeyEntry
from caravan.common.proxy_heartbeat import ProxyHeartbeat
from caravan.domain.client_proxy import ProxyRoute


class PortDoor:
    """Whether other machines reach the caravan's ports, on the proxy's own word.

    The proxy writes where its ports listen into its state file (`listenHost`).
    On a loopback address only this machine reaches them — the NAS, where the
    ports have no door (deploy/nas/compose.yaml): an address on the controller's
    IP leads nowhere, and a consumer gets in only through the entry's public
    name. The board handed out http://<NAS>:23001/v1 there (2026-10-08).
    No fresh word from the proxy is not known (None), and is not taken for open.
    """

    LOOPBACK = ("localhost", "::1")

    def __init__(self, state_file=AGENT_PROXY_STATE_FILE, clock=time.time):
        self.state_file = state_file
        self.clock = clock

    @classmethod
    def opens(cls, host):
        """True for a listen address other machines can reach, False for a
        loopback one, None for no address."""
        host = str(host or "").strip().lower()
        if not host:
            return None
        return not (host in cls.LOOPBACK or host.startswith("127."))

    def open(self):
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not ProxyHeartbeat.fresh(payload.get("time"), self.clock()):
            return None
        return self.opens(payload.get("listenHost"))


class ConsumerAddress:
    """Where a consumer calls the caravan — one rule for the board's proxy rows,
    the agents' cards and Routing's clients panel.

    A route's own port, while it is open; once it is closed, the entry: the
    public name the owner gave it (the DSM name, https://caravan-api.…/v1),
    else the entry's port on the controller's machine. A closed port whose
    entry is off has no address to give — it keeps its port's, and the board
    says the entry is off.

    Where the ports have no door (`door` False, PortDoor), nothing on the
    controller's IP is an address: a port has none ("" — the board says why),
    and the entry has only its public name. `door` None, not known, keeps the
    addresses as they were.
    """

    def __init__(self, config, host, door=None):
        entry = (config or {}).get("entry") or {}
        self.host = host
        self.door = door
        self.entry_port = int(entry.get("port") or 0)
        self.public = str(entry.get("publicUrl") or "").strip() if self.entry_port else ""
        own = ProxyRoute.port_url(host, self.entry_port) if door is not False else ""
        self.entry_url = (self.public or own) if self.entry_port else ""
        self.closed = {int(r.get("port") or 0) for r in (config or {}).get("routes") or []
                       if isinstance(r, dict) and r.get("portClosed")}

    def of(self, port):
        port = int(port or 0)
        if port in self.closed and self.entry_url:
            return self.entry_url
        if self.door is False:
            return ""
        return ProxyRoute.port_url(self.host, port)

    def entry(self):
        """The entry as the board shows it: its address and port, or none, and the
        public name as the owner typed it (the setup asks it back, not the address
        computed from the port)."""
        return {"url": self.entry_url, "port": self.entry_port or None, "publicUrl": self.public}


class EntrySettings:
    """The entry's port and public address, as the board sets them.

    The proxy watches the config file and opens, moves or closes the listener
    by itself (caravan/proxy/listeners.py): nothing restarts. The port must be
    nobody's — not a route's, not a cell's, not an excluded one, and nothing
    else may listen there. The public address is what consumers are given —
    the DSM name in front of the port, https://caravan-api.example.org/v1 —
    and is words only: the proxy never reads it.
    """

    def __init__(self, config=None, taken=None, listening=None):
        self._config = config or load_agent_proxy_config
        self._taken = taken or _all_taken_ports
        self._listening = listening or port_is_listening

    def read(self):
        config = self._config()
        entry = config.get("entry") or {}
        port = int(entry.get("port") or 0)
        routes = config.get("routes") or []
        return {"ok": True, "port": port or None, "publicUrl": entry.get("publicUrl") or "",
                "listening": bool(port) and bool(self._listening(port)),
                "keyedRoutes": sum(1 for route in routes if str(route.get("apiKey") or "").strip()),
                "closedPorts": sorted(int(route.get("port") or 0) for route in routes if route.get("portClosed"))}

    def write(self, body):
        body = body or {}
        raw = body.get("port")
        try:
            port = 0 if raw in (None, "") else int(raw)
        except (TypeError, ValueError):
            raise AppError(f"port must be a number, got {raw!r}", 400)
        url = str(body.get("publicUrl") or "").strip()
        if url and not KeyEntry.URL_RE.match(url):
            raise AppError(f"publicUrl must be an http(s) address, got {url!r}", 400)
        config = self._config()
        current = int((config.get("entry") or {}).get("port") or 0)
        routes = [route for route in config.get("routes") or [] if isinstance(route, dict)]
        # A client of the entry has no port of its own to open: its number is a record's, never
        # a listener's (caravan/admin/consumers.py). Told "open port 23001", the operator had
        # nothing to open — the client is named instead (the loader gives every route a label),
        # and deleting it is the way.
        clients = [str(route.get("label")) for route in routes if route.get("kind") == "consumer"]
        if not port and clients:
            said = (f"clients {', '.join(clients)} call" if len(clients) > 1 else f"client {clients[0]} calls")
            raise AppError(f"{said} the caravan only through the entry: delete "
                           f"{'them' if len(clients) > 1 else 'it'} before turning the entry off", 409)
        closed = sorted(int(route.get("port") or 0) for route in routes if route.get("portClosed"))
        if not port and closed:
            named = ", ".join(str(p) for p in closed)
            if len(closed) > 1:
                said = f"ports {named} are closed — their agents come in only through the entry; open them"
            else:
                said = f"port {named} is closed — its agent comes in only through the entry; open it"
            raise AppError(f"{said} before closing the entry", 409)
        if port:
            if not KeyEntry.PORT_MIN <= port <= KeyEntry.PORT_MAX:
                raise AppError(f"the entry's port must be {KeyEntry.PORT_MIN}..{KeyEntry.PORT_MAX}", 400)
            taken = set(self._taken(config.get("routes") or [])) - {current}
            if port in taken:
                raise AppError(f"port {port} is already the fleet's (a route, a cell or an excluded port)", 409)
            if port != current and self._listening(port):
                raise AppError(f"something already listens on port {port}", 409)
        payload = read_agent_proxy_payload()
        payload["entry"] = KeyEntry.clean({"port": port, "publicUrl": url}) if port else {}
        write_agent_proxy_payload(payload)
        return self.read()


entry_settings = EntrySettings()


class ClientProbe:
    """One question a client asks by POST, sent as the shortest standard request of its kind
    (OpenAI's API reference): a test the operator presses on the client's card. `kind` is how the
    body travels; `sent` what the window shows was sent — the body itself, or the form's fields."""

    PROMPT = "Reply with one word: OK"
    #: The form's boundary: fixed, so a probe is the same bytes every time; silence holds no text.
    BOUNDARY = "caravan-probe"

    def __init__(self, path, payload=None, form=None, paid=False):
        self.path = path
        self._payload = payload
        self._form = form
        #: A test that may cost money — a picture is paid for by the picture: the card asks first.
        self.paid = paid

    @staticmethod
    def silence_wav(seconds=0.5, rate=16000):
        """Half a second of silence as a 16-bit mono WAV: the smallest file a recogniser accepts."""
        data = b"\x00\x00" * int(seconds * rate)
        return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data)) + data)

    def request(self, model):
        """(body, content type, sent) of the probe for `model`."""
        if self._payload is not None:
            payload = self._payload(model)
            return json.dumps(payload).encode("utf-8"), "application/json", json.dumps(payload, ensure_ascii=False, indent=2)
        fields = self._form(model)
        audio = self.silence_wav()
        parts = [f'--{self.BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
                 for name, value in fields.items()]
        parts.append(f'--{self.BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="probe.wav"\r\n'
                     f"Content-Type: audio/wav\r\n\r\n".encode("utf-8") + audio + b"\r\n")
        parts.append(f"--{self.BOUNDARY}--\r\n".encode("utf-8"))
        sent = "\n".join([*(f"{name}={value}" for name, value in fields.items()),
                          f"file=probe.wav (audio/wav, {len(audio)} bytes: 0.5 s of silence, 16 kHz)"])
        return b"".join(parts), f"multipart/form-data; boundary={self.BOUNDARY}", sent


class AsConsumer:
    """What a client of the entry gets for a question of its own, asked with its key on the
    operator's behalf (the owner, 2026-10-12: links on a client's card in Routing, "to get the
    same data the client gets").

    The browser cannot ask it: the entry refuses a request without the client's key, and the page
    never holds a key. So the controller asks, as caravan/admin/model_card.py asks a port, and
    hands on the entry's answer as it came — its status, type and body, the refusals included: a
    401 or a 404 is what the client gets too. By GET only the model list and one model of it are
    asked (`path_of`); by POST only the five kinds of work in PROBES, each the shortest standard
    request of its kind: a link is no door into the proxy for any path the operator could type.
    The entry is asked on this machine, where the proxy listens beside the controller (127.0.0.1
    is in reach on every listen address, the NAS's loopback included).
    """

    MODELS = "/v1/models"
    #: The most of an answer handed on: a model list is a few hundred bytes.
    LIMIT = 1_000_000
    #: What a probe's window shows of an answer: text up to this many characters, audio up to
    #: this many bytes (a few seconds of speech).
    TEXT_SHOWN = 20_000
    AUDIO_SHOWN = 2_000_000
    #: The POST questions a client asks, one per kind of work (OpenAI's API reference).
    PROBES = {probe.path: probe for probe in (
        ClientProbe("/v1/chat/completions", payload=lambda model: {
            "model": model, "messages": [{"role": "user", "content": ClientProbe.PROMPT}], "max_tokens": 16}),
        ClientProbe("/v1/responses", payload=lambda model: {
            "model": model, "input": [{"role": "user", "content": ClientProbe.PROMPT}], "store": False}),
        ClientProbe("/v1/audio/transcriptions", form=lambda model: {"model": model, "response_format": "json"}),
        ClientProbe("/v1/audio/speech", payload=lambda model: {
            "model": model, "input": "OK", "voice": "alloy", "response_format": "mp3"}),
        ClientProbe("/v1/images/generations", payload=lambda model: {
            "model": model, "prompt": "A small red square on a white background", "n": 1, "size": "256x256"}, paid=True),
        ClientProbe("/v1/embeddings", payload=lambda model: {"model": model, "input": "OK"}),
    )}

    def __init__(self, config=None, opener=None, host="127.0.0.1", timeout=10, probe_timeout=120, clock=time.monotonic):
        self._config = config
        self.opener = opener or urllib.request.urlopen
        self.host = host
        self.timeout = timeout
        self.probe_timeout = probe_timeout
        self.clock = clock

    @classmethod
    def probes(cls):
        """The tests a client's card offers, from the one table that sends them: each path, and
        whether a test of it may cost money (the board hands them as `clientProbes`)."""
        return [{"path": probe.path, "paid": probe.paid} for probe in cls.PROBES.values()]

    @staticmethod
    def shown_as(content_type):
        """The type an answer is handed on with: JSON as JSON, anything else as plain text — to be
        read, never drawn as a page of the board's own origin."""
        return "application/json; charset=utf-8" if "json" in str(content_type or "").lower() else "text/plain; charset=utf-8"

    @classmethod
    def path_of(cls, path):
        """The path as the entry is asked it, or "" for one a client does not ask by GET: the list,
        or one model of it by its name — escaped whole, as a client escapes a name with a space
        or a slash in it (the entry compares it unescaped)."""
        path = str(path or "")
        if path.rstrip("/") == cls.MODELS:
            return cls.MODELS
        prefix = cls.MODELS + "/"
        if path.startswith(prefix) and path[len(prefix):]:
            return prefix + urllib.parse.quote(path[len(prefix):], safe="")
        return ""

    def _client(self, port):
        """(key, the entry's port) of the client on `port`: refused when there is no such client,
        it has no key, or the entry is off."""
        try:
            port = int(str(port).strip())
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        config = self._config if self._config is not None else load_agent_proxy_config()
        route = next((r for r in config.get("routes") or [] if isinstance(r, dict)
                      and r.get("kind") == "consumer" and int(r.get("port") or 0) == port), None)
        if route is None:
            raise AppError(f"no client of the entry on port {port}", 404)
        key = str(route.get("apiKey") or "")
        if not key:
            raise AppError(f"client {route.get('label') or port} has no key: the entry would refuse it", 409)
        entry_port = int((config.get("entry") or {}).get("port") or 0)
        if not entry_port:
            raise AppError("the entry is off: no client gets anything", 409)
        return key, entry_port

    def _send(self, request, entry_port, timeout):
        """(status, content type, body) the entry answered — its refusal is an answer too."""
        try:
            with self.opener(request, timeout=timeout) as answer:
                return int(answer.status), str(answer.headers.get("Content-Type") or ""), answer.read(self.LIMIT)
        except urllib.error.HTTPError as exc:
            # The entry's refusal is its answer: the client gets the same.
            kind = str(exc.headers.get("Content-Type") or "") if exc.headers else ""
            return int(exc.code), kind, exc.read(self.LIMIT)
        except Exception as exc:  # noqa: BLE001 — no answer at all is the controller's to say
            raise AppError(f"the entry on port {entry_port} did not answer: {exc}", 502)

    def ask(self, port, path):
        """(status, content type, body) the entry answers the client on `port` for `path`."""
        asked = self.path_of(path)
        if not asked:
            raise AppError(f"a client asks by GET only {self.MODELS} and {self.MODELS}/<model>", 400)
        key, entry_port = self._client(port)
        request = urllib.request.Request(f"http://{self.host}:{entry_port}{asked}",
                                         headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                                  KeyEntry.PROBE_HEADER: "routing"})
        return self._send(request, entry_port, self.timeout)

    def probe(self, port, path, model=""):
        """What the entry answers the client on `port` for a POST of `path`, sent as the shortest
        standard request of its kind naming `model` — the name the client calls its pool by:
        {request: {method, path, model, sent}, status, contentType, ms, bytes, and `text` (with
        `cut` when longer than shown) or, for audio, `audio` in base64}."""
        probe = self.PROBES.get(str(path or ""))
        if probe is None:
            raise AppError(f"a client asks by POST only {', '.join(self.PROBES)}", 400)
        key, entry_port = self._client(port)
        model = str(model or "")
        body, kind, sent = probe.request(model)
        request = urllib.request.Request(f"http://{self.host}:{entry_port}{probe.path}", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {key}", "Content-Type": kind, "Accept": "*/*",
                                                  KeyEntry.PROBE_HEADER: "routing"})
        started = self.clock()
        status, ctype, raw = self._send(request, entry_port, self.probe_timeout)
        out = {"request": {"method": "POST", "path": probe.path, "model": model, "sent": sent},
               "status": status, "contentType": ctype, "ms": int(round((self.clock() - started) * 1000)), "bytes": len(raw)}
        if ctype.lower().startswith("audio/"):
            out["audio"] = base64.b64encode(raw[:self.AUDIO_SHOWN]).decode("ascii")
        else:
            text = raw.decode("utf-8", errors="replace")
            out["text"], out["cut"] = text[:self.TEXT_SHOWN], len(text) > self.TEXT_SHOWN
        return out
