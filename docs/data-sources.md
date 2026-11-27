# Data sources and their terms

Cabinet reads five outside services. Three need nothing from you. Two,
Numista and PCGS, work with a key you get yourself, and that makes **you**
the party to their terms: Cabinet is software you run, with your key, on
your machine. This page says what each service asks, what Cabinet does
about it, and what stays your responsibility.

It is a reading of the published terms as of 26 November 2026, not legal
advice. Each service's own page is what governs, and terms change.

| Service | What Cabinet uses it for | Key | Its terms |
|---|---|---|---|
| [Numista](https://en.numista.com/api/) | Catalog search and fill, prices by grade, sales records, importing your own Numista collection | Free, yours | [API license](https://en.numista.com/api/license.php) |
| [PCGS](https://www.pcgs.com/publicapi) | Filling a piece from its cert number, price guide and auction prices, population | Free, yours | The API agreement shown in your PCGS API account |
| [gold-api.com](https://gold-api.com) | Today's gold, silver, platinum, and palladium spot prices | None | [Terms](https://gold-api.com/terms) |
| [Frankfurter](https://frankfurter.dev) | Daily exchange rates, for totals in one currency | None | [License page](https://frankfurter.dev/license) |
| [fawazahmed0 currency-api](https://github.com/fawazahmed0/exchange-api) | The spot price on a past purchase day, from March 2024 | None | Public domain (CC0) |

Nothing about your collection is ever sent to any of them. A request
carries a catalog number, a cert number, a metal, or a currency pair, and
nothing else. How each is used, cached, and priced is in
[price-sources.md](price-sources.md).

## Numista

**What the license allows a private collection.** An individual may store
Numista's data for a personal project: private, non-commercial, used by
that person for their own collecting, and not offered to the public
(section 8.4). No time limit is set on that storage. The free plan covers
everything Cabinet uses, up to 2,000 requests a month (section 5).

**What it does not allow.** Publishing or redistributing the stored data,
making it available to third parties, running a public or commercial
service on it, or building a copy of the catalog (sections 8.4 and 11).

**What Cabinet does.**

- Names Numista as the source wherever its data shows (a value is labeled
  "Numista value") and shows the N# beside every catalog search result, as
  section 4 asks.
- Never puts a value made from Numista's data on a share link, whatever
  the link's settings: a Numista estimate, or a comparable-sales median
  that used a sale fetched from Numista, is left out before the shown value
  is worked out.
- Looks up one type at a time, and only what you search for, fill in, or
  already hold in your Numista collection. It never walks the catalog.
- Refreshes prices on a schedule you choose (7, 14, or 30 days, off by
  default). The stored copies are what make your collection readable
  without a request per page, which the license allows a personal project;
  they are not there to get around the monthly limit.

**What stays yours.**

- Your key, and staying a personal project. Running Cabinet as a public or
  commercial service with a Numista key is outside the license.
- **An open question.** A share link shows facts you recorded about a
  piece: country, denomination, composition, weight. "Fill from Numista"
  may have supplied some of them. Whether showing those on a share link
  counts as passing Numista's data to a third party is for Numista to say,
  not Cabinet. The license provides for written authorization (section
  8.1). If you share publicly and want certainty, ask them, or fill those
  pieces in by hand.

## PCGS

**The agreement.** PCGS shows its API End User Agreement when you sign in
to create your API access. Read it there: it is the document that binds
you, and it is not published where this project could read it. The public
terms of PCGS's parent company allow personal, non-commercial use of its
content and forbid public use without written permission, and Cabinet
assumes the API agreement is no looser.

**What Cabinet does.**

- Stays inside PCGS's limit of 100 calls a day: a cert lookup and the
  estimate that follows share one request, answers are kept for seven
  days, the scheduled refresh is weekly and off by default, and Settings
  warns once a collection has more than 100 pieces PCGS can price.
- Labels a PCGS value as one ("PCGS value") and links a cert to PCGS's own
  page for it.
- Never puts a value made from PCGS's price guide or auction prices on a
  share link (from v0.39.0), and never the population figures. If the
  agreement you accepted allows showing them, tell the project: the rule
  exists because the agreement could not be read.

**What stays yours.** Your token, and the agreement you accepted to get it.

## The three keyless services

- **gold-api.com** asks for no attribution and sets no caching rule; it
  asks clients not to send several requests a second. Cabinet asks once per
  metal and keeps the answer.
- **Frankfurter** publishes central-bank reference rates. It asks for no
  credit and allows keeping the rates as long as you like; the figures
  remain subject to the terms of the bank that published them.
- **The fawazahmed0 currency-api** is in the public domain.

One service is deliberately not used: the LBMA price series reaches back
further than any of these, and its terms need a license to use the data
for valuation. See [price-sources.md](price-sources.md).

## Names and trademarks

Cabinet is not affiliated with, endorsed by, or sponsored by Numista,
PCGS, NGC, PMG, or any other service or catalog it mentions. Their names
are used only to say where a value, a lookup, or a reference number comes
from, and they remain the property of their owners. The same is true of
catalog names such as Krause, Friedberg, and Pick.

## If you run Cabinet for others

Cabinet is built for one person's collection on a private network. If you
put an instance where the public can reach it, or run one for customers or
a club, the Numista and PCGS terms above no longer describe your case: a
public instance is not a personal project, and you would need each
service's agreement for what you are doing.
