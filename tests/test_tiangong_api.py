from __future__ import annotations

import pytest

from tiangong_audit.integrations.tiangong_api import (
    DatasetAPI,
    DatasetType,
    ReviewAPI,
    TiangongAPIClient,
    TiangongAPIError,
    TiangongAuthError,
    TiangongWriteDisabledError,
)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)
        self.content = payload if isinstance(payload, bytes) else str(payload).encode()

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload, status_code: int = 200):
        self.responses = [(payload, status_code)]
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if len(response) == 3:
            payload, status_code, headers = response
        else:
            payload, status_code = response
            headers = None
        return FakeResponse(payload, status_code, headers)


class QueuedFakeSession(FakeSession):
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []


def make_client(session: FakeSession, *, allow_writes: bool = False) -> TiangongAPIClient:
    return TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="user-token",
        email="",
        password="",
        session=session,
        allow_writes=allow_writes,
    )


def test_client_requires_supabase_configuration(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
        "TIANGONG_SUPABASE_EMAIL",
        "TIANGONG_SUPABASE_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(TiangongAuthError):
        TiangongAPIClient()


def test_client_loads_configuration_from_local_dotenv(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_SUPABASE_URL=https://dotenv.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_SUPABASE_ACCESS_TOKEN=dotenv-user\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TiangongAPIClient()

    assert client.supabase_url == "https://dotenv.supabase.co"
    assert client.publishable_key == "dotenv-public"
    assert client.access_token == "dotenv-user"


def test_client_accepts_legacy_lca_url_variable(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_LCA_SUPABASE_PUBLISHABLE_KEY",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_LCA_SUPABASE_PUBLISHABLE_KEY=https://legacy.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_SUPABASE_ACCESS_TOKEN=dotenv-user\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TiangongAPIClient()

    assert client.supabase_url == "https://legacy.supabase.co"


def test_client_loads_named_account_from_local_dotenv(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
        "TIANGONG_SUPABASE_EMAIL",
        "TIANGONG_SUPABASE_PASSWORD",
        "TIANGONG_ADMIN_ACCESS_TOKEN",
        "TIANGONG_ADMIN_EMAIL",
        "TIANGONG_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_SUPABASE_URL=https://dotenv.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_ADMIN_ACCESS_TOKEN=admin-token\n"
        "TIANGONG_ADMIN_EMAIL=admin@example.com\n"
        "TIANGONG_ADMIN_PASSWORD=admin-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TiangongAPIClient(account_role="admin")

    assert client.access_token == "admin-token"
    assert client.email == "admin@example.com"
    assert client.password == "admin-secret"


def test_client_loads_operation_account_roles_from_local_dotenv(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_REJECT_ACCESS_TOKEN",
        "TIANGONG_REJECT_EMAIL",
        "TIANGONG_REJECT_PASSWORD",
        "TIANGONG_PASS_ACCESS_TOKEN",
        "TIANGONG_PASS_EMAIL",
        "TIANGONG_PASS_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_SUPABASE_URL=https://dotenv.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_REJECT_EMAIL=reject@example.com\n"
        "TIANGONG_REJECT_PASSWORD=reject-secret\n"
        "TIANGONG_PASS_EMAIL=pass@example.com\n"
        "TIANGONG_PASS_PASSWORD=pass-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    reject_client = TiangongAPIClient(account_role="reject")
    pass_client = TiangongAPIClient(account_role="pass")

    assert reject_client.email == "reject@example.com"
    assert reject_client.password == "reject-secret"
    assert pass_client.email == "pass@example.com"
    assert pass_client.password == "pass-secret"


def test_operation_account_roles_fall_back_to_fixed_accounts(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_REJECT_ACCESS_TOKEN",
        "TIANGONG_REJECT_EMAIL",
        "TIANGONG_REJECT_PASSWORD",
        "TIANGONG_PASS_ACCESS_TOKEN",
        "TIANGONG_PASS_EMAIL",
        "TIANGONG_PASS_PASSWORD",
        "TIANGONG_ADMIN_ACCESS_TOKEN",
        "TIANGONG_ADMIN_EMAIL",
        "TIANGONG_ADMIN_PASSWORD",
        "TIANGONG_MEMBER_ACCESS_TOKEN",
        "TIANGONG_MEMBER_EMAIL",
        "TIANGONG_MEMBER_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_SUPABASE_URL=https://dotenv.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_ADMIN_ACCESS_TOKEN=admin-token\n"
        "TIANGONG_ADMIN_EMAIL=audit-admin@example.com\n"
        "TIANGONG_ADMIN_PASSWORD=admin-secret\n"
        "TIANGONG_MEMBER_ACCESS_TOKEN=member-token\n"
        "TIANGONG_MEMBER_EMAIL=audit-reviewer@example.com\n"
        "TIANGONG_MEMBER_PASSWORD=member-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    reject_client = TiangongAPIClient(account_role="reject")
    pass_client = TiangongAPIClient(account_role="pass")

    assert reject_client.access_token == "admin-token"
    assert reject_client.email == "audit-admin@example.com"
    assert pass_client.access_token == "member-token"
    assert pass_client.email == "audit-reviewer@example.com"


def test_client_uses_active_account_when_role_is_not_explicit(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
        "TIANGONG_SUPABASE_EMAIL",
        "TIANGONG_SUPABASE_PASSWORD",
        "TIANGONG_ACTIVE_ACCOUNT",
        "TIANGONG_MEMBER_ACCESS_TOKEN",
        "TIANGONG_MEMBER_EMAIL",
        "TIANGONG_MEMBER_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "TIANGONG_SUPABASE_URL=https://dotenv.supabase.co\n"
        "TIANGONG_SUPABASE_ANON_KEY=dotenv-public\n"
        "TIANGONG_ACTIVE_ACCOUNT=member\n"
        "TIANGONG_MEMBER_ACCESS_TOKEN=member-token\n"
        "TIANGONG_MEMBER_EMAIL=member@example.com\n"
        "TIANGONG_MEMBER_PASSWORD=member-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TiangongAPIClient()

    assert client.account_role == "member"
    assert client.access_token == "member-token"
    assert client.email == "member@example.com"


def test_client_accepts_account_credentials_without_access_token(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
        "TIANGONG_ACTIVE_ACCOUNT",
        "TIANGONG_ADMIN_ACCESS_TOKEN",
        "TIANGONG_MEMBER_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        email="reviewer@example.com",
        password="secret",
        session=FakeSession({"ok": True}),
    )

    assert client.email == "reviewer@example.com"
    assert client.access_token == ""


def test_rpc_uses_supabase_endpoint_and_auth_headers():
    session = FakeSession([{"id": "review-1"}])
    client = make_client(session)

    result = client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert result == [{"id": "review-1"}]
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://example.supabase.co/rest/v1/rpc/qry_review_get_admin_queue_items"
    assert kwargs["json"] == {"p_status": "unassigned"}
    assert kwargs["headers"]["apikey"] == "public-key"
    assert kwargs["headers"]["Authorization"] == "Bearer user-token"


def test_expired_access_token_falls_back_to_account_login_and_retries():
    session = QueuedFakeSession(
        ({"message": "JWT expired"}, 401),
        ({"access_token": "fresh-token"}, 200),
        ([{"id": "review-1"}], 200),
    )
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="expired-token",
        email="reviewer@example.com",
        password="secret",
        session=session,
    )

    result = client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert result == [{"id": "review-1"}]
    assert session.calls[1][1] == (
        "https://example.supabase.co/auth/v1/token?grant_type=password"
    )
    assert session.calls[1][2]["json"] == {
        "email": "reviewer@example.com",
        "password": "secret",
    }
    assert session.calls[2][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_bad_jwt_403_falls_back_to_account_login_and_retries():
    session = QueuedFakeSession(
        ({"code": 403, "error_code": "bad_jwt", "msg": "token is expired"}, 403),
        ({"access_token": "fresh-token"}, 200),
        ([{"id": "review-1"}], 200),
    )
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="expired-token",
        email="reviewer@example.com",
        password="secret",
        session=session,
    )

    result = client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert result == [{"id": "review-1"}]
    assert session.calls[1][1] == (
        "https://example.supabase.co/auth/v1/token?grant_type=password"
    )
    assert session.calls[2][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_malformed_jwt_from_edge_function_refreshes_token_and_retries():
    session = QueuedFakeSession(
        (
            {
                "ok": False,
                "message": (
                    "invalid JWT: unable to parse or verify signature, token is "
                    "malformed: could not base64 decode signature"
                ),
            },
            403,
        ),
        ({"access_token": "fresh-token"}, 200),
        ({"ok": True}, 200),
    )
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="malformed-token",
        email="reviewer@example.com",
        password="secret",
        session=session,
        allow_writes=True,
    )

    result = client.invoke_function(
        "app_review_save_comment_draft",
        {"reviewId": "review-1", "json": {"conclusion": "rejected"}},
    )

    assert result == {"ok": True}
    assert session.calls[0][1].endswith("/functions/v1/app_review_save_comment_draft")
    assert session.calls[1][1] == (
        "https://example.supabase.co/auth/v1/token?grant_type=password"
    )
    assert session.calls[2][1].endswith("/functions/v1/app_review_save_comment_draft")
    assert session.calls[2][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_account_credentials_can_log_in_without_an_access_token(tmp_path, monkeypatch):
    for name in (
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
        "TIANGONG_ACTIVE_ACCOUNT",
        "TIANGONG_ADMIN_ACCESS_TOKEN",
        "TIANGONG_MEMBER_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    session = QueuedFakeSession(
        ({"access_token": "fresh-token"}, 200),
        ([{"id": "review-1"}], 200),
    )
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        email="reviewer@example.com",
        password="secret",
        session=session,
    )

    result = client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert result == [{"id": "review-1"}]
    assert "/auth/v1/token?grant_type=password" in session.calls[0][1]
    assert session.calls[1][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_successful_access_token_does_not_log_in_with_account():
    session = FakeSession([{"id": "review-1"}])
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="valid-token",
        email="reviewer@example.com",
        password="secret",
        session=session,
    )

    client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert len(session.calls) == 1
    assert "/auth/v1/token" not in session.calls[0][1]


def test_expired_access_token_without_account_credentials_keeps_401_error():
    session = FakeSession({"message": "JWT expired"}, status_code=401)
    client = make_client(session)

    with pytest.raises(TiangongAPIError, match="HTTP 401"):
        client.rpc("qry_review_get_admin_queue_items", {"p_status": "unassigned"})

    assert len(session.calls) == 1


def test_admin_queue_uses_real_platform_rpc_parameters():
    session = FakeSession([{"id": "review-1", "total_count": 14}])
    api = ReviewAPI(make_client(session))

    result = api.get_admin_tasks(status="unassigned", page=1, page_size=10)

    assert result["total"] == 14
    assert result["items"] == [{"id": "review-1", "total_count": 14}]
    assert session.calls[0][2]["json"] == {
        "p_status": "unassigned",
        "p_page": 1,
        "p_page_size": 10,
        "p_sort_by": "modified_at",
        "p_sort_order": "descend",
    }


def test_member_queue_uses_real_platform_rpc():
    session = FakeSession([])
    api = ReviewAPI(make_client(session))

    result = api.get_member_tasks(status="pending", page=2, page_size=5)

    assert result == {"items": [], "total": 0, "page": 2, "page_size": 5}
    assert session.calls[0][1].endswith("/rest/v1/rpc/qry_review_get_member_queue_items")


def test_dataset_api_reads_process_by_id_and_version():
    session = FakeSession([{"id": "process-1", "version": "01.01.000", "json": {}}])
    api = DatasetAPI(make_client(session))

    result = api.get_dataset("process-1", "01.01.000", DatasetType.PROCESS)

    assert result["id"] == "process-1"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://example.supabase.co/rest/v1/processes"
    assert kwargs["params"] == {
        "select": "id,version,json,modified_at,state_code,rule_verification,team_id,reviews",
        "id": "eq.process-1",
        "version": "eq.01.01.000",
        "limit": 1,
    }


def test_dataset_api_resolves_model_before_process():
    session = FakeSession(
        [{"id": "model-1", "version": "01.01.000", "json": {}, "json_tg": {}}]
    )
    api = DatasetAPI(make_client(session))

    result = api.resolve_dataset("model-1", "01.01.000")

    assert result["dataset_type"] == "model"
    assert result["data"]["id"] == "model-1"
    assert session.calls[0][1].endswith("/rest/v1/lifecyclemodels")


def test_dataset_api_reads_source_by_id_and_version():
    session = FakeSession(
        [{"id": "source-1", "version": "01.00.000", "json": {"sourceDataSet": {}}}]
    )
    api = DatasetAPI(make_client(session))

    result = api.get_source("source-1", "01.00.000")

    assert result["id"] == "source-1"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://example.supabase.co/rest/v1/sources"
    assert kwargs["params"]["id"] == "eq.source-1"
    assert kwargs["params"]["version"] == "eq.01.00.000"


def test_write_operations_are_disabled_by_default():
    client = make_client(FakeSession({"ok": True}))

    with pytest.raises(TiangongWriteDisabledError):
        client.invoke_function("app_review_submit_comment", {"reviewId": "review-1"})


def test_write_rpc_operations_are_disabled_by_default():
    client = make_client(FakeSession({"ok": True}))

    with pytest.raises(TiangongWriteDisabledError):
        client.command("cmd_review_assign_reviewers", {"p_review_id": "review-1"})


def test_upload_external_doc_requires_write_enablement(tmp_path):
    file_path = tmp_path / "report.docx"
    file_path.write_bytes(b"docx")
    client = make_client(FakeSession({"ok": True}))

    with pytest.raises(TiangongWriteDisabledError):
        client.upload_external_doc(
            "report.docx",
            file_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_upload_external_doc_posts_to_storage_bucket(tmp_path):
    file_path = tmp_path / "report.docx"
    file_path.write_bytes(b"docx")
    session = FakeSession({"Key": "external_docs/report.docx"})
    client = make_client(session, allow_writes=True)

    result = client.upload_external_doc(
        "report.docx",
        file_path,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert result == {"Key": "external_docs/report.docx"}
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://example.supabase.co/storage/v1/object/external_docs/report.docx"
    assert kwargs["headers"]["Authorization"] == "Bearer user-token"
    assert kwargs["headers"]["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_download_external_doc_reads_storage_bucket(tmp_path):
    output = tmp_path / "report.pdf"
    session = FakeSession(
        b"%PDF",
        status_code=200,
    )
    session.responses = [(b"%PDF", 200, {"Content-Type": "application/pdf"})]
    client = make_client(session)

    result = client.download_external_doc("report.pdf", output)

    assert output.read_bytes() == b"%PDF"
    assert result["content_type"] == "application/pdf"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://example.supabase.co/storage/v1/object/external_docs/report.pdf"
    assert kwargs["headers"]["Authorization"] == "Bearer user-token"


def test_download_external_doc_refreshes_expired_token(tmp_path):
    output = tmp_path / "report.pdf"
    session = QueuedFakeSession(
        ({"message": "JWT expired"}, 401),
        ({"access_token": "fresh-token"}, 200),
        (b"%PDF", 200, {"Content-Type": "application/pdf"}),
    )
    client = TiangongAPIClient(
        supabase_url="https://example.supabase.co",
        publishable_key="public-key",
        access_token="expired-token",
        email="reviewer@example.com",
        password="secret",
        session=session,
    )

    result = client.download_external_doc("report.pdf", output)

    assert result["content_type"] == "application/pdf"
    assert output.read_bytes() == b"%PDF"
    assert session.calls[1][1] == (
        "https://example.supabase.co/auth/v1/token?grant_type=password"
    )
    assert session.calls[2][2]["headers"]["Authorization"] == "Bearer fresh-token"


def test_assign_reviewers_uses_confirmed_write_rpc():
    session = FakeSession({"ok": True})
    api = ReviewAPI(make_client(session, allow_writes=True))

    result = api.assign_reviewers("review-1", ["reviewer-1"])

    assert result == {"ok": True}
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/rest/v1/rpc/cmd_review_assign_reviewers")
    assert kwargs["json"] == {
        "p_audit": None,
        "p_deadline": None,
        "p_review_id": "review-1",
        "p_reviewer_ids": ["reviewer-1"],
    }
