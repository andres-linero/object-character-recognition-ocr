-- Migration 5: download history for each version of a compiled ticket.
CREATE TABLE ops.ticket_downloads (
	id VARCHAR(36) NOT NULL,
	order_id VARCHAR(36) NOT NULL,
	version VARCHAR(64) NOT NULL,
	downloaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
	kind VARCHAR(20) NOT NULL,
	filename TEXT NOT NULL,
	PRIMARY KEY (id),
	CHECK (kind IN ('pdf','scan_zip','rental_zip','reported')),
	FOREIGN KEY(order_id) REFERENCES core.orders (id)
);
