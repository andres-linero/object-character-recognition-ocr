-- Migration 4: retain local page details independently of identifier matching.
CREATE TABLE ops.page_extractions (
	page_id VARCHAR(36) NOT NULL,
	extracted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	method VARCHAR(40) NOT NULL,
	fields JSON NOT NULL,
	PRIMARY KEY (page_id),
	FOREIGN KEY(page_id) REFERENCES core.document_pages (id)
);
