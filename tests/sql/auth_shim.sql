-- Reproduces the pieces of Supabase's platform (auth schema, roles,
-- auth.uid()) that a plain Postgres instance doesn't have, so
-- supabase/schema.sql's RLS policies can be exercised against a vanilla
-- Postgres service container (e.g. in CI) the same way they'd behave on
-- the real platform. Idempotent -- safe to run every time.
--
-- auth.uid() here is not a stub -- it's the same implementation Supabase
-- actually ships (reads the JWT claims PostgREST sets per-request from a
-- verified Authorization header); tests/test_rls.py simulates a specific
-- request's identity the same way PostgREST does, via
-- `set local request.jwt.claims = '{"sub": "...", "role": "authenticated"}'`.

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key,
  email text
);

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
end $$;

grant authenticated to current_user;
grant anon to current_user;

create or replace function auth.uid() returns uuid
language sql stable
as $$
  select nullif(current_setting('request.jwt.claims', true)::json->>'sub', '')::uuid
$$;
