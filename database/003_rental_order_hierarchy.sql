-- Migration 3: customer rental orders own multiple tickets and identified source pages.
-- Shipment numbers may be shared by more than one ticket/work order.
ALTER TABLE core.orders DROP CONSTRAINT IF EXISTS orders_source_system_shipment_number_key;

CREATE TABLE core.rental_orders (
	id VARCHAR(36) NOT NULL,
	source_system VARCHAR(80) NOT NULL,
	rental_number VARCHAR(80) NOT NULL,
	customer_id VARCHAR(36) NOT NULL,
	address TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (source_system, customer_id, rental_number),
	FOREIGN KEY(customer_id) REFERENCES core.customers (id)
);

CREATE TABLE core.rental_order_tickets (
	order_id VARCHAR(36) NOT NULL,
	rental_id VARCHAR(36) NOT NULL,
	PRIMARY KEY (order_id),
	FOREIGN KEY(order_id) REFERENCES core.orders (id),
	FOREIGN KEY(rental_id) REFERENCES core.rental_orders (id)
);

CREATE TABLE core.rental_order_pages (
	page_id VARCHAR(36) NOT NULL,
	rental_id VARCHAR(36) NOT NULL,
	attempt_id VARCHAR(36) NOT NULL,
	fields JSON NOT NULL,
	PRIMARY KEY (page_id),
	FOREIGN KEY(page_id) REFERENCES core.document_pages (id),
	FOREIGN KEY(rental_id) REFERENCES core.rental_orders (id),
	FOREIGN KEY(attempt_id) REFERENCES ops.ocr_attempts (id)
);
