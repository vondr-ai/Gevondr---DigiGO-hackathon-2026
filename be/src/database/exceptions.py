# src\database\exceptions.py
from __future__ import annotations

from uuid import UUID


class RepositoryException(Exception):
    """Base exception for repository errors."""

    pass


class UserNotFoundException(RepositoryException):
    """Raised when a user is not found in the database."""

    def __init__(self, user_id: UUID):
        super().__init__(f"User with ID '{user_id}' not found.")


class ProjectNotFoundException(RepositoryException):
    """Raised when one or more projects are not found in the database."""

    def __init__(self, project_ids: list[UUID]):
        super().__init__(f"Could not find projects with IDs: {project_ids}")


class PermissionDenied(Exception):
    """Raised when user doesn't have access to a resource"""

    pass


# Backward compatibility alias - will be removed after migration
InsufficientPermissionsError = PermissionDenied


class InvalidProjectConfigError(Exception):
    """Raised when project configuration is invalid or incomplete"""

    pass
