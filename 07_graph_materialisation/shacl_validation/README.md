# shacl_validation — SHACL validation of the module 07 graphs

Validates the RDF graphs produced by module 07 against the CHAD-AP
application profile:

1. **Shape extraction** (`extractor.py`): generates SHACL shapes from a
   CHAD-AP schema whose classes document their properties in structured
   `dc:description` annotations ("The properties that can be used with this
   class are: …").
2. **Validation** (`validator.py`): applies the shapes to a graph with
   [pySHACL](https://github.com/RDFLib/pySHACL).
3. **Report analysis** (`report_analysis.py`): groups the instance-level
   violations, often thousands, into a small number of independent problem
   families (same constraint, path, shape and message).

## Provenance

Adapted from the `shacl_validator` package of
[dharc-org/morph-kgc-changes-metadata](https://github.com/dharc-org/morph-kgc-changes-metadata),
path `src/morph_kgc_changes_metadata_conversions/shacl_validator`, commit
`b5e10a5c`. That package is itself imported from
[ariannamorettj/morph_kgchad_shacl_validator](https://github.com/ariannamorettj/morph_kgchad_shacl_validator).
The original comments (some in Italian) are kept; BnF changes are marked
`BnF:` in the code.

Changes for the BnF project:

- `config.py`: the default data source is
  `07_graph_materialisation/output/sample/knowledge-graph_merged.nt`
  (N-Triples; rdflib picks the parser from the `.nt` extension). The default
  CHAD-AP schema is the development/14 one the mappings use, not the upstream
  default CHAD-AP 2.1.0 (see Limits). Paths are resolved against the package,
  not the current directory.
- `extractor.py`: a shapes prefix derived from an ontology IRI ending in a
  number (`.../development/14` gave `14_sh`) is not valid Turtle and made the
  serialised shapes unreadable; such prefixes now start with a letter.
- New `bnf_run.py` (`python -m shacl_validation`): generates the shapes,
  validates, and writes timestamped reports to `07_graph_materialisation/report/shacl/`.
  Before validating it checks that the schema contains the namespace the BnF
  data use.
- New `coverage.py`: which classes of the graph the shapes reach.
- The upstream tests are in `00_test/test_shacl_extractor.py`,
  `test_shacl_report_analysis.py` and `test_shacl_validator.py` (imports
  adapted), with `test_shacl_bnf_run.py` for the BnF additions, including the
  validation of a small example graph.
- `cli.py`, `validator.py`, `report_analysis.py` and `aliases.py` are unchanged.

## Running it

From `07_graph_materialisation/`:

```bash
python -m shacl_validation                                    # merged sample graph
python -m shacl_validation --data-source GRAPH.nt --ontology-source CHAD-AP.ttl
python run_full_pipeline.py --profile sample --shacl          # as a pipeline step
```

The upstream command line (`extract`, `validate`, `run` subcommands) is still
available: `python -m shacl_validation.cli --help`.

Exit codes: 0 the graph conforms, 1 it does not (a valid result, not an
error), 2 the validation could not run (missing schema, namespace mismatch,
unparseable input).

## Reports

Each run writes to `07_graph_materialisation/report/shacl/`, with the run's
timestamp in every name:

| File | Content |
|---|---|
| `shacl_<ts>_summary.json` | conformance, triples validated, CHAD-AP version (`owl:versionIRI` / `versionInfo`), counts of results and issue families, the five largest families, class coverage |
| `shacl_<ts>_report.txt` | pySHACL's text report |
| `shacl_<ts>_issues.json`, `_issues.txt` | the independent issue families (`report_analysis.py`) |
| `shacl_<ts>_coverage.txt` | each class of the graph, its instance count and coverage status |
| `shacl_<ts>_shapes.ttl` | the shapes used, for traceability |

Coverage status, per class of the data graph:

- `targeted`: its shape has `sh:targetClass`, so every instance is validated;
- `reachable_via_sh_node`: it has a shape, applied only to instances reached
  as the value of a property of a validated node (`sh:node`); the extractor
  gives `sh:targetClass` only to classes no other class points to;
- `not_covered`: the schema documents no properties for it, so there is no
  shape. None is written by hand.

## Limits

- **CHAD-AP version.** The BnF mappings use the namespace
  `https://w3id.org/dharc/ontology/chad-ap/object/development/14/schema/`
  (`obj:Person`, `obj:Appellation`, `obj:isIdentifiedBy`, ...). No published
  CHAD-AP release contains it: 1.0.0 to 2.1.0 model actors, names and
  time-spans directly with CIDOC-CRM, LRMoo and CRMdig, and the w3id
  namespace does not resolve. Shapes generated from 2.1.0 would therefore
  validate the graph against a model it does not use (for example, 2.1.0
  requires `crm:P2_has_type` and `lrmoo:R7i_is_exemplified_by` on every
  `lrmoo:F3_Manifestation`, where the BnF graph uses `obj:hasType` and has no
  items). The development/14 schema is expected at
  `resources/chad_ap_development_14.ttl`; until it is there, or when a schema
  without the `obj:` namespace is passed, the validation stops with exit
  code 2.
- **Coverage.** The bibliographic graph uses canonical LRMoo and CIDOC-CRM
  classes (`lrmoo:F1_Work`, `F2_Expression`, `F3_Manifestation`,
  `F28_Expression_Creation`, `crm:E7_Activity`, `crm:E35_Title`,
  `crmdig:D9_Data_Object`, ...) without a CHAD-AP wrapper. Whether the schema
  documents them decides whether they are validated; the coverage report of
  each run says which are.
- **Size.** pySHACL works on an in-memory rdflib graph. The validation is
  meant for the sample graph (about 15,000 triples) and has only been run on
  it; the full graph (39 million triples) is out of reach this way.

## Dependency

`pyshacl >=0.30.1,<0.31.0` (as upstream), in `pyproject.toml` and
`poetry.lock`. It adds no constraint on the existing dependencies: rdflib,
morph-kgc 2.10 and pyoxigraph <0.4 keep their versions.
