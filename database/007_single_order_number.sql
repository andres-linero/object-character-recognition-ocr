-- Migration 7: every work order (W-…, created from a rental order) or shipment
-- ("Shipment 00001", created from a sales order) is keyed by its own number.
-- The separate shipment_number column on orders is removed.
ALTER TABLE core.orders DROP COLUMN shipment_number;
