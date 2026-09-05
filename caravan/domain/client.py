"""Клиент флота: запись о том, что он ЕСТЬ, отдельно от того, отвечает ли он.

Клиент появлялся только из сердцебиения скаута, поэтому «существует» и
«отвечает» были одним и тем же фактом. Теперь клиента заводит оператор, и эти
два факта расходятся: запись есть и настроена, а отчёта может не быть никогда.
Класс держит ровно первую половину — форму записи и правило про её id. Живость
(`state`, `ageSeconds`) вычисляется по `lastSeen` там же, где и раньше, и
ручная запись честно читается как «молчит», а не как «работает».

Правило про id жило внутри разбора сердцебиения одним комментарием на
пятнадцать строк. Как только заводить клиента стало можно двумя путями, оно
обязано было переехать в одно место: иначе второй путь пропускает то, что
первый отвергает, — а последствие описано в самом правиле.
"""
from caravan.admin.paths import CONTROLLER_HOST_ID, LEGACY_CONTROLLER_HOST_IDS
from caravan.common.errors import AppError


class FleetClient:
    """Одна запись о клиенте. Класс — про форму и правила, не про хранение."""

    #: Имена, которые клиент носить не может ни при каких условиях.
    RESERVED_IDS = (CONTROLLER_HOST_ID,) + tuple(LEGACY_CONTROLLER_HOST_IDS)

    @classmethod
    def validate_id(cls, host_id):
        """Id клиента или отказ.

        Id контроллера — зарезервированный сентинел, а слоты адресуются строкой
        "<hostId>:<port>": клиент под этим именем писал бы прямо в пространство
        контроллера, и две разные ячейки оказались бы под одним ключом. Так уже
        пропадала работающая ячейка с доски. Id приходит из чужого конфига или
        из формы, и ничего, кроме этой проверки, между ними не стоит.

        Сравнение регистронезависимое НАМЕРЕННО: флот, где живут два написания
        одного имени, — ловушка для читающего в любом случае, поэтому близкий
        промах отвергается на входе. ЛЕГАСИ-имена зарезервированы навсегда:
        устаревший фронт всё ещё присылает их, имея в виду контроллер, и клиент
        под таким именем был бы неадресуем.
        """
        host_id = str(host_id or "").strip()[:120]
        if not host_id:
            raise AppError("host.id is required", 400)
        if any(host_id.casefold() == r.casefold() for r in cls.RESERVED_IDS):
            raise AppError(f'host.id "{host_id}" is reserved for the controller — '
                           f"give this client a different hostId", 400)
        return host_id

    @classmethod
    def add_agent(cls, row, agent_id, name=""):
        """Добавить агента в запись руками. Отказ, если такой уже есть.

        Пометка `manual` — не украшение: отчёт скаута заменяет список агентов
        ЦЕЛИКОМ, и без неё добавленный руками агент исчезал бы у клиента,
        который однажды отозвался. Пометка — единственное, по чему слияние
        отличает «этого завёл оператор» от «этого больше не видно».
        """
        agent_id = str(agent_id or "").strip()[:80]
        if not agent_id:
            raise AppError("agentId is required", 400)
        agents = row.setdefault("agents", [])
        if any(str(a.get("id") or "") == agent_id for a in agents if isinstance(a, dict)):
            raise AppError(f'agent "{agent_id}" already exists on this client', 409)
        agent = {"id": agent_id, "name": str(name or agent_id).strip()[:120],
                 "scope": "agent", "manual": True}
        agents.append(agent)
        return agent

    @classmethod
    def merge_manual_agents(cls, reported, previous):
        """Список агентов после отчёта: что рассказал скаут плюс ручные.

        Живость по-прежнему принадлежит скауту — агент, о котором он молчит,
        уходит, как и раньше. Кроме тех, кого завёл оператор: их существование
        отчёт не подтверждает и не опровергает.
        """
        seen = {str(a.get("id") or "") for a in reported if isinstance(a, dict)}
        kept = [a for a in (previous or [])
                if isinstance(a, dict) and a.get("manual")
                and str(a.get("id") or "") not in seen]
        return list(reported) + kept

    @classmethod
    def adopt(cls, row):
        """Пометить СУЩЕСТВУЮЩУЮ запись ручной. True, если что-то изменилось.

        Усыновление на месте, а не «создать новое и удалить старое»: реестр
        живой, его маршруты возят трафик, и в промежутке между созданием и
        удалением они существовали бы дважды или ни разу. Здесь меняется ровно
        один факт — кто хозяин записи, — а всё остальное в ней не наше дело:
        ни живость, ни имя, ни агенты. Поэтому же повтор безвреден.
        """
        if not isinstance(row, dict) or row.get("manual"):
            return False
        # Сентинел контроллера — не клиент скаута: усыновлять нечего, а пометка
        # сделала бы вид, что оператор про него что-то решил.
        if any(str(row.get("id") or "").casefold() == r.casefold() for r in cls.RESERVED_IDS):
            return False
        row["manual"] = True
        return True

    @classmethod
    def manual(cls, host_id, name="", ip="", agent_url=""):
        """Запись о клиенте, заведённом руками.

        `lastSeen` НЕ ставится: он означает «отвечал вот тогда», и выдуманное
        значение сделало бы молчащего клиента похожим на живого — ровно то, что
        этой работой и разводится. Пустой `agents` — тоже факт, а не заглушка:
        агентов ему добавляют отдельно.
        """
        row = {
            "id": cls.validate_id(host_id),
            "name": str(name or host_id).strip()[:120],
            "agents": [],
            "manual": True,
        }
        for key, value in (("ip", ip), ("agentUrl", agent_url)):
            value = str(value or "").strip()[:240]
            if value:
                row[key] = value
        return row
