import uuid
from types import SimpleNamespace

from app.models import DocumentVisibility, RoleName
from app.security.permissions import can_access_document, can_manage_document, can_upload
from app.services.rag_service import extract_citations
from app.services.retrieval_service import RetrievedChunk, select_context
from app.services.summarization_service import split_sections


def _user(role: str, role_id: int = 3):
    u = SimpleNamespace(id=uuid.uuid4(), is_active=True, role_id=role_id, role=SimpleNamespace(name=role))
    u.has_role = lambda *names: role in {n.value if isinstance(n, RoleName) else n for n in names}
    return u


def _doc(owner, visibility, permissions=()):
    return SimpleNamespace(uploaded_by=owner, visibility=visibility, permissions=list(permissions))


def test_citation_extraction():
    assert extract_citations("Yes [S1]. Also [S3, S2] and [S2].") == [1, 2, 3]
    assert extract_citations("No citations here.") == []


def test_employee_cannot_read_restricted_without_grant():
    emp, mgr = _user("EMPLOYEE"), _user("MANAGER", 2)
    doc = _doc(mgr.id, DocumentVisibility.RESTRICTED)
    assert not can_access_document(emp, doc)
    assert can_access_document(mgr, doc)
    granted = _doc(mgr.id, DocumentVisibility.RESTRICTED, [SimpleNamespace(user_id=emp.id, role_id=None)])
    assert can_access_document(emp, granted)


def test_only_admin_or_owning_manager_can_manage():
    admin, mgr, other_mgr, emp = _user("ADMIN", 1), _user("MANAGER", 2), _user("MANAGER", 2), _user("EMPLOYEE")
    doc = _doc(mgr.id, DocumentVisibility.PUBLIC)
    assert can_manage_document(admin, doc) and can_manage_document(mgr, doc)
    assert not can_manage_document(other_mgr, doc) and not can_manage_document(emp, doc)
    assert can_upload(mgr) and not can_upload(emp)


def test_context_selection_respects_budget_and_ranking():
    def chunk(sim, size):
        return RetrievedChunk(None, None, "d", "md", None, None, None, None, [], 1, None, "x" * size, sim)

    picked = select_context([chunk(0.5, 600), chunk(0.9, 600), chunk(0.7, 600)], max_chars=1300)
    assert [c.similarity for c in picked] == [0.9, 0.7]


def test_long_text_is_split_for_map_reduce():
    text = "\n\n".join("Paragraph " + "word " * 100 for _ in range(30))
    sections = split_sections(text, 2000)
    assert len(sections) > 5 and all(len(s) <= 2000 for s in sections)
