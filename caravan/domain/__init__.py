"""What the caravan KNOWS, separate from how it serves and stores it.

The entities live here: runner, cell, route. No HTTP, no filesystem, no
global state — a module from here must import cleanly in an empty process and
answer questions about a config without touching anything.
"""
