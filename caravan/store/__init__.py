"""Where the caravan KEEPS what survives a restart.

Exactly one layer is responsible for reading from disk, writing to disk, and
defaults. Everything else asks the store and knows neither the file path nor
the format.
"""
