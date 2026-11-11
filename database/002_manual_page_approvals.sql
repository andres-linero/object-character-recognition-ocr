-- Migration 2: manual assignments preserve original OCR evidence.
CREATE TABLE ops.manual_page_approvals (
	id VARCHAR(36) NOT NULL,
	order_id VARCHAR(36) NOT NULL,
	page_id VARCHAR(36) NOT NULL,
	printed_page INTEGER NOT NULL,
	attempt_id VARCHAR(36) NOT NULL,
	approved_at TIMESTAMP WITH TIME ZONE NOT NULL,
	approved_by VARCHAR(80) NOT NULL,
	note TEXT NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (order_id, printed_page),
	CHECK (printed_page > 0),
	FOREIGN KEY(order_id) REFERENCES core.orders (id),
	UNIQUE (page_id),
	FOREIGN KEY(page_id) REFERENCES core.document_pages (id),
	FOREIGN KEY(attempt_id) REFERENCES ops.ocr_attempts (id)
);
