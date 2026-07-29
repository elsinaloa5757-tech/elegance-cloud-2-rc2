-- Elegance Cloud 2 RC2 - preparación segura de Supabase/PostgreSQL.
-- Los datos comerciales se mantienen en un esquema no expuesto por la Data API.
create schema if not exists elegance;
revoke all on schema elegance from public, anon, authenticated;
grant usage on schema elegance to service_role;
alter default privileges in schema elegance revoke all on tables from public, anon, authenticated;
alter default privileges in schema elegance grant all on tables to service_role;
alter default privileges in schema elegance revoke all on sequences from public, anon, authenticated;
alter default privileges in schema elegance grant all on sequences to service_role;

create schema if not exists elegance_private;
revoke all on schema elegance_private from public, anon, authenticated;
grant usage on schema elegance_private to service_role;

create table if not exists elegance_private.migration_runs (
  id bigint generated always as identity primary key,
  source_sha256 text not null,
  source_tables integer not null,
  source_rows bigint not null,
  manifest jsonb not null,
  verified boolean not null default false,
  created_at timestamptz not null default now()
);
revoke all on elegance_private.migration_runs from public, anon, authenticated;
grant all on elegance_private.migration_runs to service_role;
