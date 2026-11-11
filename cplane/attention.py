"""Shared recipient rules for slice attention."""
from .installation import install_failure, installable


def recipient(item, attention=None):
    """Return the recipient of an attention item, honoring an explicit override."""
    attention = attention if attention is not None else item['attention']
    if attention.get('for') in ('owner', 'planner'):
        return attention['for']
    if attention['kind'] == 'merge' or install_failure(attention):
        return 'owner'
    if attention['kind'] == 'node-step':
        return 'owner' if installable(item) else 'planner'
    return 'planner'
