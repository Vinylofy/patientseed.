# EAN en ARTIST_TITLE binnen de bestaande factory

## Bestaande architectuur

`collector/public-queue.json` bevat 3.353 bronregels: de oorspronkelijke 3.303 en de 50 Findyl-vermeldingen. `manual-collector-cycle.yml` gebruikt de bestaande `batch_limit` en `reset_cursor`, `recon.probe`, vier platformadapters en `build_scrapers.build`. Bronhistorie staat op `collector-progress`; scraperprofielen op `scraper-builds`; inhoudelijke EAN-toelating en herstel op `scraper-quality`. `scraper-status.md` is de centrale voortgangslijst. Een listingproef, een geïmporteerde wrapper en een productiegeschikte scraper zijn verschillende bewijspunten.

De oude EAN-admission blijft intact. Die controleert listingprijzen en productgebonden detailgegevens, geldige GTIN-checksums en expliciete variantkoppeling. De bestaande geplande prijs- en EAN-workers blijven alleen de oorspronkelijke toegelaten profielen gebruiken.

## Uitbreiding

De bestaande batchactie krijgt `scraper_type=AUTO|EAN|ARTIST_TITLE`. AUTO houdt EAN als voorkeur en beoordeelt vervolgens Artist + Title. Dit selecteert de aanvullende kandidaatbouw; de bestaande bronopties en oude scraperbestanden blijven behouden. Zodra de oude bronqueue is doorlopen, gebruikt dezelfde actie zijn bestaande tien dagelijkse tijdslots voor de nieuwe beoordeling. Geen nieuwe internationale lijst of parallelle factory is gemaakt.

De versie-2-beoordeling:

- Hergebruikt de bestaande bronreconnaissance, listingadapters, prijscontrole, productgebonden JSON-LD-detailcontrole, GTIN-validator en builder.
- Behoudt ongewijzigde reeds bewezen EAN-toelatingen zonder opnieuw ontwikkelen. Dit is historische technische toelating, geen claim over de huidige gezondheid van iedere worker.
- Gebruikt maximaal één begrensde listingselectie en drie verspreide, verschillende productdetails voor positieve nieuwe classificaties. Maximaal zestien verzoeken per shop, inclusief robots.txt, brononderzoek en detailproeven; geen volledige cataloguscrawl.
- Vereist minstens 80% geldige eigen-product-GTIN's in de detailproef voor een nieuwe EAN-classificatie. Geldige codes moeten per verschillend product consistent zijn. Numerieke SKU's en URL-ID's zijn geen GTIN-bewijs.
- Kan ARTIST_TITLE kiezen als EAN niet voldoende is bewezen, minstens 80% van de listings een consistent herkenbare identiteit heeft en alle drie productdetails hun eigen prijs en identiteit bevestigen.
- Gebruikt uitsluitend expliciete artiest-attributen of een consequent enkelvoudig `Artiest - Album`-formaat. Vendor/label is geen artiest. Meervoudige ambigue splitsingen leveren geen gok op.
- Behoudt de bestaande policy: vinyl zonder tweedehands-signaal wordt als nieuw behandeld. De detailproef registreert of dit expliciet NewCondition is of de bestaande afwezigheid-van-used-signaalregel. Expliciete UsedCondition, grading of tegenstrijdige conditiewaarden leiden tot MANUAL_REVIEW. Bestaande EAN-profielen worden niet aangepast.
- Bewijst geen volledige EAN-dekking of volledig assortiment op basis van deze kleine proef. Productaantallen blijven onbekend zonder passende bron. Oude Excel-aantallen blijven alleen als gedateerd-onbekende historische bronmetadata bewaard.
- Maakt onderscheid tussen EAN, ARTIST_TITLE, UNSUITABLE en MANUAL_REVIEW. Een toegangsblokkade of onbekende catalogusroute is review met concrete reden, geen bewijs dat een winkel nooit scrape-baar is. Alleen bewezen ongeschiktheid wordt definitief afgewezen.

`collector/shop-metadata.json` herstelt aangeleverde landcodes uit kolom B van de ongewijzigde oorspronkelijke Excel: 3.301 US en 2 GB. Het bevat geen NL of BE. Voor de 50 toegevoegde Findyl-bronregels wordt geen vestigingsland uit domein of valuta verzonnen. De volgorde is NL, BE, GB, US, overig/onbekend; binnen landen gaan eerdere EAN-only-afwijzingen voor.

Eigen domeinaliassen delen één beoordeling met alle oorspronkelijke rij-ID's. Verschillende winkels met Facebook/Discogs/andere gedeelde platformdomeinen worden niet samengevoegd: daar blijft de bronrij de identiteit. De huidige 3.353 bronregels vormen daardoor 3.324 afzonderlijke shop-/bronidentiteiten.

## Geschiedenis, bouwen en centrale exports

Iedere beoordeling wordt onveranderlijk opgeslagen onder `assessments/v2/<shop-id>/v2-<run-id>-<attempt>.json` op de bestaande `collector-progress`-branch. De latest-index staat in `assessments/v2/index.json`. Oude beoordelingen, bronhistorie en kwaliteitstoelating worden niet overschreven. Bij iedere volgende batch worden reeds beoordeelde versie-2-identiteiten overgeslagen. Bij een toekomstige nieuwe beoordelingsversie kan een nieuw historisch record worden toegevoegd.

Geschikte nieuwe kandidaten gebruiken de bestaande builder met dezelfde native platformadapter. Alleen ARTIST_TITLE krijgt een identiteits-overlay; die verandert geen listingprijs, valuta of beschikbaarheid en verzint geen identifier. Kandidaten worden geïmporteerd en getest tegen de daadwerkelijk opgehaalde listing. Dit is nog geen volledige handmatige scraperacceptatie. Als de bestaande techniek onvoldoende bewijs geeft, blijft de shop geblokkeerd voor verdere ontwikkeling met de bronreden. De bestaande EAN-reparatie- en freeze-flow blijft ongewijzigd.

Nieuwe broncode staat onveranderlijk op `scraper-builds` onder `collector/candidates/v2/<assessment-id>/<slug>.py` en `.json`, met `AWAITING_MANUAL_TEST` en `production_approved=false`. Operationele bestanden onder `collector/generated` blijven onaangetast. Deze kandidaatnamespace is uitgesloten van de bestaande automatische admission/collectors, die alleen de oorspronkelijke generated-root gebruiken.

De enige voortgangslijst blijft `scraper-status.md`, met een aanvullende sectie EAN / Artist + Title. Vaste, steeds bijgewerkte CSV-exports staan op `collector-progress` in `assessment-exports/v2/`:

- `all.csv`
- `artist-title.csv`
- `ean.csv`
- `manual-review.csv`
- `unsuitable.csv`
- `assessment-ready.csv`

Er komen geen aparte voortgangssheets per batch. Volledige bewijsdetails blijven in de historische JSON-records en het batchartifact. Spreadsheetformules uit onbetrouwbare shopnamen worden bij CSV-export als tekst behandeld.

`assessment_ready` betekent uitsluitend voldoende beoordeling voor toekomstige ontwikkel-/overdrachtsbespreking; geen productieacceptatie. Onbekend land voorkomt deze readiness, maar blokkeert een technisch geschikte read-only kandidaatscraper niet. Geen daadwerkelijke overdracht, matching of databasepublicatie is toegevoegd.

## Handmatig testen met bestaande opties

Gebruik de bestaande **SCRAPER | Manual | Single scraper**. Kies `scraper_slug=CANDIDATE`, vul `candidate_ref` uit de centrale lijst in (`assessment-id/slug`) en kies de bestaande `price`-modus. Deze levert ook artiest en titel. De bestaande `ean`-modus is alleen beschikbaar voor EAN-kandidaten. Bestaande dropdownopties en profielen blijven werken. De kandidaat krijgt hierdoor nog geen schedule of databasewrite.

## Veiligheidsgrenzen

Publieke collectie blijft credentialvrij. GitHub-authenticatie bestaat alleen in de laad-/publicatiestappen. Robots.txt en bestaande HTTPS-, domein-, request-, runtime- en responsegroottegrenzen worden gehandhaafd. Bij 401/403/429 wordt de shop niet verder benaderd. Geen login, CAPTCHA-bypass, betaalde jobs, MusicBrainz-matches, importers, databasewrites, migraties, frontendwijzigingen of wijzigingen aan private productieprocessen.

Na de begrensde live proeven is `collector/assessment-policy.json` aangezet. De bestaande tien dagelijkse slots verwerken maximaal 100 volgende shopidentiteiten per run. Iedere shop wordt eenmaal per beleidsrevisie beoordeeld; reviews worden niet eindeloos opnieuw benaderd. GitHub kan geplande runs vertragen; 1.000 per dag is een bovengrens, geen gegarandeerde doorvoer. Een batch heeft bovendien een tijdsbudget en kan daardoor minder shops afwerken. `reset_cursor` blijft de bestaande legacy-bronreset en is niet nodig om de nieuwe beoordeling over de al doorlopen lijst te laten starten.

## Eerste proef en beleidsrevisie

De eerste tien beoordelingen zijn onveranderd opgeslagen onder assessment-versie 2. De aanvullende beleidsrevisie 2.1 herstelt de bestaande nieuw-policy in plaats van een nieuwe verplichte NewCondition-gate. Nieuwe records verwijzen naar de nieuwe revision en datum; de eerste JSON-records worden niet herschreven. Eerdere 401/403/429/robots-blokkades worden bij deze revisie met verwijzing behouden, zonder de verboden route opnieuw te benaderen.

## Vastgelegde live proeven — 27 oktober 2026

[Herproef van tien shops](https://github.com/Vinylofy/patientseed./actions/runs/40568772977): vier ARTIST_TITLE-kandidaten gebouwd en tegen de live listing getest; zes shops blijven MANUAL_REVIEW. Er waren geen Nederlandse bronregels beschikbaar voor een NL-pilot. De oorspronkelijke te strikte proef blijft als historie bewaard.

| Shop | Uitkomst | Reden / kandidaat |
| --- | --- | --- |
| Assai Records | MANUAL_REVIEW | Eigen detailprijs/valuta niet voldoende bewezen of afwijkend |
| Resident Music | MANUAL_REVIEW | HTTP 403; bestaande blokkade behouden zonder nieuwe bronaanvraag |
| 10,000 Hz Records | ARTIST_TITLE | `v2-40568772977-1/10000hzrecords_com` |
| Abrodos Music | MANUAL_REVIEW | Nieuwe/tweedehands conditie niet betrouwbaar te scheiden |
| AFK Books & Records | MANUAL_REVIEW | Begrensde listing bewijst vinyl, prijs, voorraad en productlinks onvoldoende |
| AGS Honolulu (Aloha Got Soul) | ARTIST_TITLE | `v2-40568772977-1/ags_earth` |
| All The Best | ARTIST_TITLE | `v2-40568772977-1/allthebestflorence_com` |
| Antone’s Record Shop | MANUAL_REVIEW | Artiest/titel niet consistent bewezen |
| art sound language | ARTIST_TITLE | `v2-40568772977-1/artsoundlanguage_com` |
| Bent Crayon Records | MANUAL_REVIEW | Onvoldoende betrouwbaar herkenbare artiest/titel in listing |

[Afzonderlijke Single scraper-proef](https://github.com/Vinylofy/patientseed./actions/runs/40569588169) voor 10,000 Hz: vijf records, geen fouten, `database_write=false`, met artiest, titel, variantlink en prijzen 23,99–26,99 USD. Dit zijn records inclusief varianten, geen claim over vijf unieke albums of productieacceptatie.

95 tests en actionlint voor beide aangepaste workflows zijn geslaagd. De kandidaatpublicatie veranderde geen bestanden onder `collector/generated` ten opzichte van de toestand direct vóór publicatie. Handmatige inhoudelijke acceptatie en eventuele latere overdracht naar curedplant blijven afzonderlijke stappen.
