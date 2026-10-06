-- core-0010: a place to keep a copy of every row the cleanup job removes.
--
-- Additions only. The cleanup job (app/services/cleanup.py) clears out finished drafts, expired
-- one-time codes and abandoned workflow drafts that nothing ever removed. Before a row goes, it is
-- copied here, in the same statement, as JSON (so the copy still reads fine if the table it came
-- from changes later). A row can be put back from its copy. The copies are cleared after the
-- organisation's own number of days (orgs.settings.retention.archive_days, 180 when not set).
--
-- Nothing reads or writes this table until the cleanup job is deployed. Safe to run twice.

CREATE TABLE IF NOT EXISTS public.archived_rows (
    id           bigserial PRIMARY KEY,
    source_table text NOT NULL,
    row_id       text,
    org_id       uuid,
    row_data     jsonb NOT NULL,
    reason       text,
    archived_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_archived_rows_age
    ON public.archived_rows (org_id, archived_at);
CREATE INDEX IF NOT EXISTS idx_archived_rows_source
    ON public.archived_rows (source_table, archived_at);
