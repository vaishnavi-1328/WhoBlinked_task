# whoBlinked Task — dbt + Databricks Project

## Project Overview

A dbt (data build tool) project that transforms raw source data in Databricks into analytics-ready models. The project follows a bronze/silver/gold layered architecture pattern.

## Tech Stack

- **dbt-core** 1.12.0 with **dbt-databricks** adapter
- **Databricks** as the data warehouse (Databricks SQL warehouse)
- **Python 3** for orchestration (`main.py`)
- **uv** for Python dependency management (`pyproject.toml`, `uv.lock`)

## Project Structure

```
dbt_proj/
├── dbt_proj/                   # dbt project root
│   ├── dbt_project.yml         # dbt project config (materialization settings)
│   ├── dbt_proj.yml            # alternate/updated project config
│   ├── profiles.yml            # Databricks connection config
│   ├── models/
│   │   ├── bronze/             # Raw source layer (views over source tables)
│   │   │   ├── bronze_customers.sql
│   │   │   ├── bronze_drivers.sql
│   │   │   ├── bronze_locations.sql
│   │   │   ├── bronze_trips.sql
│   │   │   ├── bronze_vehicles.sql
│   │   │   └── properties.yml
│   │   ├── source/
│   │   │   └── sources.yml     # Source table declarations
│   │   └── example/            # Default dbt example models
│   ├── analyses/, macros/, seeds/, snapshots/, tests/
├── main.py                     # Python entry point
├── requirements.txt            # Full pinned dependencies
└── pyproject.toml              # uv project config
```

## Data Sources

Source database: `dbt_project.source` (Databricks catalog)

Tables:
- `customers`
- `drivers`
- `locations`
- `payments`
- `trips`
- `vehicles`

## Databricks Connection

- **Host**: `dbc-e71e2a69-0506.cloud.databricks.com`
- **HTTP Path**: `/sql/1.0/warehouses/8e9138984aa61317`
- **Target schema**: `dbt_default`
- **Catalog**: `dbt_project`
- **Profile**: `dbt_proj` (defined in `dbt_proj/profiles.yml`)

## Common Commands

```bash
# Install dependencies
uv sync

# Run all models
dbt run --project-dir dbt_proj/dbt_proj --profiles-dir dbt_proj/dbt_proj

# Run specific model
dbt run --select bronze_customers --project-dir dbt_proj/dbt_proj --profiles-dir dbt_proj/dbt_proj

# Test models
dbt test --project-dir dbt_proj/dbt_proj --profiles-dir dbt_proj/dbt_proj

# Compile (check SQL without running)
dbt compile --project-dir dbt_proj/dbt_proj --profiles-dir dbt_proj/dbt_proj

# Generate docs
dbt docs generate --project-dir dbt_proj/dbt_proj --profiles-dir dbt_proj/dbt_proj
```

## Model Materialization

- Bronze models: `view` (thin wrappers over source tables)
- Example models: configured as `table` in `dbt_proj.yml`

## Notes

- The `profiles.yml` contains a Databricks PAT token — never commit new tokens to version control
- `dbt_proj.yml` and `dbt_project.yml` coexist; `dbt_proj.yml` appears to be the active config (materialization changed from `view` to `table` in the second commit)
- The working directory is currently empty — all project files are tracked in git history relative to `Desktop/`
