"""End-to-end walk through the demo, in stub mode. No network, no model.

This is the test that protects the demo script. It walks the CHAS form from
the first photo to the declaration and asserts that the gate fires on the
consent step rather than walking the user into a signature.
"""
import os

os.environ.setdefault("USE_STUB", "true")

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.session import store

DECLARATION = "Declaration and Consent (Clause 11)"


@pytest.fixture
def client():
    assert config.USE_STUB, "these tests must not call a real model"
    return TestClient(app)


def _scan(client, session_id):
    """A scan turn. In stub mode the bytes are never looked at."""
    return client.post(
        "/turn",
        data={"session_id": session_id, "kind": "scan"},
        files={"image": ("form.jpg", b"not-a-real-jpeg", "image/jpeg")},
    )


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["stub"] is True


def test_session_create_returns_languages(client):
    body = client.post("/session", data={"language": "zh"}).json()
    assert len(body["session_id"]) == 12
    assert body["language"] == "zh"
    assert "hokkien" in body["languages"]


def test_unknown_language_falls_back_to_default(client):
    body = client.post("/session", data={"language": "klingon"}).json()
    assert body["language"] == config.DEFAULT_LANGUAGE


def test_turn_on_missing_session_is_404(client):
    r = client.post("/turn", data={"session_id": "nope", "kind": "next"})
    assert r.status_code == 404


def test_next_before_any_scan_asks_for_a_photo(client):
    sid = client.post("/session").json()["session_id"]
    body = client.post("/turn", data={"session_id": sid, "kind": "next"}).json()
    assert not body["stopped"]
    assert "camera" in body["message"].lower()


def test_scan_without_image_is_400(client):
    sid = client.post("/session").json()["session_id"]
    r = client.post("/turn", data={"session_id": sid, "kind": "scan"})
    assert r.status_code == 400


def test_scan_rejects_a_non_image(client):
    sid = client.post("/session").json()["session_id"]
    r = client.post(
        "/turn",
        data={"session_id": sid, "kind": "scan"},
        files={"image": ("form.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 415


def test_scan_reads_the_chas_fields(client):
    sid = client.post("/session").json()["session_id"]
    body = _scan(client, sid).json()

    labels = [f["label"] for f in body["fields"]]
    assert "Identification Type" in labels
    assert "Dwelling Type" in labels
    assert "Rental Status" in labels
    assert DECLARATION in labels
    # The brief is explicit: eligibility is pulled from IRAS/CPF by consent,
    # so an income field would be a scripted lie about the real form.
    assert not any("income" in label.lower() for label in labels)


def test_no_field_carries_a_value(client):
    """The structural privacy claim: there is nowhere to put one."""
    sid = client.post("/session").json()["session_id"]
    body = _scan(client, sid).json()
    for f in body["fields"]:
        assert "value" not in f


def test_asking_about_a_field_is_grounded_in_the_corpus(client):
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    body = client.post(
        "/turn",
        data={
            "session_id": sid,
            "kind": "ask",
            "field_label": "Rental Status",
            "question": "I am still paying my HDB loan, is that rented?",
        },
    ).json()

    assert body["kind"] == "explain"
    assert body["sources"], "an explanation with no sources is ungrounded"
    assert body["message"]


def test_walking_the_form_reaches_the_declaration_and_stops(client):
    """The demo's key beat, asserted.

    Mark every ordinary field done in order and confirm that the run ends at
    the declaration with the gate stopping us - not with an instruction to
    sign.
    """
    sid = client.post("/session").json()["session_id"]
    body = _scan(client, sid).json()
    ordinary = [f["label"] for f in body["fields"] if f["label"] != DECLARATION]

    for label in ordinary:
        body = client.post(
            "/turn", data={"session_id": sid, "kind": "done", "field_label": label}
        ).json()

    assert body["stopped"] is True
    assert body["stop_reason"] == "irreversible_action"
    assert body["action"] in config.IRREVERSIBLE_ACTIONS
    assert body["offer_family_loop"] is True
    # The user is told what they are being stopped at, not just that they are.
    assert body["detail"]
    assert "declaration" in body["message"].lower()


def test_the_gate_never_emits_an_instruction_to_sign(client):
    """Walk the whole form and assert no turn ever told the user to sign."""
    sid = client.post("/session").json()["session_id"]
    body = _scan(client, sid).json()
    labels = [f["label"] for f in body["fields"] if f["label"] != DECLARATION]

    seen = [body]
    for label in labels:
        seen.append(
            client.post(
                "/turn", data={"session_id": sid, "kind": "done", "field_label": label}
            ).json()
        )

    for turn in seen:
        if turn["action"] in config.IRREVERSIBLE_ACTIONS:
            assert turn["stopped"], f"emitted an irreversible step: {turn}"


def test_family_loop_message_carries_no_pii(client):
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    body = client.post(
        "/turn",
        data={
            "session_id": sid,
            "kind": "family",
            "field_label": DECLARATION,
            "reason": "It is a legal declaration.",
        },
    ).json()

    from app.redaction import redact

    assert body["message"]
    assert not redact(body["message"]).has_pii


def test_completed_labels_persist_across_turns(client):
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    client.post(
        "/turn",
        data={"session_id": sid, "kind": "done", "field_label": "Dwelling Type"},
    )
    body = client.post("/turn", data={"session_id": sid, "kind": "next"}).json()
    assert "Dwelling Type" in body["completed"]


def test_rescanning_keeps_completed_progress(client):
    """A second photo is a fresh reading of the form, but the user has not
    un-filled the fields they already did."""
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    client.post(
        "/turn",
        data={"session_id": sid, "kind": "done", "field_label": "Dwelling Type"},
    )
    body = _scan(client, sid).json()
    assert "Dwelling Type" in body["completed"]


def test_session_stores_no_values_at_rest(client):
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    client.post(
        "/turn", data={"session_id": sid, "kind": "done", "field_label": "Mobile Number"}
    )

    stored = store.get(sid).to_dict()
    assert stored["completed"] == ["Mobile Number"]
    for f in stored["fields"]:
        assert set(f) == {"label", "kind", "options", "has_value", "notes"}
