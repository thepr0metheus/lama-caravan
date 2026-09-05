"""Разговор с caravan-scout на клиентской машине.

ТРИ неудачи выглядят отсюда одинаково и не имеют между собой ничего общего:

  * хост НЕДОСТУПЕН — не ответил никто, и чинить надо сеть, процесс скаута,
    файрвол;
  * хост ОТВЕТИЛ и ОТКАЗАЛ — он прекрасно доступен, и у него есть причина:
    порт занят, модели нет, venv не собран;
  * хост ОТВЕТИЛ НЕРАЗБОРЧИВО — соединение живо, но ответ оборвался на полуслове
    или пришёл не тем, что мы умеем читать. Скаут, перезапущенный посреди
    долгого вызова, выглядит именно так. Это не отказ (причины нет) и не
    недоступность (связь была).

Шесть мест звали скаута, и только одно разворачивало отказ и показывало слова
самого агента; в его комментарии так и было написано — то есть урок выучили
один раз и он никуда не поехал. Три остальных называли ответивший хост
«client unreachable», четвёртое роняло сырое исключение, и оператор видел голый
500. Человек шёл чинить исправную сеть.

Разрешение адреса тоже жило в двух копиях: помощник и те же девять строк,
переписанные внутри `stop`.

Отсюда класс: он знает, где живёт клиент, и переводит его отказ на язык
оператора — один раз, для всех вызовов.
"""
import json
import urllib.error
import urllib.request

from caravan.common.errors import AppError
from caravan.common.fetch import post_json


class Scout:
    """Скаут одного клиентского хоста."""

    def __init__(self, host_id, agent_url, headers=None):
        self.host_id = host_id
        self.agent_url = agent_url
        self._headers = headers or {}

    @classmethod
    def for_host(cls, host_id, topology, headers=None):
        """Скаут зарегистрированного клиента.

        Адрес берётся из назначения, если оно есть, и только потом из записи
        клиента: назначение — это то, куда его перецепили, и оно главнее того,
        чем он представился при регистрации.
        """
        host_id = str(host_id or "").strip()
        if not host_id:
            raise AppError("hostId is required", 400)
        client = topology.clients().get(host_id)
        if not client:
            raise AppError(f"client not registered: {host_id}", 404)
        agent_url = str(
            (topology.assignments().get(host_id) or {}).get("agentUrl")
            or client.get("agentUrl") or ""
        ).rstrip("/")
        if not agent_url:
            raise AppError(f"no agentUrl for client {host_id}", 400)
        return cls(host_id, agent_url, headers)

    def post(self, path, payload=None, timeout=10):
        """Позвать скаута и перевести неудачу в понятный отказ.

        Различие между двумя видами неудачи — весь смысл этого метода:
        `HTTPError` значит, что клиент ответил и отказал, и его слова обязаны
        доехать до того, кто читает; `URLError` значит, что до клиента не
        достучались, и вот тогда «недоступен» — правда.
        """
        url = f"{self.agent_url}{path}"
        try:
            return post_json(url, payload or {}, timeout=timeout, headers=self._headers)
        except urllib.error.HTTPError as exc:
            # Answered, and refused. The agent's own words are the whole point.
            raise AppError(f"{self.host_id}: {self._reason(exc)}".strip(), 502)
        except OSError as exc:
            # No answer came back: URLError for a refused connection or DNS
            # failure, TimeoutError for a socket that went quiet. The timeout is
            # NOT a URLError — catching only that let a raw TimeoutError out,
            # which the old bare `except Exception` had been absorbing. HTTPError
            # is a subclass of both and is caught above.
            raise AppError(f"{self.host_id} unreachable: "
                           f"{getattr(exc, 'reason', None) or exc}", 502)
        except Exception as exc:  # noqa: BLE001
            # An answer came, and it cannot be used: IncompleteRead when the
            # scout dies mid-reply, JSONDecodeError or UnicodeDecodeError when
            # the body is not what we read. None of these is an OSError, so
            # narrowing the catch to HTTPError/OSError let them out raw — an
            # operator saw a bare 500 naming no host, which is the exact failure
            # this module was written to remove. The snapshot could not see it
            # either: it drove a refusal and a dead socket, and this is neither.
            raise AppError(f"{self.host_id} answered with an unusable reply: "
                           f"{type(exc).__name__}: {exc}", 502)

    def read(self, path, timeout=10):
        """Ask the scout for something, and keep its answer legible.

        Returns rather than raises, and keeps the shape callers already send
        straight to the browser: {"ok": False, "error": ...}. What changes is the
        CONTENT of that error. `fetch_json` catches everything itself and reports
        `str(exc)`, which for a refusal is "HTTP Error 409: Conflict" — the
        agent's actual words, in the response BODY, are never read at all. So the
        reason was destroyed one level lower than on the write path, and the
        `except Exception` wrapped around these calls almost never fired: it
        looked like error handling without being any.

        The status code is deliberately not changed. These answers go to the
        browser as 200 with ok=false, and turning them into a 502 would move the
        frontend onto a different code path for a fix that is about wording.
        """
        url = f"{self.agent_url}{path}"
        try:
            request = urllib.request.Request(url, headers=self._headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"{self.host_id}: {self._reason(exc)}".strip()}
        except OSError as exc:
            return {"ok": False,
                    "error": f"{self.host_id} unreachable: "
                             f"{getattr(exc, 'reason', None) or exc}"}
        except Exception as exc:  # noqa: BLE001
            # Same third world as post(): answered, and unusable. Saying
            # "unreachable" here would send an operator to check a link that is
            # up. Same wording as the write path, so the two read alike whichever
            # call produced them.
            return {"ok": False,
                    "error": f"{self.host_id} answered with an unusable reply: "
                             f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _reason(exc):
        """Слова агента из тела ответа; сам ответ, если это не наш JSON."""
        try:
            body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            return str(exc)
        try:
            return (json.loads(body) or {}).get("error") or body
        except Exception:  # noqa: BLE001
            return body or str(exc)
