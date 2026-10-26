--liquibase formatted sql

--changeset boris:004-add-review-model
-- Stage one of the review model: the new columns and organizations next to the old columns.
-- The status check accepts the old and the new values so that 005 can remap the data; 006
-- drops the old columns and narrows the check.
CREATE TABLE jobs.organizations (
    id   bigint GENERATED ALWAYS AS IDENTITY,
    name text   NOT NULL,

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX organizations_name_key ON jobs.organizations (lower(name));

ALTER TABLE jobs.vacancies
    ADD COLUMN fit_score        smallint CHECK (fit_score BETWEEN 0 AND 100),
    ADD COLUMN interest_score   smallint CHECK (interest_score BETWEEN 0 AND 100),
    ADD COLUMN management_level text     CHECK (management_level IN ('individual_contributor', 'tech_lead', 'team_lead', 'group_lead')),
    ADD COLUMN work_mode        text     CHECK (work_mode IN ('onsite', 'hybrid', 'remote')),
    ADD COLUMN employer_id      bigint   REFERENCES jobs.organizations (id),
    ADD COLUMN agency_id        bigint   REFERENCES jobs.organizations (id),
    ADD COLUMN duplicate_of     bigint   REFERENCES jobs.vacancies (id),
    ADD COLUMN search_text      text,
    ADD COLUMN digest           text     CHECK (length(digest) <= 1500),
    DROP CONSTRAINT vacancies_status_check,
    ADD CONSTRAINT vacancies_status_check CHECK (
        status IN ('new', 'interesting', 'not_interested', 'applied', 'closed', 'unsuitable', 'low_priority', 'duplicate')
    );

CREATE INDEX vacancies_search_text_fts_idx
    ON jobs.vacancies USING gin (to_tsvector('english', search_text));
-- Rollback fails while any job is in a status introduced here; move those jobs to an old status first.
--rollback DROP INDEX jobs.vacancies_search_text_fts_idx;
--rollback ALTER TABLE jobs.vacancies DROP COLUMN digest, DROP COLUMN search_text, DROP COLUMN duplicate_of, DROP COLUMN agency_id, DROP COLUMN employer_id, DROP COLUMN work_mode, DROP COLUMN management_level, DROP COLUMN interest_score, DROP COLUMN fit_score, DROP CONSTRAINT vacancies_status_check, ADD CONSTRAINT vacancies_status_check CHECK (status IN ('new', 'interesting', 'not_interested', 'applied', 'closed'));
--rollback DROP TABLE jobs.organizations;
