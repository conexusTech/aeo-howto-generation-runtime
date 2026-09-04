"""The HTTP surface AgentCore requires.

The property worth testing hardest is the one that looks wrong at first glance:
**every outcome is HTTP 200 with a typed body.** AgentCore reports a non-2xx as
an invocation failure and frequently discards the body on the way back, so a 400
carrying a precise explanation reaches the gateway as "it broke".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.howto_generation.model import ChatModel, FakeChatModel, GeneratedArticle
from app.howto_generation.server import app, get_chat_model

TEMPLATE = {
    "id": "tpl-1",
    "service_key": "timing-belt",
    "vertical": "auto-repair",
    "title": "How to replace a timing belt",
    "sections": [],
    "slots": [{"name": "shop_name", "description": None, "required": True}],
}

CONTEXT = {
    "context_version": "v1",
    "organization": {"id": "org-1", "name": "Auto Care Guy"},
}


class ExplodingModel(ChatModel):
    def generate(self, *, prompt):  # noqa: ANN001, ANN201
        raise RuntimeError("bedrock said no, and the message names an internal host")


@pytest.fixture
def client():
    app.dependency_overrides[get_chat_model] = lambda: FakeChatModel()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestPing:
    def test_ping_reports_healthy(self, client: TestClient) -> None:
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_ping_does_not_construct_the_model(self) -> None:
        # Deliberately not overridden here. If /ping touched `get_chat_model`
        # it would build a real Bedrock client, and a misconfigured model id or
        # an IAM denial would turn into a failing health check — so the
        # container gets recycled instead of accepting a request and returning
        # one clear typed error.
        app.dependency_overrides.clear()
        with TestClient(app) as bare:
            assert bare.get("/ping").status_code == 200


class TestInvocations:
    def test_a_valid_request_returns_an_article(self, client: TestClient) -> None:
        response = client.post(
            "/invocations",
            json={"operation": "generate", "template": TEMPLATE, "context": CONTEXT},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["operation"] == "generate"
        assert body["sections"]
        assert body["audit"]["organization_id"] == "org-1"

    def test_the_session_header_is_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/invocations",
            json={"template": TEMPLATE, "context": CONTEXT},
            headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "sess-1"},
        )
        assert response.status_code == 200

    def test_an_unknown_context_field_is_ignored_not_rejected(
        self, client: TestClient
    ) -> None:
        # The gateway's context DTO gains fields regularly. A runtime that
        # rejects an unknown key turns every additive gateway change into an
        # outage in a repo nobody touched.
        response = client.post(
            "/invocations",
            json={
                "template": TEMPLATE,
                "context": {**CONTEXT, "a_field_invented_next_quarter": [1, 2, 3]},
                "some_future_top_level_key": True,
            },
        )
        assert response.status_code == 200


class TestEveryOutcomeIsTyped:
    def test_a_malformed_body_is_a_200_with_an_error_code(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/invocations",
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["error_code"] == "INVALID_REQUEST"

    def test_a_json_array_body_is_refused_by_code(self, client: TestClient) -> None:
        response = client.post("/invocations", json=[1, 2, 3])
        assert response.status_code == 200
        assert response.json()["error_code"] == "INVALID_REQUEST"

    def test_a_missing_template_is_refused_by_code(self, client: TestClient) -> None:
        response = client.post("/invocations", json={"context": CONTEXT})
        assert response.status_code == 200
        assert response.json()["error_code"] == "INVALID_REQUEST"

    def test_a_model_failure_is_a_200_with_an_error_code(self) -> None:
        app.dependency_overrides[get_chat_model] = lambda: ExplodingModel()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/invocations", json={"template": TEMPLATE, "context": CONTEXT}
            )
        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json()["error_code"] == "GENERATION_FAILED"

    def test_a_model_failure_does_not_leak_its_message(self) -> None:
        # The gateway relays this body onward, and a generation failure can
        # carry fragments of tenant-authored context. The traceback stays in
        # the runtime logs.
        app.dependency_overrides[get_chat_model] = lambda: ExplodingModel()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/invocations", json={"template": TEMPLATE, "context": CONTEXT}
            )
        app.dependency_overrides.clear()
        body = response.text
        assert "internal host" not in body
        assert "bedrock said no" not in body

    def test_an_empty_article_is_a_200_with_an_error_code(self) -> None:
        app.dependency_overrides[get_chat_model] = lambda: FakeChatModel(
            GeneratedArticle(title="T", sections=[])
        )
        with TestClient(app) as client:
            response = client.post(
                "/invocations", json={"template": TEMPLATE, "context": CONTEXT}
            )
        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert response.json()["error_code"] == "EMPTY_ARTICLE"


class TestEmitOnly:
    def test_the_settings_carry_no_connection_string(self) -> None:
        # The invariant the whole design rests on: this runtime holds no write
        # authority anywhere. A settings field naming a database, a queue or a
        # bucket is the signal that somebody is about to give it some.
        from app.config import Settings

        forbidden = ("DATABASE", "POSTGRES", "REDIS", "NEO4J", "S3_", "BUCKET", "QUEUE")
        for field in Settings.model_fields:
            assert not any(token in field.upper() for token in forbidden), field


class TestStubModelFlag:
    def test_the_stub_flag_is_off_by_default(self) -> None:
        # The whole safety of the flag rests on this. A default of True would
        # mean a deploy that set nothing served canned articles, and canned
        # prose is plausible enough that a reviewer might approve one.
        from app.config import Settings

        assert Settings().HOWTO_GENERATION_USE_STUB_MODEL is False

    def test_the_stub_flag_returns_a_fake_and_never_builds_bedrock(
        self, monkeypatch
    ) -> None:
        # The point of the flag: the whole pipeline runs locally with no AWS.
        # `get_chat_model` would otherwise construct AnthropicBedrockMantle,
        # which needs the SDK and credentials.
        import app.howto_generation.server as server_module
        from app.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("HOWTO_GENERATION_USE_STUB_MODEL", "true")
        monkeypatch.setattr(server_module, "_model_singleton", None)
        try:
            assert Settings().HOWTO_GENERATION_USE_STUB_MODEL is True
            assert isinstance(server_module.get_chat_model(), FakeChatModel)
        finally:
            get_settings.cache_clear()

    def test_turning_the_flag_on_logs_a_warning(self, monkeypatch, caplog) -> None:
        # A silent stub is the dangerous one.
        import logging

        import app.howto_generation.server as server_module
        from app.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("HOWTO_GENERATION_USE_STUB_MODEL", "1")
        monkeypatch.setattr(server_module, "_model_singleton", None)
        try:
            with caplog.at_level(logging.WARNING):
                server_module.get_chat_model()
            assert "CANNED" in caplog.text
            assert "HOWTO_GENERATION_USE_STUB_MODEL" in caplog.text
        finally:
            get_settings.cache_clear()
