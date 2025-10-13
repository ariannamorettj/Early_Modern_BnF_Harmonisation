# bnf\_agents\_data\_gap\_filling

Supplements missing agent data by querying for agents that did not receive metadata in dataset\_maker\_agents\_raw\_data.py.
Required inputs: raw edition metadata (merged\_editions\_dataset\_with\_log.csv) from the BNF and a full list of agents (shortlist\_aut, shortlist\_pbl etc. atm).

## query\_missing\_agents.R

Script to query for the missing agent data

## actor\_queries\_results\_for\_actors\_missing\_from\_bnf\_editions

The output agent metadata.
