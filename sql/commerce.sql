begin;
alter table public.products add column if not exists image_url text;
alter table public.orders add column if not exists customer_id uuid references public.line_customers(id) on delete set null;
create table if not exists public.expenses (
 id uuid primary key default gen_random_uuid(), merchant_id text not null references public.stores(id) on delete cascade,
 description text not null check(char_length(trim(description))>0), amount numeric(12,2) not null check(amount>0),
 expense_date date not null, created_at timestamptz not null default now()
);
alter table public.expenses enable row level security;
revoke all on public.expenses from public, anon, authenticated;
grant select,insert,update,delete on public.expenses to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('product-images','product-images',true,5242880,array['image/jpeg','image/png','image/webp'])
on conflict(id) do update set public=true,file_size_limit=excluded.file_size_limit,allowed_mime_types=excluded.allowed_mime_types;
commit;
