# Customer LINE login

This first slice implements customer identity only. The Vue app is the customer LIFF app; the merchant website remains a separate future app. Supabase project Canteen (dlrijxeacdpzefwylbad) was resumed and the line_customers schema was applied on 2026-09-09. No frontend/backend deployment has been performed.

## LINE Developers

1. Open your existing **LINE Login** channel (not a Messaging API channel).
2. In its LIFF tab, add a LIFF app. Select Full size and scopes **openid** and **profile**.
3. Set the Endpoint URL to the HTTPS URL serving the customer Vue app.
4. Copy its LIFF ID into frontend `VITE_LIFF_ID`. Copy the channel's Channel ID into backend `LINE_LOGIN_CHANNEL_ID`. These must refer to the same channel. No Channel Secret is required for this verification endpoint.
5. While the channel is in development, test using a LINE account registered with an appropriate channel role. Publish the channel when ready for other customers.
6. Open `https://liff.line.me/YOUR_LIFF_ID` from LINE. Do not use the raw website URL as the customer entry link.

## Database and backend

- Already applied to Canteen: `sql/line_customers.sql`. Do not rerun CREATE TABLE on this project. For a new environment, review and apply the SQL. This is a schema proposal, not an applied migration. It creates a new table and deliberately fails if the table already exists, so an existing schema is not silently replaced.
- Add missing values from `.env.example` to your existing `.env`; do not overwrite existing settings.
- `SUPABASE_SECRET_KEY` must be a backend secret key or legacy service_role key. It must never be placed in a `VITE_` variable. The existing `SUPABASE_KEY` setting is not reused automatically because its privilege level is unknown.
- Install `pip install -r requirements.txt` (or `requirements.lock.txt` for the captured environment).
- Start the customer API using `python -m uvicorn customer_app:app --host 0.0.0.0 --port 8000`.
- For hosted use set `CUSTOMER_ORIGINS` to the exact frontend origin; comma-separated values are supported. Use HTTPS for both services.
- Run `python -m unittest test_customer_auth -v`.

## Frontend

Inside `canteen-frontend/vue-project`, copy `.env.example` to `.env.local`, fill the LIFF ID and API URL, then run `npm ci` and `npm run dev`. For a hosted build run `npm run build`. The LIFF Endpoint URL must serve this build over HTTPS.

## Contract and access model

`GET /auth/me` requires `Authorization: Bearer <liff.getIDToken()>`. The backend verifies the raw token with LINE and the configured channel before upserting the account. It returns `{ "customer": { "id", "display_name", "picture_url", "role": "customer" } }`.

This is LINE authentication with an application customer table, **not a Supabase Auth session**. The browser never talks directly to the database. The table has RLS enabled, no public policies, public access revoked, and an explicit grant to service_role. Future customer routes must use `Depends(current_customer)` and constrain queries to that returned customer ID. Never accept a customer ID or merchant role from the browser as authorization. Future Realtime access requires a separate access design.

Tokens are not stored by our app code; each request retrieves a token from the LIFF SDK. Expired/rejected tokens return 401 and the UI asks the customer to reopen LIFF. No token or raw database exception is returned or logged by these modules. Identity is scoped to the configured channel; changing channels later requires an explicit account migration.

`main.py` remains the legacy prototype. The customer entry point deliberately does not mount its unprotected order endpoints. Do not deploy the legacy API as the customer API. Order pricing, atomic stock updates, merchant auth, and order ownership are subsequent work.

## Live acceptance checks (require configured LINE and database)

1. Apply the SQL and confirm anonymous/authenticated roles cannot read the table.
2. Open LIFF with an allowed LINE account; confirm display name and a single row in `line_customers`.
3. Reopen with the same account; confirm the customer UUID is unchanged and no duplicate row appears.
4. Use a second LINE account; confirm it gets a different UUID.
5. Try an invalid or expired token; expect 401 and no database write.

References: https://developers.line.biz/en/docs/line-login/verify-id-token/ and https://developers.line.biz/en/reference/liff/ and https://supabase.com/docs/guides/api/securing-your-api

## Verified database setup (2026-09-09)
- Backend service key: Data API SELECT returned HTTP 200.
- RLS enabled; anon and authenticated SELECT privileges both false.
- service_role access verified; repeated upsert passed inside a rolled-back transaction.
- Verified that the disposable test UUID is absent after rollback.
- Live LINE login remains untested until HTTPS deployment and LIFF endpoint configuration.
