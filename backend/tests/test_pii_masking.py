from app.ingestion.pii_mask import _plausible_person, find_tokens, mask_text


def test_masks_email_and_password_field():
    text = "Contact: john@example.com. password: hunter2super. Client ID: CID-12345"
    masked, mapping = mask_text(text)
    assert "john@example.com" not in masked
    assert "hunter2super" not in masked
    assert "CID-12345" not in masked
    # mapping is {token: (entity_type, original_value)}
    types = {etype for etype, _ in mapping.values()}
    assert "EMAIL_ADDRESS" in types
    assert "PASSWORD_FIELD" in types
    assert "CLIENT_ID" in types
    # every token in the mapping actually appears in the masked text
    for token in mapping:
        assert token in masked
    assert set(find_tokens(masked)) == set(mapping.keys())


def test_passthrough_on_clean_text():
    text = "The sky is blue today."
    masked, mapping = mask_text(text)
    assert masked == text
    assert mapping == {}


def test_tokens_are_deterministic():
    a, m1 = mask_text("password: hunter2super")
    b, m2 = mask_text("password: hunter2super")
    assert a == b
    assert m1 == m2


def test_person_filter_rejects_finance_phrases():
    # spaCy sm tags these as PERSON in bank statements; they must NOT be masked
    # (that both breaks retrieval and attaches a bogus person to fact chunks).
    assert not _plausible_person("Closing Balance")
    assert not _plausible_person("Fixed Deposit")
    assert not _plausible_person("Payroll Credit")
    assert not _plausible_person("Whole Foods Market")
    assert not _plausible_person("the sky")


def test_person_filter_accepts_real_names():
    assert _plausible_person("Priya Sharma")
    assert _plausible_person("Michael O'Sullivan")
    assert _plausible_person("Jennifer Martinez-Chen")
    assert _plausible_person("Kavita")


def test_finance_phrases_survive_masking():
    text = "Opening Balance on 01 May 2026: INR 1,24,580.00 Closing Balance on 31 May 2026: INR 2,08,145.50"
    masked, _ = mask_text(text)
    assert "Closing Balance" in masked
    assert "Opening Balance" in masked
