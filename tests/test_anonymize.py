from c2k.extract.anonymize import has_raw_volatile, scrub


def test_scrub_card_amount_email_date_phone():
    r = scrub("card 1234 5678 9012, fee 45 USD, mail me at x.y@example.invalid on 12.03.2031, call +1 555 010 2233")
    assert "<card_number>" in r.text
    assert "<amount>" in r.text
    assert "<email>" in r.text
    assert "<date>" in r.text
    assert "<phone_number>" in r.text
    assert set(r.kinds) >= {"card", "amount", "email", "date", "phone"}


def test_scrub_names_with_blocklist():
    r = scrub("this is Mira from desk 14, Mira Okonkwo", names=["Mira Okonkwo"])
    assert "Mira" not in r.text and "<person_name>" in r.text
    assert "name" in r.kinds


def test_scrub_keeps_plain_text():
    r = scrub("the printer near the kitchen is jammed")
    assert r.text == "the printer near the kitchen is jammed"
    assert r.kinds == []


def test_has_raw_volatile_ignores_placeholders():
    assert has_raw_volatile("fee of <amount> on <date>") == []
    assert "amount" in has_raw_volatile("fee of 45 USD")
    assert "name" in has_raw_volatile("ask Tomas", names=["Tomas Vega"])
