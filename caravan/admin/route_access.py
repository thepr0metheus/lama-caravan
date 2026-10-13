"""Who may call a route of the admin: one rule, read by the auth guard that
enforces it (routes.py, `_auth_guard`) and by the API description that states
it (api_spec.py, GET /openapi.json). Two copies of this rule would disagree
about exactly the routes that matter most — the open ones.
"""


class RouteAccess:
    """A session cookie for humans (a viewer account may call every GET but the ones
    that hold keys, and log out, nothing else), the fleet token (X-Caravan-Token) for the machine
    endpoints, and a small public allowlist. Before the first account exists
    only the allowlist answers — the guard sends pages to /setup — so a fresh
    controller is never an open one (since 2026-10-07).
    """

    PUBLIC = "public"      # no credentials at all
    MACHINE = "machine"    # the fleet token in X-Caravan-Token
    METRICS = "metrics"    # the fleet token (header or Bearer), or a session
    SESSION = "session"    # a signed-in account

    # /health is deliberately open: it is the cheapest possible "is this thing up"
    # — no cookie, no browser, milliseconds — and it is what a CI run, a monitor or
    # a load balancer asks BEFORE it has credentials, or when the question is
    # precisely whether credentials can be checked at all. It answers liveness and
    # version and nothing else; no fleet state, no config, nothing worth guarding.
    # /setup is public so ITS OWN route decides what it means: with auth enabled
    # it 302s to /login, which is exactly what the guard would have done — but
    # stated where the page is defined, not implied by an omission here.
    # /healthz is /health in the home network's shape (visumap nas-new-app.md):
    # the commit a deploy check compares with the one it shipped.
    # /openapi.json is open for the same reason /health is, and by the home rule
    # (visumap, apps-openapi.md): it holds paths and words — what the API is,
    # not what the fleet holds — and a test suite reads it before it signs in.
    # /api/packages likewise (visumap apps-packages.md): names and versions of
    # what the controller runs on, for the vulnerability check of the home network.
    PUBLIC_GET = frozenset({"/login", "/setup", "/favicon.svg", "/favicon.ico",
                            "/api/auth/me", "/health", "/api/health", "/healthz", "/openapi.json",
                            "/api/packages"})
    PUBLIC_POST = frozenset({"/api/auth/login", "/api/auth/setup"})
    MACHINE_GET = frozenset({"/api/models/download", "/api/models/folder", "/api/cell-assets", "/api/cell-assets/file"})
    MACHINE_POST = frozenset({"/api/topology/client-heartbeat"})
    # Prometheus can't do cookies: /metrics takes the fleet token via either
    # X-Caravan-Token or Authorization: Bearer, and a logged-in browser can peek too.
    METRICS_GET = frozenset({"/metrics"})
    #: What a viewer may call besides every GET: leaving.
    VIEWER_ALSO = frozenset({"/api/auth/logout"})
    #: The GETs a viewer may not call: the routes' file as stored holds every client's key, and a
    #: client's key is answered once, to an admin, when it is made (2026-10-11).
    ADMIN_GET = frozenset({"/api/agent-proxies/raw"})

    SECURITY_SCHEMES = {
        "session": {
            "type": "apiKey", "in": "cookie", "name": "caravan_session",
            "description": "Set by POST /api/auth/login {username, password}. A viewer account may call "
                           "every GET but the raw routes file, which holds the clients' keys, and log out; "
                           "everything else needs an admin account.",
        },
        "fleetToken": {
            "type": "apiKey", "in": "header", "name": "X-Caravan-Token",
            "description": "The fleet token the scouts carry. Only the machine endpoints take it.",
        },
        "fleetBearer": {
            "type": "http", "scheme": "bearer",
            "description": "The fleet token as a Bearer token: /metrics only (Prometheus sends no cookies).",
        },
    }

    #: The sign-in paragraph of the API description (/openapi.json `info.description`).
    DESCRIPTION = (
        "Every route but the public ones needs a session. Before the first account exists only "
        "the public ones answer — GET /health says `setupRequired`, and POST /api/auth/setup "
        "makes that account. Then POST /api/auth/login `{username, password}` sets the "
        "`caravan_session` cookie. A viewer "
        "account may call every GET but the raw routes file and log out; everything else needs an admin account "
        "(`x-caravan-roles` on each operation). The machine endpoints take the fleet token in "
        "`X-Caravan-Token` instead."
    )

    def kind(self, method, path):
        """PUBLIC, MACHINE, METRICS or SESSION: what `method path` asks of its caller."""
        if (method == "GET" and path in self.PUBLIC_GET) or (method == "POST" and path in self.PUBLIC_POST):
            return self.PUBLIC
        if (method == "GET" and path in self.MACHINE_GET) or (method == "POST" and path in self.MACHINE_POST):
            return self.MACHINE
        if method == "GET" and path in self.METRICS_GET:
            return self.METRICS
        return self.SESSION

    def viewer_may(self, method, path):
        """Whether a viewer account may call `method path` (it is read-only)."""
        return (method == "GET" and path not in self.ADMIN_GET) or path in self.VIEWER_ALSO

    def security(self, method, path):
        """The OpenAPI `security` of `method path` — and, for a session, the roles that may call it."""
        kind = self.kind(method, path)
        if kind == self.PUBLIC:
            return {"security": []}
        if kind == self.MACHINE:
            return {"security": [{"fleetToken": []}]}
        if kind == self.METRICS:
            return {"security": [{"fleetToken": []}, {"fleetBearer": []}, {"session": []}]}
        roles = ["admin", "viewer"] if self.viewer_may(method, path) else ["admin"]
        return {"security": [{"session": []}], "x-caravan-roles": roles}


ROUTE_ACCESS = RouteAccess()
