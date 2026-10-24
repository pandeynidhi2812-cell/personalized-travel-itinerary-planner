create table if not exists public.trips (
  id text primary key,
  title text not null,
  destination text not null,
  start_date date,
  end_date date,
  budget numeric,
  currency text default 'INR',
  travelers integer default 1,
  preferences jsonb default '{}'::jsonb,
  itinerary jsonb default '[]'::jsonb,
  estimated_total numeric default 0,
  created_at timestamptz default now()
);
alter table public.trips enable row level security;
-- For a private student demo, backend service-role access is used. Never expose the service role key in a browser.
