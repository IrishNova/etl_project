-- Migration 001 — normalize product_subtype on rows already in the warehouse.
--
-- The L2 transforms were fixed to normalize subtype at source (A: upper+strip the
-- SKU's case drift "ia-core"->"IA-CORE"; B: strip trailing space "Standard "->
-- "Standard"). This backfill applies the same rule to rows loaded before the fix,
-- so the warehouse matches the regenerated clean data. Idempotent — safe to re-run.
--
-- Run: psql "$DATABASE_URL" -f scripts/migrations/001_normalize_subtype.sql
--      (or via the host/port/creds in .env)

BEGIN;

UPDATE fact_contracts
   SET product_subtype = upper(btrim(product_subtype))
 WHERE product = 'A'
   AND product_subtype IS DISTINCT FROM upper(btrim(product_subtype));

UPDATE fact_contracts
   SET product_subtype = btrim(product_subtype)
 WHERE product = 'B'
   AND product_subtype IS DISTINCT FROM btrim(product_subtype);

COMMIT;
