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

# The two signature-kind fields on the Dec 2025 form. Both must gate.
DECLARATION = "Consent and Declaration by Main Applicant (Section 2B)"
SIGNATURE = "Signature / Thumbprint of Main Applicant (Section 3)"
IRREVERSIBLE_FIELDS = {DECLARATION, SIGNATURE}


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


def _keys(client, sid):
    """label -> key for the current session. Labels repeat on the real form,
    so tests resolve through this rather than addressing fields by label."""
    body = client.post("/turn", data={"session_id": sid, "kind": "next"}).json()
    return {f["label"]: f["key"] for f in body["fields"]}


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["stub"] is True


def test_health_is_not_on_the_path_google_swallows(client):
    """Regression: /healthz never reaches the container on Cloud Run -
    Google's frontend returns its own 404 and nothing is logged. Keep the
    health check off that path."""
    assert client.get("/healthz").status_code == 404


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
    assert "Dwelling Type" in labels
    assert "Rental Status of Residence" in labels
    assert DECLARATION in labels
    assert SIGNATURE in labels
    # Verified against the published Dec 2025 PDF: eligibility is pulled from
    # IRAS/CPF by consent, so an income field would be a scripted lie about
    # the real form.
    assert not any("income" in label.lower() for label in labels)


def test_stub_options_match_the_real_form(client):
    """The stub's printed options are copied from the PDF, not invented.

    Guards the specific things the Dec 2025 revision changed: dwelling type
    lost its room-count breakdown, and rental status is phrased as
    "Not Rented", not "Owned".
    """
    sid = client.post("/session").json()["session_id"]
    fields = {f["label"]: f for f in _scan(client, sid).json()["fields"]}

    dwelling = fields["Dwelling Type"]["options"]
    assert "HDB Flat" in dwelling
    assert not any("room" in o.lower() for o in dwelling)

    rental = fields["Rental Status of Residence"]["options"]
    assert "Not Rented (e.g. bought or owned)" in rental
    assert "Renting from Government" in rental


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
            "field_key": _keys(client, sid)["Rental Status of Residence"],
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
    ordinary = [
        f["key"] for f in body["fields"] if f["label"] not in IRREVERSIBLE_FIELDS
    ]

    for key in ordinary:
        body = client.post(
            "/turn", data={"session_id": sid, "kind": "done", "field_key": key}
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
    keys = [
        f["key"] for f in body["fields"] if f["label"] not in IRREVERSIBLE_FIELDS
    ]

    seen = [body]
    for key in keys:
        seen.append(
            client.post(
                "/turn", data={"session_id": sid, "kind": "done", "field_key": key}
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
            "field_key": _keys(client, sid)[DECLARATION],
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
        data={
            "session_id": sid,
            "kind": "done",
            "field_key": _keys(client, sid)["Dwelling Type"],
        },
    )
    body = client.post("/turn", data={"session_id": sid, "kind": "next"}).json()
    assert _keys(client, sid)["Dwelling Type"] in body["completed"]


def test_rescanning_keeps_completed_progress(client):
    """A second photo is a fresh reading of the form, but the user has not
    un-filled the fields they already did."""
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    client.post(
        "/turn",
        data={
            "session_id": sid,
            "kind": "done",
            "field_key": _keys(client, sid)["Dwelling Type"],
        },
    )
    body = _scan(client, sid).json()
    assert _keys(client, sid)["Dwelling Type"] in body["completed"]


def test_session_stores_no_values_at_rest(client):
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    mobile = _keys(client, sid)["Mobile Number"]
    client.post(
        "/turn", data={"session_id": sid, "kind": "done", "field_key": mobile}
    )

    stored = store.get(sid).to_dict()
    assert stored["completed"] == [mobile]
    for f in stored["fields"]:
        assert set(f) == {"key", "label", "kind", "options", "has_value", "notes"}


def test_duplicate_labels_are_tracked_separately():
    """Regression: the real Dec 2025 form carries "Name (in BLOCK LETTERS, as
    in NRIC)" and "Mobile Number" twice - once in Section 1A for the
    applicant, once in Section 1B for a family member.

    Found by running the live vision agent against the published PDF. Keying
    completion off the label ticked both at once.
    """
    from app.agents.vision import DetectedField, assign_keys
    from app.session import FormSession

    session = FormSession(session_id="dup")
    session.fields = assign_keys([
        DetectedField(label="Name (in BLOCK LETTERS, as in NRIC)", kind="text"),
        DetectedField(label="Mobile Number", kind="number"),
        DetectedField(label="Name (in BLOCK LETTERS, as in NRIC)", kind="text"),
        DetectedField(label="Mobile Number", kind="number"),
    ])

    keys = [f.key for f in session.fields]
    assert len(set(keys)) == 4, "keys must be unique even when labels are not"

    # Finish the applicant's name only.
    session.mark_complete(keys[0])

    done = session.completed_set
    assert keys[0] in done
    assert keys[2] not in done, "finishing 1A must not tick the 1B field"
    assert session.completed_labels() == ["Name (in BLOCK LETTERS, as in NRIC)"]

    # Lookup resolves to the right one of the pair.
    assert session.field_by_key(keys[3]).label == "Mobile Number"
    assert session.label_for(keys[2]) == "Name (in BLOCK LETTERS, as in NRIC)"


def test_keys_survive_a_firestore_round_trip():
    """Keys are persisted, not recomputed, so a reload cannot re-map which
    field a user already finished."""
    from app.agents.vision import DetectedField, assign_keys
    from app.session import FormSession

    original = FormSession(session_id="rt")
    original.fields = assign_keys([
        DetectedField(label="Mobile Number", kind="number"),
        DetectedField(label="Mobile Number", kind="number"),
    ])
    original.mark_complete(original.fields[1].key)

    restored = FormSession.from_dict(original.to_dict())
    assert [f.key for f in restored.fields] == [f.key for f in original.fields]
    assert restored.completed == [original.fields[1].key]


def test_simple_mode_is_sticky_on_the_session(client):
    """Asked for once, remembered. The client sends it with each ask, but a
    reload that forgets to must not silently drop the preference."""
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    key = _keys(client, sid)["Dwelling Type"]

    assert store.get(sid).simple is False
    client.post("/turn", data={
        "session_id": sid, "kind": "ask", "field_key": key, "simple": "true"})
    assert store.get(sid).simple is True

    # An ask that omits the flag entirely leaves it alone.
    client.post("/turn", data={"session_id": sid, "kind": "ask", "field_key": key})
    assert store.get(sid).simple is True

    client.post("/turn", data={
        "session_id": sid, "kind": "ask", "field_key": key, "simple": "false"})
    assert store.get(sid).simple is False


def test_simple_mode_survives_a_firestore_round_trip():
    from app.session import FormSession

    original = FormSession(session_id="rt2", simple=True)
    assert FormSession.from_dict(original.to_dict()).simple is True


def test_simple_mode_reaches_the_prompt():
    """The preference has to change the prompt, not just sit in state."""
    from app.agents.field_explainer import SIMPLE_MODE, _build_prompt

    plain = _build_prompt("Dwelling Type", "", "GUIDANCE", "en", False)
    simple = _build_prompt("Dwelling Type", "", "GUIDANCE", "en", True)

    assert SIMPLE_MODE.strip() not in plain
    assert SIMPLE_MODE.strip() in simple
    # Shorten the sentences, not the answer - and never patronise.
    assert "Shorten the SENTENCES, not the answer" in SIMPLE_MODE
    assert "Do not talk down" in SIMPLE_MODE
    # The anti-abstraction rule, kept because the first version of this
    # prompt made output WORSE: asked to simplify, the model rewrote
    # "whether you rent or own" as "how you occupy your home". Being
    # explicit about concreteness is what fixed it.
    assert "CONCRETE" in SIMPLE_MODE
    # Whitespace-normalised: the prompt is hard-wrapped, so the phrase spans
    # a line break in the source.
    flat = " ".join(SIMPLE_MODE.split())
    assert "how you occupy your home" in flat


def test_session_at_rest_still_holds_no_values(client):
    """The new preference must not have opened a door for user data."""
    sid = client.post("/session").json()["session_id"]
    _scan(client, sid)
    stored = store.get(sid).to_dict()
    assert set(stored) == {
        "session_id", "form_id", "form_guess", "language", "simple",
        "fields", "completed", "history", "created_at", "updated_at",
    }
