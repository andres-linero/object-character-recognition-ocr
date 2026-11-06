# Documentation guide

Start with the [project README](../README.md) to install and launch the app.

| Document | Purpose |
| --- | --- |
| [Live OCR validation](ocr-validation-results.md) | Results and limits for the two 60-page synthetic batches |
| [Database and ETL](data-pipeline.md) | SQL storage, migrations, ingestion, and synthetic preview |
| [Architecture](architecture.md) | Current components, data flow, deployment boundary, and limitations |
| [Synthetic demo dataset](demo-data.md) | Generate 100 fictional packets and a matching tracker |
| [Configuration and data](configuration.md) | Environment variables, workbook schema, and generated files |
| [Operations](operations.md) | Startup, diagnosis, recovery, and retention |
| [ADR 0001](decisions/0001-modular-monolith.md) | Proposed architecture direction and implementation stages |
| [ADR 0002](decisions/0002-relational-store-and-etl.md) | Proposed database, ETL, and resume evidence |
| [Walkthrough plan](walkthroughs.md) | Video coverage, transcripts, and publication requirements |
| [Release audit](../PRP.md) | Initial public-copy changes and validation limits |

[Google Doc architecture workspace](https://docs.google.com/document/d/19lhy8-3sdm3E9ZSVoxvQ6Cty-0Tm62eW5EJPxWn24YQ/edit?usp=drivesdk) — design discussion and proposed decisions; access follows Drive permissions.

The repository is the source of truth for implemented behavior. The linked Google Doc is a working design discussion; there is no automatic synchronization. Move approved decisions into an ADR and implementation details into these docs in the same change that updates the code.

For each behavior change, update the relevant guide, configuration example, and walkthrough timestamps. Record architectural trade-offs in a new ADR; preserve superseded decisions rather than silently rewriting them.
