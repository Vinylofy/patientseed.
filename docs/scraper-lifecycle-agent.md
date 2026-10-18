# Scraper Lifecycle Agent

The public collector processes one queue shop at a time. A manual cycle records source evidence, probes the bounded set of public catalog methods, ranks the routes that an adapter can actually parse, and uses the best proven route for the listing/detail pilot. A scraper wrapper is built only when that selected adapter and the detail gate pass.

Discovery is evidence-based rather than platform-name based. The run artifact records every tested route in `method_candidates` and the selected route in `selected_method`; the generated scraper profile carries both fields forward. A rejected route or an unknown platform remains a review/blocker and is never silently converted into a scraper.

- `collector/scraper-lifecycle.json` is the durable central state file.
- `collector/scraper-lifecycle.md` is the human-readable status view.
- `collector/frozen/<domain>/status.json` records shops after three unsuccessful build attempts.
- `collector/generated/` is published to the private-free `scraper-builds` branch after a successful build.
- `scraper-price-refresh.yml` and `scraper-ean-refresh.yml` collect artifacts only; they never write Supabase or any database.

The price workflow runs every two days. The EAN workflow is limited to 250 detail records per day. A later private importer can review these artifacts and perform any database synchronization separately.

The public discovery cycle is scheduled ten times per UTC day at two-hour intervals, with a batch size of 100. It advances the durable queue cursor and uses a concurrency lock so batches do not overlap. A manual dispatch remains available for recovery or a deliberate restart.

## Naming convention and single-scraper view

Actions use the prefixes `SCRAPER | Batch | ...` for scheduled batches and `SCRAPER | Manual | ...` for a deliberate single-scraper pilot. Generated profiles use the stable domain slug (`<domain-with-non-alphanumeric-replaced-by-underscores>`), for example `22soundrecords_com`. The scheduled workflows write a per-scraper table to the GitHub job summary. The `SCRAPER | Manual | Single scraper` workflow accepts one slug and runs only that profile without changing health state.

Each currently published profile also has its own visible manual workflow under `.github/workflows/scrapers/`, named `SCRAPER | <slug>`. These small workflows call the shared reusable runner, so scraper logic is not duplicated. GitHub Actions cannot generate workflow files dynamically at runtime; when new profiles are published, a new wrapper must be committed (the generic single-scraper workflow remains available as fallback).

## Inhoudelijke toelating van bestaande builds (18 oktober 2026)

`SCRAPER | Batch | Quality admission and repair` behandelt dagelijks maximaal
25 kandidaten om 00:37 UTC (02:37 Nederlandse zomertijd / 01:37 wintertijd).
Nieuwe profielen worden automatisch ontdekt op `scraper-builds`. De bronqueue
wordt niet gereset. Nieuwe kandidaten gaan vóór herhaalde initiële reviews;
workers met twee opeenvolgende fouten krijgen onderhoudsprioriteit.

Een proef gebruikt één listingpagina (maximaal 20 records) en maximaal drie
verschillende detailproducten. Prijs en valuta moeten overeenkomen met
JSON-LD-aanbod van dezelfde productvariant. Shipping/organisatie/andere
producten mogen geen prijsbewijs leveren. EAN/UPC/GTIN gebruikt de GS1-checksum,
conflicterende codes blokkeren en er moet minstens één door de werkende adapter
gelezen code onafhankelijk op de juiste detailpagina bevestigd zijn. Alleen
vinyl zonder tweedehandsbewijs wordt toegelaten. Ontbrekend bewijs is REVIEW,
geen succesvolle scraper. 401/403/429 stopt die shop direct als BLOCKED.

De initiële proef telt apart van maximaal drie latere herstelproeven. Ondersteund
automatisch herstel is begrensd tot alternatieve, eerder adapter-geteste routes
van hetzelfde platform. Dit is geen algemene LLM die willekeurige parsercode
herschrijft. Een blijvend probleem wordt na drie herstelproeven FROZEN; de
exacte wrapper, het profiel en blokkadebewijs worden apart bewaard. Andere
shops gaan door. Parserverbeteringen buiten dit repertoire vragen gericht werk.

Duurzame toestand staat op branch `scraper-quality` in `quality/state.json`;
checkpoint na elke shop, publiceren ook bij normale stapfouten. De volgende
batch slaat goedgekeurde/ongewijzigde en bevroren profielen over. Bij een harde
runnerstop kan alleen het nog niet gepubliceerde deel opnieuw worden getoetst.
`quality/frozen/<slug>/` bevat bevroren bronkopieën en bewijs. Een expliciete
bron/codewijziging krijgt een nieuwe fingerprint en moet opnieuw door de gate.
De centrale lijst **scraper-status.md** krijgt één vervangbare QA-sectie met
batchnummer, bewijs, status en afzonderlijke prijs/EAN-health. Bronhercontroles
behouden deze sectie. Er komen geen losse batchoverzichten bij.

Beide bestaande verzamelplanningen selecteren voortaan uitsluitend exacte
quality-goedgekeurde releases (profiel + wrapper + adapterhash), dynamisch in
groepen van 100 en met een eigen job per scraper. Ook de 57 oude ingeplande
wrappers moeten deze aanvullende gate halen. De prijsplanning blijft eenmaal
per twee dagen, EAN dagelijks, maximaal 250 records per scraper per run.
Dit zijn begrensde listing/detailruns, geen claim op volledige catalogusdekking.
Er worden geen databasewrites of productie-imports uitgevoerd. Deze toelating
is publieke bron-QA en vervangt geen private markt-/productacceptatie.

Losse handmatige workflows blijven beschikbaar. Elke uitgevoerde prijs- of
EAN-run schrijft een eigen onderhoudsobservatie naar
`quality/health/<mode>/<slug>.json`, met token uitsluitend in de publicatiestap.
Een eerste failure is INCIDENT, twee achtereen REPAIR_REQUIRED: de betreffende
release wordt uit de automatische selectie gehouden tot de herstelproef slaagt.
Een succesvolle run reset de foutreeks; een dubbele of oudere observatie telt
niet opnieuw. Bevroren status wordt door een toevallige handmatige run niet
stilzwijgend opgeheven. De dagelijkse QA-batch verwerkt deze herstelgevallen;
de oude onderhoudsregistratie blijft historische informatie.
