"""Calibration tests for the form matcher.

The field lists below are REAL - captured from the live vision agent reading
the published Dec 2025 CHAS PDF, not invented. That matters, because the
expensive failure here is a false "I don't know this form" on the actual
demo form, and only real readings would catch it.

Page 2 is the interesting case: the model named it "Application Form -
Particulars of Main Applicant and Family Members", which does not contain
the word CHAS at all. Matching on the form name alone would have failed it.
"""
import os

os.environ.setdefault("USE_STUB", "true")

from app.form_match import match

# Live vision output, chas_p2.jpg (Sections 1A and 1B).
CHAS_P2_GUESS = "Application Form - Particulars of Main Applicant and Family Members"
CHAS_P2_FIELDS = [
    "Name (in BLOCK LETTERS, as in NRIC)",
    "Pink NRIC / Birth Certificate Number (Main Applicant must be a Singapore Citizen)",
    "Email Address (Optional)",
    "Mobile Number",
    "Mailing Address (if different from NRIC)",
    "Home Phone Number",
    "Dwelling Type (based on NRIC address)",
    "Rental Status of Residence",
    "Name (in BLOCK LETTERS, as in NRIC)",
    "Pink NRIC / Blue NRIC / Birth Certificate Number / FIN",
    "Relationship to Main Applicant",
    "Mobile Number (Optional)",
]

# Live vision output, chas_p7.jpg (Section 3, the signature page).
CHAS_P7_GUESS = "CHAS Application Form"
CHAS_P7_FIELDS = [
    "Main Applicant's Name:",
    "Signature/ Thumbprint of Main Applicant/ Representative* (Date):",
    "Name of Representative",
    "I declare that I am (tick one of the checkboxes):",
    "The name of the interpreter is (name),",
    "(NRIC)",
    "(contact number).",
]

# A Schengen visa application - the form from the project's own origin
# story, and the one we must NOT pretend to understand.
VISA_GUESS = "Application for Schengen Visa"
VISA_FIELDS = [
    "Surname (Family name)",
    "Date of birth",
    "Place of birth",
    "Current nationality",
    "Type of travel document",
    "Purpose of the journey",
    "Member State of main destination",
    "Travel medical insurance",
    "Proof of accommodation",
    "Intended date of arrival",
]


def test_recognises_the_fields_page_despite_a_generic_name():
    """The regression this file exists for: page 2's own heading never says
    CHAS, so the field labels have to carry the match."""
    m = match(CHAS_P2_GUESS, CHAS_P2_FIELDS)
    assert m.known, f"false negative on the real demo form (score={m.score})"
    assert "nric" in m.matched
    assert "dwelling type" in m.matched


def test_recognises_the_signature_page():
    """Far fewer markers - the page is mostly signature boxes - but the form
    name carries it. This is the page the gate demo runs on."""
    m = match(CHAS_P7_GUESS, CHAS_P7_FIELDS)
    assert m.known, f"false negative on the gate demo page (score={m.score})"


def test_rejects_a_visa_form():
    m = match(VISA_GUESS, VISA_FIELDS)
    assert m.unknown
    assert m.score == 0


def test_rejects_an_unreadable_scan():
    assert match("", []).unknown


def test_markers_match_whole_words_only():
    """"fin" must not match inside "confirm" or "define". A false positive
    here silently re-enables guidance on a form we know nothing about."""
    m = match("Expense claim", ["Please confirm the amount", "Define your cost centre"])
    assert m.unknown
    assert m.score == 0


def test_a_single_field_mention_is_not_enough():
    """Plenty of Singapore forms ask for an NRIC. One mention should not
    make an unrelated document look like the one we hold guidance for."""
    m = match("Club membership application", ["NRIC number", "Preferred tee time"])
    assert m.unknown, f"one NRIC mention was treated as a match (score={m.score})"


def test_the_form_name_alone_is_enough():
    """Naming the scheme is strong evidence, so it counts double."""
    assert match("Community Health Assist application", []).known
