--liquibase formatted sql

--changeset boris:001-create-vacancies
CREATE SCHEMA IF NOT EXISTS jobs;

CREATE TABLE jobs.vacancies (
    id            bigint      GENERATED ALWAYS AS IDENTITY,
    site          text        NOT NULL,
    pos_id        text        NOT NULL,
    url           text        NOT NULL,
    title         text        NOT NULL,
    company       text,
    location      text,
    description   text,
    downloaded_at timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    score         smallint,
    status        text        NOT NULL DEFAULT 'new',

    PRIMARY KEY (id),
    UNIQUE (site, pos_id),
    CHECK (score BETWEEN 0 AND 100),
    CHECK (status IN ('new', 'interesting', 'not_interested', 'applied'))
);
--rollback DROP TABLE jobs.vacancies;
