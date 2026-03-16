
## 1. `duplicates_report.json`

produced by `editions_analysis.py`
The output file `duplicates_report.json` is a structured JSON file containing three top-level keys: `general`, `occurrences`, and `detail`.

The `general` key provides an overview of how many URIs are found in the dataset for each type (`edition`, `expression`, `work`), including total and unique counts. The `occurrences` key contains URIs that appear more than once in the dataset (i.e. duplicates), grouped by type. The `detail` key includes relationships and co-occurrence mappings across entities.

Fields with multiple URIs separated by semicolons are split and processed individually. All URIs are stripped of whitespace and deduplicated.

Each field in `detail` includes mappings such as:
- `editions_with_multiple_works`: maps each edition URI to a list of associated work URIs, if more than one is present.
- `editions_with_multiple_expressions`: maps each edition URI to multiple expressions, if applicable.
- `works_with_multiple_editions`: maps each work URI to all editions it's associated with.
- `works_with_multiple_expressions`: maps each work URI to multiple expressions.
- `expressions_with_multiple_editions`: maps each expression URI to multiple editions.
- `expressions_with_multiple_works`: maps each expression URI to multiple works.

Each mapping has the format:  
`"<uri>": ["<related_uri_1>", "<related_uri_2>", ...]`

The file also includes co-occurrence information based on URIs found together in the same row (e.g. in a field separated by `;`):
- `paired_works`: for each work URI, lists other works that appeared with it in any row.
- `paired_editions`: same for editions.
- `paired_expressions`: same for expressions.

All lists are deduplicated and sorted. The output is saved to `final_dataset_analysis/reports/duplicates_report.json`.


## **Final Dataset Analysis – Reports Overview**

These reports were generated from the unified dataset chunks in
`data/unified_dataset/unified_chunks/`, filtered to records of type:

```
http://purl.org/dc/dcmitype/Text
```

### **1. work\_link\_summary.json**&#x20;

**Purpose:**
Summarises how many *work IDs* are connected to at least one edition and/or expression.

**Key results:**

* **Total works analysed:** 3 958 # Should me 100 of thousands 
* **Works with at least one edition:** 3 958
* **Works with at least one expression:** 3 958
* **Works with both edition & expression:** 3 958
* **Works with neither:** 0
* **Unique editions linked from works:** 22 238
* **Unique expressions linked from works:** 22 238

**Interpretation:**
Every work ID in this subset is linked to both at least one edition and at least one expression; there are no works without connections.

---

### 2. `edition_expression_checks.json`
### 3. `work_link_summary.json`

**Purpose:**
Checks cardinality and pairing between editions and expressions.

**Key results:**

* **Total editions:** 465 542
* **Total expressions:** 465 542
* **Editions with multiple expressions:** 0
* **Editions without any expression:** 0
* **Expressions without any edition:** 0

**Interpretation:**
There is a strict 1:1 pairing between editions and expressions in this dataset.
No editions are linked to multiple expressions, and all editions have an expression (and vice versa).

---

### **File locations**

All JSON reports are stored in:

```
final_dataset_analysis/reports/
```

* `work_link_summary.json` — work → edition/expression connectivity counts.
* `edition_expression_checks.json` — edition ↔ expression pairing checks.



## RESULTS COMPARISONS

From the previous analysis (full dataset, no record-type filter):

Editions total (unique): 875 018

Expressions total (unique): 786 991

Works total (unique): 31 195

Editions with multiple expressions: 0

Expressions without edition: 0

Editions without expression: 0

From the new analysis (filtered to dc/dcmitype/Text):

Editions total: 465 542

Expressions total: 465 542

Works total: 3 958

Editions with multiple expressions: 0

Expressions without edition: 0

Editions without expression: 0

Conclusion:
The structural results are consistent — in both cases there are no editions with multiple expressions, and every edition has exactly one expression (and vice versa).
The differences in totals are due to the filtering in the new run (only Text resources).

- Controlliamo se queste cose che hanno altro tipo siano uscite dall'analisi (vediamo della alternative)
- check se ci sono uncategorised items 
- facciamo un ranking dei tipi 
- why so few works: maybe they could not match. when they make work id for estc avevano un bioinformatico che lavorava per questo. Ci sta che sia così sotto numero. Potrebbero averlo eseguito solo parzialmente 

> final_dataset_analysis/reports/bnf_ark_titles.json

- prodotto con `final_dataset_analysis/fetch_bnf_ark_titles.py`

- analisi per vedere in quali casi compare uno di questi tipi senza un tipo primario (tipo testo o oggetto fisico)
fatta con script : `edition_record_type_analysis.py`
prodotto : `final_dataset_analysis/reports/edition_to_allowed_record_types.json`
> 186 opere che possono essere considerate testi valutando i risultati 

non sono molte ma è interessante 

- work id è prominente per quelli che vogliono highlightare come tali nella french - fare un'analisi di cosa c'è dietro (???)





Arianna Moretti
in the meantime I did an analysis of the entities whose only type was not among the known ones
it's not many of them (186) but I made a script to use beautiful soup and retrieve the type name and they all seem to be classifiable as texts

-> correggere .. con xx
esprimere come magnitudine 
correggere gli anni negativi 
--> ne prendiamo un centinaio e vediamo se sono problematici (python final_dataset_analysis/find_entities_without_record_type.py --> qui gestita la faccenda)
--> Cosa degli omonimi 
--> avere tabelle con link esterni solo quelle per gli attori. Da usare con soft matching. 
--> iniziare a scrivere 

###### https://data.bnf.fr/ark:/12148/cb129249167 
###### https://catalogue.bnf.fr/ark:/12148/cb129249167 