# NYC 311 Data Factory

Pipeline: source (API / csv / jsonl) -> validation by contract -> quarantine -> clean + enrich -> destinations (csv / database).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
# put the raw population file at data/reference/population_raw.csv
# fill population_source_url and population_source_retrieved in config.json
nyc311-factory run
python -m unittest discover
```

Commands: `run`, `fetch`, `process`. Rolling window: `run --since-last-run`.
Other inputs and outputs, no code change:

```bash
nyc311-factory process --source-type csv --input data/raw/file.csv
nyc311-factory process --destinations csv,database   # needs DATABASE_URL
```

Outputs are in `data/curated/` (`cases.csv`, `quarantine.csv`, `aggregate_wide.csv`,
`quality_report.json`, `manifest_run.json`) and, for the database destination, in the
`cases` and `quarantine` tables of `database_schema`.

Guide for later stages: `docs/USAGE.md`. Example project: `examples/new_dataset/`.

Layout: `contract.py`, `validator.py`, `transformer.py`, `enrichers.py`, `sources.py`,
`sinks.py`, `pipeline.py` are dataset independent. A dataset lives in `datasets/`
(contract + derived columns + reference joins) and is picked by `dataset` in the config.
