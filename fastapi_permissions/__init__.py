""" Row Level Permissions for FastAPI

This module provides an implementation for row level permissions for the
FastAPI framework. This is heavily inspired / ripped off the Pyramids Web
Framework, so all cudos to them!

extremely simple and incomplete example:

    from fastapi import Depends, FastAPI
    from fastapi.security import OAuth2PasswordBearer
    from fastapi_permissions import configure_permissions, Allow, Deny, Grant

    app = FastAPI()
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

    def get_current_user(token: str = Depends(oauth2_scheme)):
        ...

    def get_item(item_identifier):
        ...

    permissions = configure_permissions(get_current_user)

    @app.get("/item/{item_id}")
    async def show_item(context:Grant=Depends(permission("view", get_item))):
        return [{"item": context.resource, "user": context.user.username}]
"""

__version__ = "0.0.1"

from fastapi import Depends, HTTPException
from starlette.status import HTTP_403_FORBIDDEN


import collections
import functools
import itertools

from typing import Any, Type

# constants

Allow = "Allow"  # acl "allow" action
Deny = "Deny"  # acl "deny" action

Everyone = "system:everyone"  # user principal for everyone
Authenticated = "system:authenticated"  # authenticated user principal


class _AllPermissions:
    """ special container class for the all permissions constant

    first try was to override the __contains__ method of a str instance,
    but it turns out to be readonly...
    """

    def __contains__(self, other):
        """ returns alway true any permission """
        return True

    def __str__(self):
        """ string representation """
        return "permissions:*"


All = _AllPermissions()


DENY_ALL = (Deny, Everyone, All)  # acl shorthand, denies anything
ALOW_ALL = (Allow, Everyone, All)  # acl shorthand, allows everything


# the exception that will be raised, if no sufficient permissions are found
# can be configured in the configure_permissions() function
permission_exception = HTTPException(
    status_code=HTTP_403_FORBIDDEN,
    detail="Insufficient permissions",
    headers={"WWW-Authenticate": "Bearer"},
)

# the return data structure if a permission is granted
Grant = collections.namedtuple("Grant", ["user", "resource"])


def configure_permissions(
    current_user_func: Any,
    grant_class: Type[Any] = Grant,
    permission_exception: HTTPException = permission_exception,
):
    """ sets the basic configuration for the permissions system

    current_user_func: a dependency that returns the current user
    grant_class: the result class used for a granted permission
    permission_exception: the exception used if a permission is denied

    returns: permission_dependency_factory function,
             with some parameters already provisioned
    """
    current_user_func = Depends(current_user_func)

    return functools.partial(
        permission_dependency_factory,
        current_user_func=current_user_func,
        grant_class=grant_class,
        permission_exception=permission_exception,
    )


def permission_dependency_factory(
    permission: str,
    resource: Any,
    current_user_func: Any,
    grant_class: Type[Any],
    permission_exception: HTTPException,
):
    """ returns a function that acts as a dependable for checking permissions

    This is the actual function used for creating the permission dependency,
    with the help of fucntools.partial in the "configure_permissions()"
    function.

    permission: the permission to check
    resource: the resource that will be accessed
    current_user_func: (provisioned) denpendency, retrieves the current user
    grant_class: (provisioned) data class used if permission is granted
    permission_exception: (provisioned) exception if permission is denied

    returns: dependency function for "Depends()"
    """
    if callable(resource):
        resource = Depends(resource)
    else:
        resource = Depends(lambda: resource)

    # to get the caller signature right, we need to add only the resource and
    # user dependable in the definition
    # the permission itself is available through the outer function scope
    def permission_dependency(resource=resource, user=current_user_func):
        if has_permission(user, permission, resource):
            return grant_class(user=user, resource=resource)
        raise permission_exception

    return permission_dependency


def has_permission(user: Any, requested_permission: str, resource: Any):
    """ checks if a user has the permission for a resource

    The order of the function parameters can be remembered like "Joe eat apple"

    user: a user object, must provide principals for logged in user
    requested_permission: the permission that should be checked
    resource: the object the user wants to access, must provide an ACL

    returns bool: permission granted or denied
    """
    user_principals = normalize_principals(user)
    acl = normalize_acl(resource)

    for action, principal, permissions in acl:
        if isinstance(permissions, str):
            permissions = {permissions}
        if requested_permission in permissions:
            if principal in user_principals:
                return action == Allow
    return False


def list_permissions(user: Any, resource: Any):
    """ lists all permissions of a user for a resouce

    user: a user object, must provide principals for logged in user
    resource: the object the user wants to access, must provide an ACL

    returns dict: every available permission of the resource as key
                  and True / False as value if the permission is granted.
    """
    acl = normalize_acl(resource)

    acl_permissions = (permissions for _, _, permissions in acl)
    as_iterables = ({p} if not is_like_list(p) else p for p in acl_permissions)
    available_permissions = set(itertools.chain.from_iterable(as_iterables))

    return {
        str(p): has_permission(user, p, acl) for p in available_permissions
    }


# utility functions


def normalize_principals(user: Any):
    """ augments all user principal with the system ones

    If the user has no "principal" attribute or the attribute evaluates to
    false, the user is considered to not be logged in. In this case, only the
    principal "Everyone" is returned

    If a user is considered as logged in, "Everyone" and "Authenticated" are
    added to the provided user princpals
    """
    user_principals = getattr(user, "principals", [])
    if callable(user_principals):
        user_principals = user_principals()
    if not user_principals:
        return {Everyone}
    return {Everyone, Authenticated}.union(user_principals)


def normalize_acl(resource: Any):
    """ returns the access controll list for a resource

    If the resource is not an acl list itself it needs to have an "__acl__"
    attribute. If the "__acl__" attribute is a callable, it will be called and
    the result of the call returned.
    """
    acl = getattr(resource, "__acl__", None)
    if callable(acl):
        return acl()
    elif acl is not None:
        return acl
    elif is_like_list(resource):
        return resource
    return []


def is_like_list(something):
    """ checks if something is iterable but not a string """
    if isinstance(something, str):
        return False
    return hasattr(something, "__iter__")