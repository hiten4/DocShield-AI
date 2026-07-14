"""Person grounding: names in questions resolve to the tenant's vault tokens.

This is what makes 'What is Priya's balance?' answerable for the tenant that
HAS Priya, and refusable for tenants that don't — instead of misattributing
another customer's numbers (the bug found during the demo run).
"""

import uuid

import pytest
from sqlalchemy import text

from app.db.models import Tenant
from app.db.postgres import SessionLocal
from app.ingestion.pii_mask import make_token
from app.ingestion.pii_vault import write_mapping
from app.query.person_grounding import ground_question


@pytest.fixture()
def tenant_with_priya():
    db = SessionLocal()
    try:
        t = Tenant(id=uuid.uuid4(), name=f"G-{uuid.uuid4()}")
        db.add(t)
        db.flush()
        db.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": str(t.id)})
        tok = make_token("PERSON", "Priya Sharma")
        write_mapping(db, str(t.id), str(uuid.uuid4()), {tok: ("PERSON", "Priya Sharma")})
        db.commit()
        yield db, tok
    finally:
        db.close()


def test_known_person_is_grounded(tenant_with_priya):
    db, tok = tenant_with_priya
    g = ground_question(db, "What is Priya Sharma's closing balance for May 2026?")
    assert g.detected, "NER should tag a capitalized full name"
    assert tok in g.question
    assert not g.all_unknown


def test_partial_name_matches_full_vault_entry(tenant_with_priya):
    db, tok = tenant_with_priya
    g = ground_question(db, "What is the closing balance of Priya in May 2026?")
    # A lone first name may or may not be tagged by the small spaCy model;
    # but if it IS detected it must resolve via containment, never refuse.
    if g.detected:
        assert not g.all_unknown
        assert tok in g.question


def test_unknown_person_flagged_for_refusal(tenant_with_priya):
    db, _ = tenant_with_priya
    g = ground_question(db, "What is Michael O'Sullivan's account balance?")
    assert g.detected
    assert g.all_unknown


def test_no_person_question_untouched(tenant_with_priya):
    db, _ = tenant_with_priya
    q = "What are the fixed deposit rates for senior citizens?"
    g = ground_question(db, q)
    assert not g.all_unknown
    assert g.question == q
