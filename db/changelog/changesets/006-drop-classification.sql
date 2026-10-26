--liquibase formatted sql

--changeset boris:006-drop-classification
-- Stage two of the review model: drop the single score and the unused classification, and
-- narrow the status check to the review outcomes. Dropping a column drops its checks too.
DROP INDEX jobs.vacancies_english_description_fts_idx;

ALTER TABLE jobs.vacancies
    DROP COLUMN score,
    DROP COLUMN managerial,
    DROP COLUMN stack,
    DROP COLUMN requirements,
    DROP COLUMN english_description,
    DROP CONSTRAINT vacancies_status_check,
    ADD CONSTRAINT vacancies_status_check
        CHECK (status IN ('new', 'unsuitable', 'low_priority', 'applied', 'closed', 'duplicate')),
    ADD CONSTRAINT vacancies_duplicate_of_check
        CHECK ((status = 'duplicate') = (duplicate_of IS NOT NULL));
-- Rollback restores the dropped columns empty: their data is gone.
--rollback ALTER TABLE jobs.vacancies DROP CONSTRAINT vacancies_duplicate_of_check, DROP CONSTRAINT vacancies_status_check, ADD CONSTRAINT vacancies_status_check CHECK (status IN ('new', 'interesting', 'not_interested', 'applied', 'closed', 'unsuitable', 'low_priority', 'duplicate')), ADD COLUMN score smallint CHECK (score BETWEEN 0 AND 100), ADD COLUMN managerial boolean, ADD COLUMN stack text, ADD COLUMN requirements jsonb CHECK (jsonb_typeof(requirements) = 'array' AND NOT jsonb_path_exists(requirements, '$[*] ? (@.type() != "string")')), ADD COLUMN english_description text;
--rollback CREATE INDEX vacancies_english_description_fts_idx ON jobs.vacancies USING gin (to_tsvector('english', english_description));
