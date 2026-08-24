"""Tests für die Ingest-Regeln (FA-02, FA-04, FA-05)."""
from signatur import ingest
from signatur.models import LoadedEmail


def _mail(**kwargs) -> LoadedEmail:
    base = {"source": "test.eml", "from_email": "kontakt@fremd.de",
            "subject": "Angebot", "text_body": "Hallo"}
    base.update(kwargs)
    return LoadedEmail(**base)


def test_internal_sender_is_dropped(config):
    decision = ingest.classify(_mail(from_email="kollege@apa.at"), config)
    assert not decision.accept and decision.rule == "intern"


def test_subdomain_of_internal_domain_is_dropped(config):
    decision = ingest.classify(_mail(from_email="k@mail.apa.at"), config)
    assert not decision.accept and decision.rule == "intern"


def test_blocklist_domain_is_dropped(config):
    decision = ingest.classify(_mail(from_email="news@mailchimp.com"), config)
    assert not decision.accept and decision.rule == "blocklist"


def test_allowlist_limits_processing(config):
    config.allowlist_domains = ["kunde.de"]
    assert not ingest.classify(_mail(from_email="a@fremd.de"), config).accept
    assert ingest.classify(_mail(from_email="a@kunde.de"), config).accept


def test_noreply_and_autoreply_and_newsletter(config):
    assert not ingest.classify(_mail(from_email="no-reply@fremd.de"), config).accept
    assert not ingest.classify(
        _mail(subject="Automatische Antwort: Urlaub"), config).accept
    assert not ingest.classify(
        _mail(headers={"auto-submitted": "auto-replied"}), config).accept
    assert not ingest.classify(
        _mail(headers={"list-unsubscribe": "<mailto:x>"}), config).accept
    assert not ingest.classify(_mail(headers={"precedence": "bulk"}), config).accept


def test_regular_external_mail_is_accepted(config):
    decision = ingest.classify(_mail(), config)
    assert decision.accept and decision.rule == "ok"


def test_message_key_prefers_message_id():
    mail = _mail(message_id="<abc@fremd.de>")
    assert ingest.message_key(mail) == "<abc@fremd.de>"


def test_message_key_falls_back_to_hash():
    key_a = ingest.message_key(_mail(date="Mon, 1 Jan 2026 08:00:00 +0100"))
    key_b = ingest.message_key(_mail(date="Mon, 1 Jan 2026 08:00:00 +0100"))
    key_c = ingest.message_key(_mail(subject="Anderes Thema"))
    assert key_a == key_b and key_a != key_c and key_a.startswith("sha1:")
