from __future__ import annotations

NORMS_CATALOG = [
    {"code": "NEN 2580", "label": "NEN 2580", "category": "metingen"},
    {"code": "NEN 2767", "label": "NEN 2767", "category": "inspectie"},
    {"code": "NEN 6068", "label": "NEN 6068", "category": "brandveiligheid"},
    {"code": "NEN-EN 1997-1", "label": "NEN-EN 1997-1", "category": "constructie"},
]

GEBORA_ROLES = [
    {
        "code": "Opdrachtgever",
        "label": "Opdrachtgever",
        "description": "Projecteigenaar of opdrachtgever.",
    },
    {
        "code": "Aannemer",
        "label": "Aannemer",
        "description": "Uitvoerende hoofdaannemer.",
    },
    {
        "code": "Onderaannemer",
        "label": "Onderaannemer",
        "description": "Gespecialiseerde uitvoerende partij.",
    },
    {
        "code": "Toezichthouder",
        "label": "Toezichthouder",
        "description": "Controlerende of toezichthoudende partij.",
    },
    {
        "code": "Asset Eigenaar",
        "label": "Asset Eigenaar",
        "description": "Strategisch beheer van assets, stelt doelen en kaders.",
    },
    {
        "code": "Asset Manager",
        "label": "Asset Manager",
        "description": "Beheer en optimalisatie van fysieke assets.",
    },
    {
        "code": "Taxateur",
        "label": "Taxateur",
        "description": "Bepaalt waarde van onroerend goed.",
    },
    {
        "code": "Makelaar",
        "label": "Makelaar",
        "description": "Bemiddelt bij aan- en verkoop, huur en verhuur.",
    },
    {
        "code": "Notaris",
        "label": "Notaris",
        "description": "Regelt juridische documenten en overeenkomsten in vastgoed.",
    },
    {
        "code": "Architect",
        "label": "Architect",
        "description": "Ontwerpt gebouwen en stedelijke gebieden.",
    },
    {
        "code": "Ontwikkelaar",
        "label": "Ontwikkelaar",
        "description": "Ontwikkelt bouwprojecten of gebieden.",
    },
    {
        "code": "Bevoegd gezag",
        "label": "Bevoegd gezag",
        "description": "Verzorgt vergunningen, toezicht en handhaving.",
    },
    {
        "code": "Ingenieur",
        "label": "Ingenieur",
        "description": "Past technische kennis toe op bouw en infra.",
    },
    {
        "code": "Bouwbedrijf",
        "label": "Bouwbedrijf",
        "description": "Coordineert en voert bouwprojecten uit.",
    },
    {
        "code": "Producent",
        "label": "Producent",
        "description": "Produceert bouwmaterialen en componenten.",
    },
    {
        "code": "Transporteur",
        "label": "Transporteur",
        "description": "Vervoert bouwmaterialen en apparatuur.",
    },
    {
        "code": "Leverancier",
        "label": "Leverancier",
        "description": "Levert materialen aan bouwprojecten.",
    },
    {
        "code": "Installateur",
        "label": "Installateur",
        "description": "Realiseert technische installaties zoals HVAC, sanitair en elektra.",
    },
    {
        "code": "Registrerende instantie",
        "label": "Registrerende instantie",
        "description": "Houdt officiele registraties van vastgoed bij.",
    },
    {
        "code": "Huurder",
        "label": "Huurder",
        "description": "Huurt onroerend goed.",
    },
    {
        "code": "Gebruiker",
        "label": "Gebruiker",
        "description": "Gebruikt een gebouw, ruimte of infrastructuur.",
    },
    {
        "code": "Beheerder",
        "label": "Beheerder",
        "description": "Beheert en optimaliseert gebouw of infrastructuur.",
    },
    {
        "code": "Financier",
        "label": "Financier",
        "description": "Verstrekt financiele middelen voor projecten.",
    },
    {
        "code": "Certificerende instantie",
        "label": "Certificerende instantie",
        "description": "Beoordeelt conformiteit aan normen.",
    },
    {
        "code": "Arbeidsbemiddelaar",
        "label": "Arbeidsbemiddelaar",
        "description": "Leent gespecialiseerd personeel uit.",
    },
    {
        "code": "Kwaliteitsborger",
        "label": "Kwaliteitsborger",
        "description": "Houdt toezicht op bouwkwaliteit onder de WKB.",
    },
    {
        "code": "Verhuurder",
        "label": "Verhuurder",
        "description": "Verhuurt vastgoed.",
    },
    {
        "code": "Hypotheekverstrekker",
        "label": "Hypotheekverstrekker",
        "description": "Verstrekt leningen met vastgoed als onderpand.",
    },
    {
        "code": "Adviseur",
        "label": "Adviseur",
        "description": "Geeft expertadvies en begeleiding bij bouwprojecten.",
    },
    {
        "code": "Nutsbedrijf",
        "label": "Nutsbedrijf",
        "description": "Levert essentiele diensten zoals elektra, gas en water.",
    },
    {
        "code": "Onderhoudsbedrijf",
        "label": "Onderhoudsbedrijf",
        "description": "Voert onderhoud en reparatie aan gebouwen en installaties uit.",
    },
    {
        "code": "Sloopbedrijf",
        "label": "Sloopbedrijf",
        "description": "Verzorgt sloop en oogst van materialen.",
    },
    {
        "code": "Materieel verhuurder",
        "label": "Materieel verhuurder",
        "description": "Verhuurt bouw- en constructieapparatuur.",
    },
    {
        "code": "Regelinghouder",
        "label": "Regelinghouder",
        "description": "Beheert normen en kwalificatiesystemen.",
    },
    {
        "code": "Vakpersoon",
        "label": "Vakpersoon",
        "description": "Vult als persoon een actieve rol in bouw of infra in.",
    },
    {
        "code": "Vakbedrijf",
        "label": "Vakbedrijf",
        "description": "Vult als bedrijf een actieve rol in bouw of infra in.",
    },
    {
        "code": "Vakopleider",
        "label": "Vakopleider",
        "description": "Traint en leidt bouwprofessionals op.",
    },
    {
        "code": "Recyclebedrijf",
        "label": "Recyclebedrijf",
        "description": "Verzorgt hergebruik en recycling van bouwafval.",
    },
    {
        "code": "Groothandel",
        "label": "Groothandel",
        "description": "Koopt bouwmaterialen in en verkoopt deze door.",
    },
    {
        "code": "Uitvoeringsorganisatie",
        "label": "Uitvoeringsorganisatie",
        "description": "Voert operationele taken namens een ministerie uit.",
    },
]

NEN_2084_DOCUMENT_TYPES = [
    {"code": "Overeenkomst", "label": "Overeenkomst", "category": "Contractueel"},
    {"code": "Bestek", "label": "Bestek", "category": "Contractueel"},
    {"code": "Vergunning", "label": "Vergunning", "category": "Contractueel"},
    {"code": "Beschikking", "label": "Beschikking", "category": "Contractueel"},
    {"code": "Certificaat", "label": "Certificaat", "category": "Contractueel"},
    {
        "code": "Technische tekening",
        "label": "Technische tekening",
        "category": "Ontwerpend",
    },
    {"code": "Berekening", "label": "Berekening", "category": "Ontwerpend"},
    {
        "code": "Programma van Eisen",
        "label": "Programma van Eisen",
        "category": "Ontwerpend",
    },
    {"code": "Schema", "label": "Schema", "category": "Ontwerpend"},
    {"code": "3D/BIM-model", "label": "3D/BIM-model", "category": "Ontwerpend"},
    {"code": "Rapport", "label": "Rapport", "category": "Verslaggevend"},
    {
        "code": "Inspectieresultaat",
        "label": "Inspectieresultaat",
        "category": "Verslaggevend",
    },
    {
        "code": "Proces-verbaal",
        "label": "Proces-verbaal",
        "category": "Verslaggevend",
    },
    {"code": "Notulen", "label": "Notulen", "category": "Verslaggevend"},
    {"code": "Planning", "label": "Planning", "category": "Planning"},
    {"code": "Begroting", "label": "Begroting", "category": "Planning"},
    {"code": "Handleiding", "label": "Handleiding", "category": "Planning"},
    {"code": "Register", "label": "Register", "category": "Registrerend"},
    {
        "code": "Correspondentie",
        "label": "Correspondentie",
        "category": "Registrerend",
    },
    {"code": "Melding", "label": "Melding", "category": "Registrerend"},
    {"code": "Foto/opname", "label": "Foto/opname", "category": "Registrerend"},
    {"code": "Norm", "label": "Norm", "category": "Normatief"},
    {"code": "Richtlijn", "label": "Richtlijn", "category": "Normatief"},
    {
        "code": "Beleidsdocument",
        "label": "Beleidsdocument",
        "category": "Normatief",
    },
]

GEBORA_VALUE_STREAMS = [
    {
        "code": "1",
        "label": "Strategisch en Tactisch Asset Management",
        "description": "Asset waarde en rendement",
    },
    {
        "code": "2",
        "label": "Investering en financiering",
        "description": "Kapitaal, businesscase en financieringsstructuren",
    },
    {
        "code": "3",
        "label": "Gebieds- en project (her-)ontwikkeling",
        "description": "Initiatie, planvorming en ontwikkeling van gebieden en projecten",
    },
    {
        "code": "4",
        "label": "Bouwwerk realisatie",
        "description": "Uitvoering, bouwproductie en oplevering",
    },
    {
        "code": "5",
        "label": "Aan- en verkoop",
        "description": "Transacties, overdracht en eigendomsoverdracht",
    },
    {
        "code": "6",
        "label": "Exploitatie en commercieel beheer",
        "description": "Operationele exploitatie, verhuur en commercieel rendement",
    },
    {
        "code": "7",
        "label": "Gebruiks ondersteuning en functioneel beheer",
        "description": "Gebruikersdienstverlening en functionele ondersteuning",
    },
    {
        "code": "8",
        "label": "Technisch beheer en onderhoud",
        "description": "Beheer, onderhoud en instandhouding van assets",
    },
    {
        "code": "9",
        "label": "Renovatie en vervanging",
        "description": "Aanpassing, modernisering en vervangingsingrepen",
    },
    {
        "code": "10",
        "label": "Sloop en oogst",
        "description": "Demontage, sloop en materiaalterugwinning",
    },
    {
        "code": "11",
        "label": "Producten en materialen",
        "description": "Materialen, componenten en productspecificaties",
    },
    {
        "code": "12",
        "label": "Personeel",
        "description": "Arbeid, inzetbaarheid en personeelsorganisatie",
    },
    {
        "code": "13",
        "label": "Materieel",
        "description": "Machines, gereedschappen en bedrijfsmiddelen",
    },
    {
        "code": "14",
        "label": "Logistiek en transport",
        "description": "Transport, bevoorrading en logistieke ketens",
    },
    {
        "code": "15",
        "label": "Kwaliteit, vergunning, toezicht, handhaving",
        "description": "Compliance, kwaliteitstoetsing en formeel toezicht",
    },
    {
        "code": "16",
        "label": "Registratie en administratie",
        "description": "Dossiervorming, registratie en administratieve vastlegging",
    },
    {
        "code": "17",
        "label": "Hergebruik van circulaire producten",
        "description": "Herinzet van circulaire materialen en producten",
    },
]
