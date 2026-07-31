"""Enums shared by models and schemas.

All of these become native PostgreSQL enum types. Note the `values_callable`
in the models: without it SQLAlchemy stores the member *name* ("MANUAL_QA")
instead of the value ("manual_qa").
"""

from enum import Enum


class UserRole(str, Enum):
    """The three product roles, plus admin.

    Ordered by privilege — see ROLE_LEVEL below.
    """

    MANUAL_QA = "manual_qa"
    QA_ENGINEER = "qa_engineer"
    TEST_MANAGER = "test_manager"
    ADMIN = "admin"


# Permissions are hierarchical: a test_manager can do anything a qa_engineer can.
# `require_role(UserRole.QA_ENGINEER)` therefore means "qa_engineer or above".
ROLE_LEVEL: dict[UserRole, int] = {
    UserRole.MANUAL_QA: 1,
    UserRole.QA_ENGINEER: 2,
    UserRole.TEST_MANAGER: 3,
    UserRole.ADMIN: 4,
}


class Browser(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"
