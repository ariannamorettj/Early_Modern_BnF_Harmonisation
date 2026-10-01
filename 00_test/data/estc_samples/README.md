# Synthetic ESTC samples

The three CSV files in this folder are **synthetic**. They have the same
columns, in the same order, as the COMHIS ESTC tables used by module 06
(`estc_core.csv`, `estc_actor_links.csv`, `estc_actors.csv`), but every value
is invented: names, ESTC ids (prefix `Z`, which the ESTC does not use), VIAF
ids (prefix `99999`), titles, places and dates. They describe no real record.

The real tables are licensed data: they stay in `data/estc/` on the machines
that have access to them and are not part of this repository (`data/estc/`
is git-ignored).

Regenerate the samples (deterministic) from the repository root:

```bash
python 00_test/data/estc_samples/make_synthetic_samples.py
```

`00_test/test_estc_samples.py` checks that they keep the column structure of
the real tables and load through `05_map_estc_actors.py` and
`03_map_estc_ecco.py`.
