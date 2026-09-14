--liquibase formatted sql

--changeset boris:003-add-closed-status
ALTER TABLE jobs.vacancies
    DROP CONSTRAINT vacancies_status_check,
    ADD CONSTRAINT vacancies_status_check
        CHECK (status IN ('new', 'interesting', 'not_interested', 'applied', 'closed'));
-- Rollback fails while any job is still in the 'closed' status; move those jobs to another
-- status first.
--rollback ALTER TABLE jobs.vacancies DROP CONSTRAINT vacancies_status_check, ADD CONSTRAINT vacancies_status_check CHECK (status IN ('new', 'interesting', 'not_interested', 'applied'));
