"""Relational storage shared by PostgreSQL and the local SQLite demonstration."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
                        Integer, JSON, MetaData, String, Table, Text, UniqueConstraint,
                        create_engine, event, func, select)
from sqlalchemy.schema import CreateSchema, CreateTable
from sqlalchemy.pool import StaticPool

metadata = MetaData()


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


def identity():
    return Column("id", String(36), primary_key=True, default=uid)


versions = Table("schema_versions", metadata, Column("version", Integer, primary_key=True),
                 Column("applied_at", DateTime(timezone=True), nullable=False), schema="ops")
runs = Table("ingestion_runs", metadata, identity(),
    Column("kind", String(30), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(20), nullable=False),
    Column("rows_seen", Integer, nullable=False, default=0),
    Column("rows_loaded", Integer, nullable=False, default=0),
    Column("rows_rejected", Integer, nullable=False, default=0),
    Column("error_code", String(80)),
    CheckConstraint("status IN ('running','success','partial','failed')"),
    CheckConstraint("rows_seen >= 0 AND rows_loaded >= 0 AND rows_rejected >= 0"), schema="ops")
sources = Table("source_files", metadata, identity(),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("name", Text, nullable=False), Column("kind", String(20), nullable=False),
    Column("synthetic", Boolean, nullable=False, default=False), schema="staging")
raw_rows = Table("tracker_rows", metadata, identity(),
    Column("run_id", ForeignKey("ops.ingestion_runs.id"), nullable=False),
    Column("source_id", ForeignKey("staging.source_files.id"), nullable=False),
    Column("sheet", String(100), nullable=False), Column("row_number", Integer, nullable=False),
    Column("payload", JSON, nullable=False), schema="staging")
rejected = Table("rejected_rows", metadata, identity(),
    Column("raw_row_id", ForeignKey("staging.tracker_rows.id"), nullable=False),
    Column("reason", Text, nullable=False), schema="staging")
customers = Table("customers", metadata, identity(),
    Column("source_system", String(80), nullable=False),
    Column("external_key", String(100), nullable=False), Column("name", Text, nullable=False),
    UniqueConstraint("source_system", "external_key"), schema="core")
orders = Table("orders", metadata, identity(),
    Column("source_system", String(80), nullable=False),
    Column("order_number", String(80), nullable=False),
    Column("shipment_number", String(80), nullable=False),
    Column("customer_id", ForeignKey("core.customers.id"), nullable=False),
    Column("ship_to", Text, nullable=False), Column("status", String(20), nullable=False),
    Column("order_date", Date), Column("deadline", Date),
    Column("requested_by", Text, nullable=False), Column("order_type", String(40), nullable=False),
    Column("expected_pages", Integer), Column("source_sheet", String(100), nullable=False),
    Column("source_id", ForeignKey("staging.source_files.id"), nullable=False),
    UniqueConstraint("source_system", "order_number"),
    CheckConstraint("status IN ('OPEN','COMPLETE')"),
    CheckConstraint("expected_pages IS NULL OR expected_pages > 0"), schema="core")
documents = Table("documents", metadata, identity(),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("path", Text, nullable=False), Column("page_count", Integer, nullable=False),
    Column("synthetic", Boolean, nullable=False),
    CheckConstraint("page_count > 0"), schema="core")
pages = Table("document_pages", metadata, identity(),
    Column("document_id", ForeignKey("core.documents.id"), nullable=False),
    Column("page_number", Integer, nullable=False),
    UniqueConstraint("document_id", "page_number"),
    CheckConstraint("page_number > 0"), schema="core")
associations = Table("order_document_pages", metadata, identity(),
    Column("order_id", ForeignKey("core.orders.id"), nullable=False),
    Column("page_id", ForeignKey("core.document_pages.id"), nullable=False),
    Column("method", String(30), nullable=False),
    UniqueConstraint("order_id", "page_id", "method"),
    CheckConstraint("method IN ('synthetic_manifest','azure_ocr')"), schema="core")
attempts = Table("ocr_attempts", metadata, identity(),
    Column("page_id", ForeignKey("core.document_pages.id"), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("provider", String(40), nullable=False),
    Column("status", String(20), nullable=False), Column("identifier", String(80)),
    Column("error_code", String(80)),
    CheckConstraint("status IN ('running','success','no_match','error')"), schema="ops")
reviews = Table("review_events", metadata, identity(),
    Column("order_id", ForeignKey("core.orders.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", String(20), nullable=False),
    CheckConstraint("status IN ('pending','reviewed')"), schema="ops")
page_approvals = Table("manual_page_approvals", metadata, identity(),
    Column("order_id", ForeignKey("core.orders.id"), nullable=False),
    Column("page_id", ForeignKey("core.document_pages.id"), nullable=False, unique=True),
    Column("printed_page", Integer, nullable=False),
    Column("attempt_id", ForeignKey("ops.ocr_attempts.id"), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("approved_by", String(80), nullable=False),
    Column("note", Text, nullable=False),
    UniqueConstraint("order_id", "printed_page"),
    CheckConstraint("printed_page > 0"), schema="ops")
rental_orders = Table("rental_orders", metadata, identity(),
    Column("source_system", String(80), nullable=False),
    Column("rental_number", String(80), nullable=False),
    Column("customer_id", ForeignKey("core.customers.id"), nullable=False),
    Column("address", Text, nullable=False),
    UniqueConstraint("source_system", "customer_id", "rental_number"), schema="core")
rental_tickets = Table("rental_order_tickets", metadata,
    Column("order_id", ForeignKey("core.orders.id"), primary_key=True),
    Column("rental_id", ForeignKey("core.rental_orders.id"), nullable=False), schema="core")
rental_pages = Table("rental_order_pages", metadata,
    Column("page_id", ForeignKey("core.document_pages.id"), primary_key=True),
    Column("rental_id", ForeignKey("core.rental_orders.id"), nullable=False),
    Column("attempt_id", ForeignKey("ops.ocr_attempts.id"), nullable=False),
    Column("fields", JSON, nullable=False), schema="core")
page_extractions = Table("page_extractions", metadata,
    Column("page_id", ForeignKey("core.document_pages.id"), primary_key=True),
    Column("extracted_at", DateTime(timezone=True), nullable=False),
    Column("method", String(40), nullable=False),
    Column("fields", JSON, nullable=False), schema="ops")
downloads = Table("ticket_downloads", metadata, identity(),
    Column("order_id", ForeignKey("core.orders.id"), nullable=False),
    Column("version", String(64), nullable=False),
    Column("downloaded_at", DateTime(timezone=True), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("filename", Text, nullable=False),
    CheckConstraint("kind IN ('pdf','scan_zip','rental_zip','reported')"), schema="ops")


class Store:
    """Explicit migrations and transaction boundaries, with no implicit database fallback."""
    def __init__(self, url: str):
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url.endswith(":memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def configure(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")
            self.engine = self.engine.execution_options(
                schema_translate_map={"staging": None, "core": None, "ops": None})
        elif self.engine.dialect.name != "postgresql":
            raise ValueError("Only PostgreSQL and SQLite are supported")

    def migrate(self):
        """Apply versioned migrations without replacing existing document evidence."""
        with self.engine.connect() as connection:
            sqlite = self.engine.dialect.name == 'sqlite'
            if sqlite:
                connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
                connection.commit()
            try:
                with connection.begin():
                    if sqlite:
                        connection.exec_driver_sql('BEGIN IMMEDIATE')
                    else:
                        for schema in ("staging", "core", "ops"):
                            connection.execute(CreateSchema(schema, if_not_exists=True))
                    versions.create(connection, checkfirst=True)
                    current = connection.scalar(select(func.max(versions.c.version))) or 0
                    if current > 5:
                        raise ValueError("Database schema is newer than this application")
                    if current == 0:
                        metadata.create_all(connection)
                        connection.execute(versions.insert().values(version=1, applied_at=utcnow()))
                    if current < 2:
                        page_approvals.create(connection, checkfirst=True)
                        connection.execute(versions.insert().values(version=2, applied_at=utcnow()))
                    if current < 3:
                        for table in (rental_orders, rental_tickets, rental_pages):
                            table.create(connection, checkfirst=True)
                        if current and sqlite:
                            # Rebuild only orders to remove the obsolete one-shipment/one-ticket rule.
                            unique_shipments = False
                            for index in connection.exec_driver_sql('PRAGMA index_list(orders)').mappings():
                                if index['unique']:
                                    columns = [r[2] for r in connection.exec_driver_sql(f'PRAGMA index_info("{index["name"]}")')]
                                    unique_shipments |= columns == ['source_system', 'shipment_number']
                            if unique_shipments:
                                ddl = str(CreateTable(orders).compile(dialect=connection.dialect,
                                    schema_translate_map={'core': None, 'ops': None, 'staging': None}, render_schema_translate=True))
                                ddl = ddl.replace('CREATE TABLE main.orders', 'CREATE TABLE orders_next', 1)
                                connection.exec_driver_sql(ddl)
                                columns = ', '.join(f'"{column.name}"' for column in orders.columns)
                                connection.exec_driver_sql(f'INSERT INTO orders_next ({columns}) SELECT {columns} FROM orders')
                                connection.exec_driver_sql('DROP TABLE orders')
                                connection.exec_driver_sql('ALTER TABLE orders_next RENAME TO orders')
                        elif current:
                            from sqlalchemy import inspect
                            for constraint in inspect(connection).get_unique_constraints('orders', schema='core'):
                                if constraint['column_names'] == ['source_system', 'shipment_number']:
                                    quoted = connection.dialect.identifier_preparer.quote(constraint['name'])
                                    connection.exec_driver_sql(f'ALTER TABLE core.orders DROP CONSTRAINT {quoted}')
                        connection.execute(versions.insert().values(version=3, applied_at=utcnow()))
                    if current < 4:
                        page_extractions.create(connection, checkfirst=True)
                        connection.execute(versions.insert().values(version=4, applied_at=utcnow()))
                    if current < 5:
                        downloads.create(connection, checkfirst=True)
                        connection.execute(versions.insert().values(version=5, applied_at=utcnow()))
                    if sqlite and connection.exec_driver_sql('PRAGMA foreign_key_check').all():
                        raise ValueError('Migration would break existing document references')
            finally:
                if sqlite:
                    connection.exec_driver_sql('PRAGMA foreign_keys=ON')
                    connection.commit()

    def rows(self, statement):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def counts(self):
        with self.engine.connect() as connection:
            return {table.name: connection.scalar(select(func.count()).select_from(table))
                    for table in (customers, orders, documents, pages, associations, attempts, runs, rejected)}

    def order_rows(self):
        statement = select(orders.c.id.label("database_id"),
            orders.c.order_number.label("Order_ID"), orders.c.shipment_number.label("SO"),
            customers.c.name.label("Customer_name"), orders.c.ship_to.label("Ship_to"),
            orders.c.status.label("Status"), orders.c.order_date.label("Today"),
            orders.c.deadline.label("Deadline"), orders.c.requested_by.label("Requested by"),
            orders.c.order_type.label("Order_Type"), orders.c.source_sheet.label("Source_Sheet"),
            orders.c.expected_pages.label("Expected_Pages"))
        return self.rows(statement.select_from(orders.join(customers)).order_by(orders.c.shipment_number))

    def reconciliation_rows(self):
        statement = select(orders.c.id.label("database_id"),
            func.count(func.distinct(associations.c.page_id)).filter(
                associations.c.method == "synthetic_manifest").label("Manifest_Pages"),
            func.count(func.distinct(associations.c.page_id)).filter(
                associations.c.method == "azure_ocr").label("OCR_Verified_Pages"))
        return self.rows(statement.select_from(orders.outerjoin(associations))
                         .group_by(orders.c.id).order_by(orders.c.id))

    def close(self):
        self.engine.dispose()


def sqlite_url(path: Path):
    return "sqlite:///" + str(path.resolve())
