"""End-to-end API tests against a real Postgres + pgvector database (fake AI providers)."""
import pytest

HR = b"# Annual Leave\n\nAll employees receive 25 days of annual leave per calendar year. Unused leave carries over up to 5 days.\n"
SECRET = b"# Incident Response\n\nThe break-glass vault code rotation happens every quarter by the security operations team.\n"


def upload(client, headers, name, data, **form):
    return client.post("/api/documents", headers=headers, files={"file": (name, data, "text/markdown")}, data=form)


@pytest.fixture(scope="module")
def docs(client, users):
    mgr = users["MANAGER"]["headers"]
    public = upload(client, mgr, "leave.md", HR, title="Leave Policy", tags="hr,leave")
    restricted = upload(client, mgr, "ir.md", SECRET, title="Incident Runbook", visibility="RESTRICTED", roles="MANAGER")
    assert public.status_code == 202, public.text
    assert restricted.status_code == 202, restricted.text
    return {"public": public.json()["id"], "restricted": restricted.json()["id"]}


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_register_login_and_logout_revokes_token(client):
    r = client.post("/api/auth/register", json={"name": "New", "email": "new@test.enterpriseiq.dev", "password": "Another-Pass-1"})
    assert r.status_code == 201 and r.json()["role"] == "EMPLOYEE"
    token = client.post("/api/auth/login", json={"email": "new@test.enterpriseiq.dev", "password": "Another-Pass-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_wrong_password_and_missing_token(client):
    r = client.post("/api/auth/login", json={"email": "admin@test.enterpriseiq.dev", "password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert client.get("/api/documents").status_code == 401


def test_employee_cannot_upload(client, users):
    assert upload(client, users["EMPLOYEE"]["headers"], "x.md", HR).status_code == 403


def test_upload_rejects_bad_files(client, users):
    mgr = users["MANAGER"]["headers"]
    assert upload(client, mgr, "virus.exe", b"MZ").status_code == 415
    assert upload(client, mgr, "fake.pdf", b"not a pdf").status_code == 415


def test_documents_are_processed(client, users, docs):
    d = client.get(f"/api/documents/{docs['public']}", headers=users["MANAGER"]["headers"]).json()
    assert d["processing_status"] == "COMPLETED" and d["chunk_count"] >= 1 and d["embedding_model"] == "nomic-embed-text"


def test_restricted_document_hidden_from_employee(client, users, docs):
    emp = users["EMPLOYEE"]["headers"]
    ids = {d["id"] for d in client.get("/api/documents", headers=emp).json()}
    assert docs["public"] in ids and docs["restricted"] not in ids
    assert client.get(f"/api/documents/{docs['restricted']}", headers=emp).status_code == 404  # existence not leaked
    assert client.get(f"/api/documents/{docs['restricted']}/chunks", headers=emp).status_code == 404
    assert client.get(f"/api/documents/{docs['restricted']}/download", headers=emp).status_code == 404


def test_search_filters_by_permission(client, users, docs):
    q = {"query": "break-glass vault code rotation"}
    emp = client.post("/api/search", headers=users["EMPLOYEE"]["headers"], json=q).json()["results"]
    mgr = client.post("/api/search", headers=users["MANAGER"]["headers"], json=q).json()["results"]
    admin = client.post("/api/search", headers=users["ADMIN"]["headers"], json=q).json()["results"]
    assert all(r["document_id"] != docs["restricted"] for r in emp)
    assert any(r["document_id"] == docs["restricted"] for r in mgr)
    assert any(r["document_id"] == docs["restricted"] for r in admin)


def test_chat_never_sends_restricted_chunks_to_llm(client, users, docs, fakes):
    llm, _ = fakes
    llm.calls.clear()
    r = client.post("/api/chat", headers=users["EMPLOYEE"]["headers"], json={"message": "What is the break-glass vault code rotation?"})
    assert r.status_code == 200
    prompt = "\n".join(m.content for call in llm.calls for m in call)
    assert "security operations team" not in prompt
    assert all(s["document_id"] != docs["restricted"] for s in r.json()["sources"])


def test_chat_returns_cited_answer_and_history(client, users, docs):
    h = users["EMPLOYEE"]["headers"]
    r = client.post("/api/chat", headers=h, json={"message": "How many days of annual leave do employees receive?"}).json()
    assert "[S1]" in r["answer"]
    assert r["sources"][0]["document_name"] == "Leave Policy" and r["sources"][0]["excerpt"]
    convo = client.get(f"/api/conversations/{r['conversation_id']}", headers=h).json()
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]
    assert client.get(f"/api/conversations/{r['conversation_id']}", headers=users["EMPLOYEE2"]["headers"]).status_code == 404
    assert client.post(f"/api/conversations/{r['conversation_id']}/regenerate", headers=h).status_code == 200
    assert len(client.get(f"/api/conversations/{r['conversation_id']}", headers=h).json()["messages"]) == 2


def test_user_grant_gives_access(client, users, docs):
    emp2 = users["EMPLOYEE2"]
    r = client.put(
        f"/api/documents/{docs['restricted']}/permissions",
        headers=users["MANAGER"]["headers"],
        json={"visibility": "RESTRICTED", "roles": ["MANAGER"], "user_ids": [emp2["id"]]},
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/api/documents/{docs['restricted']}", headers=emp2["headers"]).status_code == 200
    assert client.get(f"/api/documents/{docs['restricted']}", headers=users["EMPLOYEE"]["headers"]).status_code == 404


def test_other_manager_cannot_manage(client, users, docs):
    other = users["MANAGER2"]["headers"]
    assert client.delete(f"/api/documents/{docs['public']}", headers=other).status_code == 403
    assert client.put(f"/api/documents/{docs['public']}/permissions", headers=other, json={"visibility": "RESTRICTED"}).status_code == 403


def test_summary_and_compare(client, users, docs):
    h = users["MANAGER"]["headers"]
    s = client.post(f"/api/documents/{docs['public']}/summarize", headers=h, json={"type": "executive"})
    assert s.status_code == 200 and s.json()["summary"]
    c = client.post("/api/documents/compare", headers=h, json={"document_a_id": docs["public"], "document_b_id": docs["restricted"]})
    assert c.status_code == 200 and c.json()["categories"][0]["name"] == "Added"
    emp = client.post(
        "/api/documents/compare", headers=users["EMPLOYEE"]["headers"], json={"document_a_id": docs["public"], "document_b_id": docs["restricted"]}
    )
    assert emp.status_code == 404


def test_admin_only_endpoints(client, users):
    assert client.get("/api/users", headers=users["EMPLOYEE"]["headers"]).status_code == 403
    assert client.get("/api/admin/audit-logs", headers=users["MANAGER"]["headers"]).status_code == 403
    actions = {entry["action"] for entry in client.get("/api/admin/audit-logs", headers=users["ADMIN"]["headers"]).json()}
    assert {"USER_LOGIN", "DOCUMENT_UPLOADED", "PERMISSION_DENIED", "CHAT_REQUEST", "SEARCH_PERFORMED", "PERMISSION_CHANGED"} <= actions


def test_admin_role_change_invalidates_token(client, users):
    from tests.conftest import PASSWORD

    r = client.post("/api/users", headers=users["ADMIN"]["headers"], json={"name": "Temp", "email": "temp@test.enterpriseiq.dev", "password": PASSWORD})
    uid = r.json()["id"]
    token = client.post("/api/auth/login", json={"email": "temp@test.enterpriseiq.dev", "password": PASSWORD}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert upload(client, h, "t.md", HR).status_code == 403
    assert client.patch(f"/api/users/{uid}", headers=users["ADMIN"]["headers"], json={"role": "MANAGER"}).json()["role"] == "MANAGER"
    assert client.get("/api/auth/me", headers=h).status_code == 401  # must sign in again


def test_admin_cannot_demote_self(client, users):
    r = client.patch(f"/api/users/{users['ADMIN']['id']}", headers=users["ADMIN"]["headers"], json={"role": "EMPLOYEE"})
    assert r.status_code == 403


def test_stats_are_role_aware(client, users):
    emp = client.get("/api/admin/stats", headers=users["EMPLOYEE"]["headers"]).json()
    admin = client.get("/api/admin/stats", headers=users["ADMIN"]["headers"]).json()
    assert admin["total_documents"] > emp["total_documents"]


def test_delete_document(client, users):
    doc_id = upload(client, users["MANAGER"]["headers"], "tmp.md", HR, title="Temp").json()["id"]
    assert client.delete(f"/api/documents/{doc_id}", headers=users["MANAGER"]["headers"]).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=users["ADMIN"]["headers"]).status_code == 404
