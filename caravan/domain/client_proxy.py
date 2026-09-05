"""Назначение агента и его маршруты — класс, а не словарь из трёх ключей.

Форму этой записи строят три места: нормализатор в `admin/topology.py`,
пересборка в `admin/proxy_ops.py` и провижининг в `admin/fleet_clients.py`.
Сама по себе тройка не беда — беда в том, что нормализатор ПЕРЕСОБИРАЕТ строку
с нуля, поэтому поле, которого он не называет, тихо исчезает при следующем
сохранении. Это уже случилось: флаг `manual` пришлось называть отдельно, и
рядом с ним стоит комментарий о том, что «оставь этот агент в покое», молча
вернувшееся к автомату, — худший отказ, какой у этого флага есть.

Значит «не забыть назвать поле» не должно быть тем, о чём можно забыть. Список
полей живёт здесь, в одном месте, и все трое идут через него: добавленное поле
переживает сохранение у всех писателей сразу или ни у кого.

Класс держит ФОРМУ и правила отказа, а не политику: кто имеет право писать и
что побеждает при слиянии — вопросы вызывающего.
"""
from caravan.common.errors import AppError

#: Как зовётся порт прокси внутри каравана. Неймспейс проверяется отдельным
#: гвардом (scripts/check_proxy_id_namespace.py) — здесь только сборка.
PROXY_ID_PREFIX = "skynet:proxy:"


class ProxyRoute:
    """Одна роль одного агента: каким портом прокси он пользуется.

    `role` по умолчанию "primary" — так вела себя пересборка, и снимок это
    пинит. `proxy_id` может быть пустым: живой отчёт клиента знает свой
    endpoint, но не знает внутреннего id, и пустая строка здесь честнее
    отсутствия ключа.
    """

    __slots__ = ("role", "proxy_id", "endpoint", "context_length", "context_auto", "model_name")

    def __init__(self, role="primary", proxy_id="", endpoint="",
                 context_length=None, context_auto=None, model_name=None):
        self.role = str(role or "primary").strip()
        self.proxy_id = str(proxy_id or "").strip()
        self.endpoint = str(endpoint or "").strip()
        #: Окно контекста, заданное оператором ДЛЯ ЭТОГО потребителя. Побеждает
        #: число модели: у каждого клиента свой бюджет, и модель про него не
        #: знает. None — не задано; ноль и мусор тоже дают None, потому что
        #: клиент прочитал бы ноль как настоящий предел.
        self.context_length = self._positive_int(context_length)
        #: «Брать то, что сообщает модель». Хранится только когда включена:
        #: выдуманное False у маршрута, которому его никто не ставил, читалось
        #: бы как решение оператора.
        self.context_auto = None if context_auto is None else bool(context_auto)
        #: Под каким именем этот порт объявляет свою модель. Клиент ищет в
        #: `/v1/models` СВОЙ id и, не найдя, берёт встроенное умолчание —
        #: поэтому окно, честно опубликованное под чужим именем, до него не
        #: доходит. Пусто — публикуется то, что назвал апстрим.
        self.model_name = (str(model_name).strip()[:120] or None) if model_name else None

    @staticmethod
    def _positive_int(value):
        try:
            value = int(value) if value not in (None, "", False) else None
        except (TypeError, ValueError):
            return None
        return value if value and value > 0 else None

    @classmethod
    def for_port(cls, role, port, server_ip):
        """Маршрут на выданный порт. Единственное место, где собирается пара
        `proxyId`/`endpoint`: раньше её писали два вызывающих, и порт в двух
        половинах обязан быть одним и тем же — снимок это пинит."""
        port = int(port)
        return cls(role=role, proxy_id=f"{PROXY_ID_PREFIX}{port}",
                   endpoint=f"http://{server_ip}:{port}/v1")

    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            raise AppError("route must be an object", 400)
        route = cls(role=raw.get("role"), proxy_id=raw.get("proxyId"), endpoint=raw.get("endpoint"),
                    context_length=raw.get("contextLength"), context_auto=raw.get("contextAuto"),
                    model_name=raw.get("modelName"))
        if not route.endpoint:
            raise AppError("route.endpoint is required", 400)
        return route

    @property
    def port(self):
        """Порт из id, если он там есть. 0 — «не знаю», а не «нулевой порт»."""
        tail = self.proxy_id.rsplit(":", 1)[-1] if self.proxy_id else ""
        return int(tail) if tail.isdigit() else 0

    def to_dict(self):
        # Незаданные настройки не пишутся вовсе: маршрут, которого оператор не
        # трогал, сохраняет ровно ту трёхключевую форму, что и раньше, — значит
        # переход не требует миграции записей.
        out = {"role": self.role, "proxyId": self.proxy_id, "endpoint": self.endpoint}
        if self.context_length is not None:
            out["contextLength"] = self.context_length
        if self.context_auto is not None:
            out["contextAuto"] = self.context_auto
        if self.model_name:
            out["modelName"] = self.model_name
        return out


class AgentAssignment:
    """Куда ходит один агент — и что оператор решил про него руками.

    `manual` означает «провижининг сюда не лезет». Флаг хранится только когда
    он задан: выдуманное False у записи, которой его никто не ставил, читалось
    бы как решение оператора.
    """

    __slots__ = ("agent_id", "routes", "manual")

    def __init__(self, agent_id, routes=None, manual=None):
        self.agent_id = str(agent_id or "").strip()
        if not self.agent_id:
            raise AppError("assignment.agentId is required", 400)
        self.routes = list(routes or [])
        self.manual = None if manual is None else bool(manual)

    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            raise AppError("assignment must be an object", 400)
        raw_routes = raw.get("routes") or []
        if not isinstance(raw_routes, list):
            raise AppError("assignment.routes must be a list", 400)
        routes, seen = [], set()
        for item in raw_routes:
            route = ProxyRoute.from_raw(item)
            if route.role in seen:
                raise AppError(f"duplicate route role: {route.role}", 400)
            seen.add(route.role)
            routes.append(route)
        return cls(agent_id=raw.get("agentId"), routes=routes, manual=raw.get("manual"))

    @classmethod
    def rewired(cls, agent_id, previous_raw, route):
        """Строка, пересобранная по ЖИВОМУ отчёту клиента.

        Отчёт знает одно: каким портом агент пользуется сейчас. Он не знает,
        что оператор про этот маршрут решил, — и не вправе это стирать.
        Сверка прокси собирала строку с нуля из отчёта, поэтому окно контекста
        и флаг «руками» исчезали у КАЖДОГО онлайн-агента, даже когда порт не
        менялся; предпросмотр при этом показывал перецепку «с порта X на порт
        X» и молчал о снятых настройках.

        Живость берётся из `route`, настройки — из прежней записи той же роли.
        Строка остаётся с одним маршрутом: пары fallback сняты с вооружения, и
        воскрешать их пересборкой нельзя.
        """
        prev = previous_raw if isinstance(previous_raw, dict) else {}
        prev_routes = prev.get("routes")
        same_role = next((r for r in (prev_routes if isinstance(prev_routes, list) else [])
                          if isinstance(r, dict)
                          and str(r.get("role") or "primary").strip() == route.role), None)
        if same_role is not None:
            if route.context_length is None:
                route.context_length = ProxyRoute._positive_int(same_role.get("contextLength"))
            if route.context_auto is None and same_role.get("contextAuto") is not None:
                route.context_auto = bool(same_role.get("contextAuto"))
            if route.model_name is None and same_role.get("modelName"):
                route.model_name = str(same_role.get("modelName")).strip()[:120] or None
        return cls(agent_id, [route], manual=prev.get("manual"))

    def route(self, role):
        return next((r for r in self.routes if r.role == role), None)

    def set_route(self, route):
        """Ставит маршрут на его роль: заменяет существующий, иначе добавляет.

        Замена, а не пропуск — это и есть починка 2026-07-20: провижининг
        выдавал новый порт, когда старый исчезал, и добавлял его «если роли
        нет», что в этом случае никогда не было правдой. Запись оставалась
        стоять на мёртвом порту, ворота срабатывали снова, и порт минтился на
        каждом опросе доски.
        """
        existing = self.route(route.role)
        if existing is None:
            self.routes.append(route)
        else:
            # Переставляется ЖИВОСТЬ — куда агент ходит. Настройки, заданные
            # оператором на этой роли, переезд порта не отменяет: то же
            # разделение, что и при слиянии на доске.
            existing.role, existing.proxy_id, existing.endpoint = route.role, route.proxy_id, route.endpoint
            if route.context_length is not None:
                existing.context_length = route.context_length
            if route.context_auto is not None:
                existing.context_auto = route.context_auto
            if route.model_name is not None:
                existing.model_name = route.model_name
        return route

    def to_dict(self):
        out = {"agentId": self.agent_id, "routes": [r.to_dict() for r in self.routes]}
        if self.manual is not None:
            out["manual"] = self.manual
        return out
