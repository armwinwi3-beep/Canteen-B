-- Schema proposal: apply to the intended Supabase project before using /auth/me.
-- Separate from legacy users and Supabase Auth; only Python accesses this table.
begin;
create table public.line_customers (
    id uuid primary key,
    line_channel_id text not null,
    line_user_id text not null,
    display_name text not null,
    picture_url text,
    created_at timestamptz not null default now(),
    unique (line_channel_id, line_user_id)
);
alter table public.line_customers enable row level security;
revoke all on public.line_customers from public, anon, authenticated;
grant select, insert, update on public.line_customers to service_role;
commit;
