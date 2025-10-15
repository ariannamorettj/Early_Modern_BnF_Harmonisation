# bnf\_place_harmonisation

Script and output data of the process to harmonise the country-level and city-level publication place information in the BNF.

Contains information from the J. Paul Getty Trust, Getty Research Institute, the Getty Thesaurus of Geographic Names, which is made available under the ODC Attribution License. 

We also acnknowledge the sources and contributors of Getty Thesaurus of Geographic Names (TGN), from which our information also indirectly comes from. If the user is interested about invidual names, geographical facts etc. that are part of the information used here and obtained from the TGN, we encourage them to follow the TGN-sourced ids (links) to TGN for the original sources and contributors. 

## scripts
The commented script to implement the harmonisation (bnf\_place\_harmonisation.R)

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
