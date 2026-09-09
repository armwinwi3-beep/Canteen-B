begin;
create table if not exists public.stores (
  id text primary key,
  name text not null check (char_length(trim(name)) > 0),
  is_open boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.stores enable row level security;
revoke all on public.stores from public, anon, authenticated;
grant select, insert, update, delete on public.stores to service_role;
insert into public.stores (id, name, is_open)
values ('merchant_001', 'ป้าต้อยลูกชิ้นทอดจ้า', true)
on conflict (id) do update set name = excluded.name;
commit;
