"""The admin's HTTP API as an OpenAPI 3.1 document, built from the route tables
the server answers by (caravan/admin/routes.py).

Nothing here is written by hand. The home rule (visumap, apps-openapi.md):
every app serves its API description at GET /openapi.json, generated from its
code. The hand-written list in docs/http-api.md had fallen 16 paths behind
the 164 it covered by 2026-09-29; that list is now rendered from this
document (ApiReference), so the page people read and the document tools read
cannot disagree.

Level 1, the operator's choice (2026-09-29): every path and method; what it
does (the handler's docstring); the query parameters and top-level body
fields its code reads; the content types it answers with; who may call it.
The types of fields and the shapes of answers are not described yet, and the
document says so where they would be, rather than drawing an empty shape
that reads as "nothing here".
"""
import ast
import inspect
import re
import textwrap


class HandlerReading:
    """What one handler's own code says about its operation.

    Read off the source, not declared beside it: a declaration is a second
    copy, and the second copy is the one that goes stale. What the code does
    not show — a query or a body handed on whole to a helper — is reported as
    not known (`complete` False), never as "reads nothing".
    """

    #: Calls that turn the query string into a dict the handler reads.
    QUERY_PARSERS = ("parse_qs",)
    #: The helper that reads a boolean out of that dict: `_flag(query, "name")`.
    FLAG_READERS = ("_flag",)
    #: Uses of a body or a query dict that read nothing out of it.
    _HARMLESS = object()

    def __init__(self, fn, handler_param=None):
        self.fn = fn
        self.node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
        self._parents = {child: parent for parent in ast.walk(self.node)
                         for child in ast.iter_child_nodes(parent)}
        doc = inspect.getdoc(fn) or ""
        head, _, rest = doc.partition("\n\n")
        self.summary = " ".join(head.split())
        self.description = rest.strip()
        params = list(inspect.signature(fn).parameters)
        # A route handler is (h, parsed[, body]); a helper it hands `h` to
        # names that parameter as it likes, and says which by `handler_param`.
        self._handler = handler_param or (params[0] if params else None)
        self._request = params[1] if len(params) > 1 and not handler_param else None
        self._body = params[2] if len(params) > 2 and not handler_param else None

    # -- what the handler reads ---------------------------------------------

    def query(self):
        """The query parameters the handler reads, in the order its code reads
        them, and whether that is all of them."""
        bound = {target.id for node in ast.walk(self.node)
                 if isinstance(node, ast.Assign) and self._is_query_parse(node.value)
                 for target in node.targets if isinstance(target, ast.Name)}
        reads, complete = [], True
        for node in ast.walk(self.node):
            holder = (isinstance(node, ast.Name) and node.id in bound and isinstance(node.ctx, ast.Load)) \
                or (isinstance(node, ast.Call) and self._is_query_parse(node)
                    and not isinstance(self._parents.get(node), ast.Assign))
            if holder:
                key = self._key_read(node, flag_readers=True)
                if key is None:
                    complete = False
                elif key is not self._HARMLESS:
                    reads.append((node.lineno, node.col_offset, key))
            elif self._request and self._is_request_query(node) and not self._inside_query_parse(node):
                complete = False            # the raw query goes somewhere this cannot follow
            elif self._request and self._is_whole_request(node):
                complete = False            # the whole request is handed on
        return self._in_order(reads), complete

    def body_fields(self):
        """The top-level body fields the handler reads, in the order its code
        reads them, whether that is all of them, and whether it reads a body at all."""
        if not self._body:
            return [], True, False
        reads, complete, used = [], True, False
        for node in ast.walk(self.node):
            if isinstance(node, ast.Name) and node.id == self._body and isinstance(node.ctx, ast.Load):
                used = True
                key = self._key_read(node, flag_readers=False)
                if key is None:
                    complete = False
                elif key is not self._HARMLESS:
                    reads.append((node.lineno, node.col_offset, key))
        return self._in_order(reads), complete, used

    # -- what it answers ----------------------------------------------------

    def answers(self, depth=2):
        """The content types the handler sends, the redirect statuses it may
        answer with, and whether part of the answer is sent by code this could
        not read (then the types above are not the whole story).

        A helper the handler hands `h` to — a redirect, a page, a file stream —
        is read the same way, two calls deep: the answer is its code's fact,
        and a table of "what each helper sends" would be a second copy of it.
        """
        types, redirects, handed_on = [], [], False
        for node in ast.walk(self.node):
            if not isinstance(node, ast.Call):
                continue
            method = node.func.attr if isinstance(node.func, ast.Attribute) else None
            on_handler = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == self._handler
            if on_handler and method == "send_json":
                self._add(types, "application/json")
            elif on_handler and method == "send_file" and len(node.args) > 1 \
                    and isinstance(node.args[1], ast.Constant):
                self._add(types, self._media_type(node.args[1].value))
            elif on_handler and method == "send_header" and len(node.args) > 1 \
                    and self._constant(node.args[0], str).lower() == "content-type" \
                    and isinstance(node.args[1], ast.Constant):
                self._add(types, self._media_type(node.args[1].value))
            elif on_handler and method == "send_response" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, int) \
                    and 300 <= node.args[0].value < 400:
                self._add(redirects, str(node.args[0].value))
            elif not on_handler:
                slots = [i for i, arg in enumerate(node.args) if isinstance(arg, ast.Name) and arg.id == self._handler]
                if not slots:
                    continue
                helper = self._resolve(node.func)
                if helper is None or depth <= 0:
                    handed_on = True
                    continue
                try:
                    params = list(inspect.signature(helper).parameters)
                    sub = HandlerReading(helper, handler_param=params[slots[0]]).answers(depth - 1)
                except (TypeError, OSError, IndexError, SyntaxError):
                    handed_on = True
                    continue
                for media in sub[0]:
                    self._add(types, media)
                for status in sub[1]:
                    self._add(redirects, status)
                handed_on = handed_on or sub[2]
        return types, redirects, handed_on

    # -- reading helpers ----------------------------------------------------

    def _resolve(self, func):
        """The function a call names, looked up where the handler looks it up; None if not a Python function."""
        target = None
        if isinstance(func, ast.Name):
            target = self.fn.__globals__.get(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            target = getattr(self.fn.__globals__.get(func.value.id), func.attr, None)
        return target if inspect.isfunction(target) else None

    def _key_read(self, node, flag_readers):
        """The literal key read off `node` (a dict the handler holds); _HARMLESS
        for a use that reads nothing (a type or emptiness test); None when
        `node` is used in any other way."""
        parent = self._parents.get(node)
        if isinstance(parent, ast.Call) and self._name(parent.func) == "isinstance" and parent.args \
                and parent.args[0] is node:
            return self._HARMLESS
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            return self._HARMLESS
        if isinstance(parent, (ast.If, ast.While, ast.IfExp)) and parent.test is node:
            return self._HARMLESS
        if isinstance(parent, ast.Attribute) and parent.attr == "get":
            call = self._parents.get(parent)
            if isinstance(call, ast.Call) and call.func is parent and call.args:
                return self._constant(call.args[0], str) or None
        if isinstance(parent, ast.Subscript) and parent.value is node:
            return self._constant(parent.slice, str) or None
        if isinstance(parent, ast.Compare) and len(parent.ops) == 1 and isinstance(parent.ops[0], ast.In) \
                and parent.comparators[0] is node:
            return self._constant(parent.left, str) or None
        if flag_readers and isinstance(parent, ast.Call) and self._name(parent.func) in self.FLAG_READERS \
                and parent.args and parent.args[0] is node and len(parent.args) > 1:
            return self._constant(parent.args[1], str) or None
        return None

    def _is_query_parse(self, node):
        return isinstance(node, ast.Call) and self._name(node.func) in self.QUERY_PARSERS

    def _is_request_query(self, node):
        return isinstance(node, ast.Attribute) and node.attr == "query" \
            and isinstance(node.value, ast.Name) and node.value.id == self._request

    def _is_whole_request(self, node):
        if not (isinstance(node, ast.Name) and node.id == self._request and isinstance(node.ctx, ast.Load)):
            return False
        return not isinstance(self._parents.get(node), ast.Attribute)

    def _inside_query_parse(self, node):
        parent = self._parents.get(node)
        while parent is not None and not isinstance(parent, ast.stmt):
            if self._is_query_parse(parent):
                return True
            parent = self._parents.get(parent)
        return False

    @staticmethod
    def _name(func):
        return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")

    @staticmethod
    def _constant(node, kind):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, kind) else ""

    @staticmethod
    def _media_type(value):
        return str(value).split(";", 1)[0].strip()

    @staticmethod
    def _add(items, item):
        if item not in items:
            items.append(item)

    @staticmethod
    def _in_order(reads):
        names = []
        for _line, _col, key in sorted(reads):
            if key not in names:
                names.append(key)
        return names


class ApiSpec:
    """The OpenAPI 3.1 document for the admin's routes.

    Built once per process from the tables themselves: the routes cannot
    change while it runs, and a restart builds it again.
    """

    OPENAPI = "3.1.0"
    #: What the caller is told where a shape would be.
    NOT_DESCRIBED = "Not described yet: the shape of this value is level 2 of the API description."
    #: How refusals come back. Many handlers catch their own refusal and answer
    #: it as 200 with `ok: false` — their descriptions say so; the rest raise,
    #: and the dispatcher answers with the status the refusal carries.
    ERRORS = ("A refusal comes back as `{\"error\": \"…\"}` with the status the handler chose "
              "(400, 401, 403, 404, 409 …), or 500. Some handlers answer a refusal as 200 with "
              "`{\"ok\": false, \"error\": \"…\"}` instead; their descriptions say so.")
    ABOUT = ("The admin API of lama-caravan: the board, its cells, models, clients and cloud accounts. "
             "JSON in and out unless an operation says otherwise.")
    LEVEL = ("Level 1: what each operation does, the query parameters and top-level body fields its "
             "code reads, and the content types it answers with. The types of fields and the shapes "
             "of answers are not described yet. Generated from caravan/admin/routes.py — the "
             "handlers' docstrings and code — when the controller starts.")

    def __init__(self, get_routes, post_routes, delete_routes, prefix_routes, access, version, commit=""):
        self.tables = (("get", get_routes), ("post", post_routes), ("delete", delete_routes))
        self.prefix_routes = prefix_routes
        self.access = access
        self.version = str(version)
        self.commit = commit
        self._document = None

    def document(self):
        if self._document is None:
            self._document = self.build()
        return self._document

    def build(self):
        paths = {}
        for method, table in self.tables:
            for path in sorted(table):
                paths.setdefault(path, {})[method] = self.operation(method, path, table[path])
        for route in self.prefix_routes:
            paths.setdefault(route.template, {})["get"] = self.operation("get", route.prefix, route.handler,
                                                                          path_param=route.param,
                                                                          template=route.template)
        paths = dict(sorted(paths.items()))
        tags = sorted({op["tags"][0] for ops in paths.values() for op in ops.values()})
        return {
            "openapi": self.OPENAPI,
            "info": {
                "title": "lama-caravan admin API",
                "version": self.version,
                "x-commit": self.commit() if callable(self.commit) else str(self.commit or ""),
                "description": "\n\n".join((f"{self.ABOUT} {self.ERRORS}", self.access.DESCRIPTION, self.LEVEL)),
            },
            "servers": [{"url": "/", "description": "the controller that served this document"}],
            "tags": [{"name": tag} for tag in tags],
            "paths": paths,
            "components": {
                "securitySchemes": self.access.SECURITY_SCHEMES,
                "schemas": {"Error": {
                    "type": "object", "required": ["error"],
                    "properties": {"error": {"type": "string", "description": "What went wrong, in words."}},
                }},
                "responses": {"Error": {
                    "description": self.ERRORS,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                }},
            },
        }

    def operation(self, method, path, handler, path_param=None, template=None):
        reading = HandlerReading(handler)
        template = template or path
        op = {
            "operationId": self.operation_id(method, template),
            "summary": reading.summary,
            "tags": [self.tag(path)],
            "x-caravan-handler": f"caravan/admin/routes.py:{handler.__name__}",
        }
        notes = [reading.description] if reading.description else []
        parameters = []
        if path_param:
            parameters.append({"name": path_param, "in": "path", "required": True, "schema": {"type": "string"}})
        query, query_complete = reading.query()
        parameters += [{"name": name, "in": "query", "required": False, "schema": {"type": "string"}}
                       for name in query]
        if not query_complete:
            op["x-caravan-query-complete"] = False
            notes.append("The handler passes its query on: it may read parameters not listed here.")
        if parameters:
            op["parameters"] = parameters
        fields, body_complete, reads_body = reading.body_fields()
        if reads_body:
            schema = {"type": "object", "properties": {name: {"description": self.NOT_DESCRIBED} for name in fields},
                      "description": "The fields the handler reads. " + self.NOT_DESCRIBED}
            if not body_complete:
                schema["x-caravan-fields-complete"] = False
                schema["description"] = ("The fields the handler reads by name; it also passes the body on, "
                                         "so it may read more. " + self.NOT_DESCRIBED)
            op["requestBody"] = {"required": False, "content": {"application/json": {"schema": schema}}}
        op["responses"] = self.responses(reading)
        op.update(self.access.security(method.upper(), path))
        if notes:
            op["description"] = "\n\n".join(notes)
        return op

    def responses(self, reading):
        types, redirects, handed_on = reading.answers()
        ok = {"description": "The answer. " + self.NOT_DESCRIBED}
        if types:
            ok["content"] = {media: {"schema": {"description": self.NOT_DESCRIBED}} for media in types}
        if handed_on:
            ok["x-caravan-content-complete"] = False
            ok["description"] = ("The answer is sent by code the handler hands the request to; the types "
                                 "listed are only those the handler itself sends. " + self.NOT_DESCRIBED)
        answers = {"200": ok}
        for status in redirects:
            answers[status] = {"description": "A redirect (Location names where)."}
        answers["default"] = {"$ref": "#/components/responses/Error"}
        return answers

    @staticmethod
    def tag(path):
        parts = path.split("/")
        return parts[2] if path.startswith("/api/") and len(parts) > 2 and parts[2] else "root"

    @staticmethod
    def operation_id(method, template):
        slug = re.sub(r"[^A-Za-z0-9]+", "_", template).strip("_") or "root"
        return f"{method}_{slug}"


class ApiReference:
    """docs/http-api.md's endpoint list, rendered from the document between two
    markers. The page people read and /openapi.json say the same thing: the
    page used to be written by hand, and fell 16 paths behind."""

    START = ("<!-- api-reference:start — generated from the handlers' docstrings by "
             "`python3 scripts/check_api_spec.py --write`; edit the docstrings, not this -->")
    END = "<!-- api-reference:end -->"

    def __init__(self, document):
        self.document = document

    def access_label(self, op):
        security = op.get("security")
        if security == []:
            return "open"
        names = [name for item in security or [] for name in item]
        if "session" in names and len(names) > 1:
            return "fleet token or session"
        if "fleetToken" in names:
            return "fleet token"
        roles = op.get("x-caravan-roles") or []
        return "any account" if "viewer" in roles else "admin"

    def inputs(self, op):
        parts = []
        query = [p["name"] for p in op.get("parameters", []) if p["in"] == "query"]
        path = [p["name"] for p in op.get("parameters", []) if p["in"] == "path"]
        if path:
            parts.append("path: " + ", ".join(f"`{n}`" for n in path))
        if query or op.get("x-caravan-query-complete") is False:
            listed = ", ".join(f"`{n}`" for n in query) or "—"
            parts.append("query: " + listed + (" …" if op.get("x-caravan-query-complete") is False else ""))
        body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
        if body is not None:
            listed = ", ".join(f"`{n}`" for n in body.get("properties", {})) or "—"
            parts.append("body: " + listed + (" …" if body.get("x-caravan-fields-complete") is False else ""))
        return "; ".join(parts)

    @staticmethod
    def cell(text):
        return " ".join(str(text).split()).replace("|", "\\|")

    def table(self):
        lines = ["| Method & path | Access | Reads | What it does |", "|---|---|---|---|"]
        for path, ops in self.document["paths"].items():
            for method, op in ops.items():
                words = op["summary"] + (". " + op["description"] if op.get("description") else "")
                lines.append(f"| `{method.upper()} {path}` | {self.access_label(op)} | "
                             f"{self.cell(self.inputs(op))} | {self.cell(words)} |")
        return "\n".join(lines)

    def block(self):
        return f"{self.START}\n\n{self.table()}\n\n{self.END}"

    def splice(self, text):
        """`text` with the block between the markers replaced; ValueError when
        the markers are missing — a page without them is not ours to rewrite."""
        start, end = text.find(self.START), text.find(self.END)
        if start < 0 or end < start:
            raise ValueError("docs/http-api.md has no api-reference markers")
        return text[:start] + self.block() + text[end + len(self.END):]
