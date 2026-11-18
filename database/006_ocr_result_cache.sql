-- Migration 6: provider results keyed by the SHA-256 of the header crop sent to OCR.
-- Identical crops in re-synced, renamed or appended PDFs reuse the stored result.
CREATE TABLE ops.ocr_result_cache (
	crop_sha256 VARCHAR(64) NOT NULL,
	parser_version INTEGER NOT NULL,
	kind VARCHAR(20),
	identifier VARCHAR(80),
	identifiers JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (crop_sha256)
);
