"""Shared exception types."""


class AppError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
