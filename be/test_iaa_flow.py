"""
Test: volledige IAA-keten voor Vondr DSGO datadienst.

Flow:
1. Provider definieert documenten, rollen, en delegaties
2. Consumer authenticeert via DSGO (iSHARE)
3. Provider checkt: is consumer een geldige DSGO-deelnemer?
4. Provider checkt: heeft consumer een delegatie voor dit document?
5. Return documenten of 403
"""

from src.dsgo.auth import DSGOAuth
from src.dsgo.config import get_config
from src.dsgo.registry import DSGORegistry

# ─── STAP 1: Provider definieert documenten ──────────────────────────

DOCUMENTS = {
    "doc-001": {
        "filename": "Constructieberekening_fundering.pdf",
        "standaard": "NEN-EN 1997-1",
        "eigenaar": "Ingenieursbureau Jansen",
        "fase": "Realisatie",
        "snippet": "Funderingsdiepte 5.5m op basis van sonderingen conform NEN-EN 1997-1...",
    },
    "doc-002": {
        "filename": "Bestek_installaties_V3.docx",
        "standaard": "NEN 2767",
        "eigenaar": "Ingenieursbureau Jansen",
        "fase": "Ontwerp",
        "snippet": "Conditiemeting installaties conform NEN 2767, classificatie 1-6...",
    },
    "doc-003": {
        "filename": "Bouwtekening_begane_grond.pdf",
        "standaard": "NEN 2580 / BIM Basis ILS",
        "eigenaar": "Architectenbureau Visser",
        "fase": "Ontwerp",
        "snippet": "Oppervlakteberekening en indelingstekening begane grond conform NEN 2580...",
    },
    "doc-004": {
        "filename": "Inspectierapport_brandveiligheid.pdf",
        "standaard": "NEN 6068",
        "eigenaar": "Bureau Brandveiligheid NL",
        "fase": "Realisatie",
        "snippet": "Brandwerendheid draagconstructie getoetst conform NEN 6068, WBDBO 60 min...",
    },
}


# ─── STAP 2: Provider definieert rollen + welke docs ze mogen zien ───

ROLES = {
    "Opdrachtgever": ["doc-001", "doc-002", "doc-003", "doc-004"],
    "Aannemer": ["doc-001", "doc-002", "doc-003"],
    "Onderaannemer": ["doc-001", "doc-003"],
    "Toezichthouder": ["doc-001", "doc-004"],
}


# ─── STAP 3: Provider koppelt DSGO-organisaties aan rollen ──────────

DELEGATIONS = {
    # did:ishare van de organisatie → rol
    "did:ishare:EU.NL.NTRNL-98499327": "Opdrachtgever",    # Vondr zelf (voor test)
    "did:ishare:EU.NL.NTRNL-09036504": "Aannemer",         # ARCADIS
    "did:ishare:EU.NL.NTRNL-38020751": "Toezichthouder",   # Witteveen+Bos
}


# ─── STAP 4: Consumer probeert data op te halen ─────────────────────

def provider_handle_request(consumer_id: str, registry: DSGORegistry, query: str | None = None):
    """Simulate a provider handling a consumer's data request."""

    print(f"\n{'='*60}")
    print(f"INKOMEND VERZOEK van: {consumer_id}")
    print(f"{'='*60}")

    # --- IDENTIFICATIE: ken ik deze partij? ---
    print("\n[1] IDENTIFICATIE — Is dit een bekende DSGO-deelnemer?")
    try:
        party = registry.get_party(consumer_id)
        print(f"    ✓ Gevonden: {party.name}")
        print(f"    ✓ Membership: {party.membership_status}")
    except Exception as e:
        print(f"    ✗ ONBEKENDE PARTIJ — verzoek geweigerd")
        print(f"    Error: {e}")
        return

    # --- AUTHENTICATIE: heeft deze partij de juiste DSGO-rol? ---
    print("\n[2] AUTHENTICATIE — Is dit een actieve ServiceConsumer?")
    if party.is_service_consumer:
        print(f"    ✓ {party.name} heeft rol ServiceConsumer")
    else:
        print(f"    ✗ {party.name} is GEEN ServiceConsumer — verzoek geweigerd")
        return

    # --- AUTORISATIE: heeft deze partij een delegatie? ---
    print("\n[3] AUTORISATIE — Heeft deze partij een delegatie?")
    if consumer_id not in DELEGATIONS:
        print(f"    ✗ Geen delegatie gevonden voor {party.name}")
        print(f"    ✗ 403 FORBIDDEN — geen toegang tot documenten")
        return

    role = DELEGATIONS[consumer_id]
    allowed_docs = ROLES[role]
    print(f"    ✓ Delegatie gevonden: rol '{role}'")
    print(f"    ✓ Toegang tot {len(allowed_docs)} van {len(DOCUMENTS)} documenten")

    # --- RESULTAAT: lever documenten ───
    print(f"\n[4] RESULTAAT — Documenten voor {party.name} (rol: {role})")
    print(f"    Zoekopdracht: '{query or '*'}'\n")

    accessible = 0
    blocked = 0
    for doc_id, doc in DOCUMENTS.items():
        if doc_id in allowed_docs:
            if query is None or query.lower() in doc["snippet"].lower() or query.lower() in doc["filename"].lower():
                accessible += 1
                print(f"    ✓ {doc['filename']}")
                print(f"      Standaard: {doc['standaard']}")
                print(f"      \"{doc['snippet'][:60]}...\"")
                print()
        else:
            blocked += 1
            print(f"    🔒 {doc['filename']}")
            print(f"      GEEN TOEGANG — vereist andere rol")
            print()

    print(f"    Samenvatting: {accessible} toegankelijk, {blocked} geblokkeerd")


def test_arcadis_as_aannemer(registry: DSGORegistry):
    """Test met ARCADIS als Aannemer (heeft delegatie, beperkte docs)."""
    provider_handle_request(
        consumer_id="did:ishare:EU.NL.NTRNL-09036504",  # ARCADIS
        registry=registry,
        query="fundering",
    )


def test_wb_as_toezichthouder(registry: DSGORegistry):
    """Test met Witteveen+Bos als Toezichthouder (heeft delegatie, andere docs)."""
    provider_handle_request(
        consumer_id="did:ishare:EU.NL.NTRNL-38020751",  # Witteveen+Bos
        registry=registry,
        query=None,  # alle docs
    )


def test_consumer_with_delegation(registry: DSGORegistry):
    """Test met Vondr als consumer (heeft delegatie als Opdrachtgever)."""
    provider_handle_request(
        consumer_id="did:ishare:EU.NL.NTRNL-98499327",  # Vondr
        registry=registry,
        query="fundering",
    )


def test_unknown_consumer(registry: DSGORegistry):
    """Test met een onbekende partij (niet in DSGO)."""
    provider_handle_request(
        consumer_id="did:ishare:EU.NL.FAKE-00000000",
        registry=registry,
    )


def main():
    print("Vondr DSGO Datadienst — IAA Test")
    print("=" * 60)

    # Authenticeer Vondr bij DSGO
    config = get_config()
    auth = DSGOAuth(**config)
    registry = DSGORegistry(auth)

    print("Vondr geauthenticeerd bij DSGO Participant Registry ✓\n")

    print("\n" + "=" * 60)
    print("TEST 1: Vondr als Opdrachtgever (heeft delegatie, alle docs)")
    test_consumer_with_delegation(registry)

    print("\n" + "=" * 60)
    print("TEST 2: ARCADIS als Aannemer (ziet 3/4 docs)")
    test_arcadis_as_aannemer(registry)

    print("\n" + "=" * 60)
    print("TEST 3: Witteveen+Bos als Toezichthouder (ziet andere docs)")
    test_wb_as_toezichthouder(registry)

    print("\n" + "=" * 60)
    print("TEST 4: Onbekende partij (niet in DSGO)")
    test_unknown_consumer(registry)

    print("\n" + "=" * 60)
    print("TEST 5: Poort8 (in DSGO, maar GEEN delegatie)")
    provider_handle_request(
        consumer_id="did:ishare:EU.NL.NTRNL-76660680",  # Poort8
        registry=registry,
        query="fundering",
    )


if __name__ == "__main__":
    main()
