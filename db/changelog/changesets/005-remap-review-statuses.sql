--liquibase formatted sql

--changeset boris:005-remap-review-statuses
-- not_interested is renamed. interesting jobs go back to review with the new scores, so they
-- become indistinguishable from other new jobs; that loss is accepted.
UPDATE jobs.vacancies SET status = 'unsuitable' WHERE status = 'not_interested';
UPDATE jobs.vacancies SET status = 'new' WHERE status = 'interesting';
--rollback not required
