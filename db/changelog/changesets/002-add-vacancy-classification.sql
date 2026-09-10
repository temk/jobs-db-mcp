--liquibase formatted sql

--changeset boris:002-add-vacancy-classification
ALTER TABLE jobs.vacancies
    ADD COLUMN managerial          boolean,
    ADD COLUMN stack               text,
    ADD COLUMN requirements        jsonb,
    ADD COLUMN english_description text,
    ADD CHECK (
        jsonb_typeof(requirements) = 'array'
        AND NOT jsonb_path_exists(requirements, '$[*] ? (@.type() != "string")')
    );

CREATE INDEX vacancies_english_description_fts_idx
    ON jobs.vacancies USING gin (to_tsvector('english', english_description));
--rollback DROP INDEX jobs.vacancies_english_description_fts_idx;
--rollback ALTER TABLE jobs.vacancies DROP COLUMN english_description, DROP COLUMN requirements, DROP COLUMN stack, DROP COLUMN managerial;
