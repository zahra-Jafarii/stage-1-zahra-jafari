# NYC 311 Data Factory

Pipeline: API -> raw monthly files -> validation/quarantine -> curated outputs.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
# put the population table at data/reference/population.csv
nyc311-factory run
python -m unittest discover
```

Commands: `run`, `fetch`, `process`. Rolling window: `run --since-last-run`.
Outputs are in `data/curated/` (`cases.csv`, `quarantine.csv`, `aggregate_wide.csv`,
`quality_report.json`, `manifest_run.json`).