# bnf\_place_harmonisation

Script and output data of the process to harmonise the country-level and city-level publication place information in the BNF.

Contains information from the J. Paul Getty Trust, Getty Research Institute, the Getty Thesaurus of Geographic Names, which is made available under the ODC Attribution License. 

We also acnknowledge the sources and contributors of Getty Thesaurus of Geographic Names (TGN), from which our information also indirectly comes from. If the user is interested about invidual names, geographical facts etc. that are part of the information used here and obtained from the TGN, we encourage them to follow the TGN-sourced ids (links) to TGN for the original sources and contributors. 

## scripts
The Python implementation (`bnf_place_harmonisation.py`) and its R
counterpart (`bnf_place_harmonisation.R`, not yet updated to the current
repo layout — see below).

### Integration notes (Python)

`bnf_place_harmonisation.py` was ported from the original pandas-based
version to a stdlib-only implementation (same algorithm: city/country
split, city string cleaning, TGN lookup with country-table fallback) and
integrated into this repo's conventions:

- CLI-parameterised paths (`--input`, `--place-table`, `--country-table`,
  `--output`, `--report`) instead of the original hardcoded
  `os.chdir()`/relative-path logic, which no longer matched the current
  module-numbered repo layout.
- A JSON report (`--report`) with match-rate statistics.
- The project's standard monitor integration
  (`00_monitor/monitor.py`, same mechanism as module 1's
  `query_agents.R`/`query_editions.R`) — clearly delimited in the source
  with `MONITOR INTEGRATION` comment blocks so it's obvious what was added
  on top of the original harmonisation logic. On by default via CLI,
  `--no-monitor` to disable.
- Unit + end-to-end tests in `00_test/test_place_harmonisation.py`.

The R version (`bnf_place_harmonisation.R`) still has the original
hardcoded `setwd("D:/...")` and has not been updated — it is not run as
part of this pipeline currently.

## data\_final
The final data set (bnf\_publication\_place.csv). Includes the following fields:

* edition: Unique identifier of an BNF record.
* place\_original. The original publication place information in rdam:P30279 before harmonisation.
* tgn\_id: Unique identifier of a place of publication. The identifier comes from the TGN. 
* publication\_place. Name of the publication place (city-level).
* publication\_country. Name of the country (e.g. Great Britain, France) to which the place belongs.
* longitude and latitude. Longitude and latitude of the place.
* uncertainty\_expressions\_brackets. Boolean. If TRUE, original publication place data had brackets, indicating that the publication place had to be be reasoned from somewhere else.
* uncertainty\_expressions\_question\_mark. Boolean. If TRUE, original publication place had a question mark, indicating that there was uncertainty about the publication place.
* uncertainty\_expressions\_parentheses. Boolean. If TRUE, original publication place had parentheses, indicating that there was uncertainty about the publication place.

## data\_work
Data sets used in the process of creating the harmonised data.
