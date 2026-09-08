"""
Audit log action name constants.

Centralized so every service uses the exact same string (avoids typos like
"USER_LOGIN" vs "USER_LOGGED_IN" creating two different audit trails for the
same event). See project brief section 29 for the full envisioned list;
more are added as later phases introduce the events they describe
(DOCUMENT_UPLOADED/DELETED/ACCESSED in Phase 4, SEARCH_PERFORMED in Phase 5,
CHAT_REQUEST in Phase 6-7).
"""

USER_REGISTERED = "USER_REGISTERED"
USER_LOGIN = "USER_LOGIN"
USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
USER_CREATED_BY_ADMIN = "USER_CREATED_BY_ADMIN"
USER_UPDATED = "USER_UPDATED"
USER_DEACTIVATED = "USER_DEACTIVATED"
USER_REACTIVATED = "USER_REACTIVATED"
USER_DELETED = "USER_DELETED"
ROLE_CHANGED = "ROLE_CHANGED"
