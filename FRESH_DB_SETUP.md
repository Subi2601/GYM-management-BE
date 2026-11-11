# Fresh database setup (after pulling new code)

Use this when you pull the latest code and want to test from a **clean database** with fresh demo data.
It takes about 5 minutes.

> All backend commands run in **PowerShell** inside the `Backend\GYM-management-BE` folder.

---

## 1. Stop the backend

In the window where the backend is running, press **Ctrl + C**.
(The database can't be deleted while the backend is connected to it.)

## 2. Get the latest code

```
git pull
```

Do the same in the frontend folder (`Frontend\GYM-management-FE`) if you also pull the frontend.

## 3. Check the secret keys in `.env` (fixes the "Fernet key" error)

Do this **before** the database steps. The demo data is encrypted with this key, so it must be set first.

1. Generate the keys:

   ```
   .\env\Scripts\python -m scripts.gen_dev_secrets
   ```

2. It prints two lines. Open the **`.env`** file (same folder as `.env.example`) and replace the
   `JWT_SECRET=` and `PII_KEY=` lines with them:

   ```
   JWT_SECRET=...long value...
   PII_KEY=...44 characters ending with =
   ```

   - No quotes, no spaces before or after.
   - The file must be named exactly `.env` (not `.env.txt`).

3. Check the key works:

   ```
   .\env\Scripts\python -c "from app.config import settings; from cryptography.fernet import Fernet; Fernet(settings.PII_KEY.encode()); print('PII_KEY OK')"
   ```

   You should see **`PII_KEY OK`**.

> If your `.env` already has a working `PII_KEY` (the check above prints OK), keep it. Don't change it.

## 4. Delete and recreate the database

**Option A: pgAdmin**

1. Right-click the **`stag_gym_saas`** database, then **Delete / Drop**.
   If it says the database is in use, close every backend window and try again.
2. Right-click **Databases**, then **Create → Database**, and name it **`stag_gym_saas`**.

**Option B: command line** (enter your Postgres password when asked)

```
psql -U postgres -c "DROP DATABASE IF EXISTS stag_gym_saas WITH (FORCE);"
psql -U postgres -c "CREATE DATABASE stag_gym_saas;"
```

## 5. Update packages (only matters when new ones were added)

```
.\env\Scripts\pip install -r requirements.txt
```

## 6. Create the tables and the demo data

```
.\env\Scripts\alembic upgrade head
.\env\Scripts\python -m app.utils.seed
```

- `alembic upgrade head` creates all the tables.
- `seed` adds the demo gym (Stag Fitness), its branches, roles and access, demo logins, plans and food items.

## 7. Start the backend

```
.\env\Scripts\uvicorn app.main:app --port 8001 --reload
```

Keep this window open.

## 8. Start the frontend (new PowerShell window)

In the `Frontend\GYM-management-FE` folder:

```
npm install
npm run dev
```

Open **http://localhost:5173** (or the link shown in the terminal).

## 9. Log in

| Role  | Email             | Password     |
|-------|-------------------|--------------|
| Owner | `owner@gym.com`   | `owner123`   |
| Staff | `trainer@gym.com` | `trainer123` |

If the browser says **"Session expired"**, just log in again (the old session belonged to the old database).

---

## Quick check (optional)

With the backend running, in another window in the backend folder:

```
.\env\Scripts\python -m scripts.smoke_test http://127.0.0.1:8001
```

`FAILURES: 0` at the end means the setup is good.

---

## Problems

| You see | Do this |
|---|---|
| `Fernet key must be 32 url-safe base64-encoded bytes` | `PII_KEY` in `.env` is empty or wrong. Do step 3, then **restart the backend** (Ctrl + C, then step 7). |
| Can't delete the database ("in use") | Stop every backend window first (step 1). Option B's `WITH (FORCE)` also works. |
| Backend can't connect to the database | Check Postgres is running, the `stag_gym_saas` database exists, and the password in `DATABASE_URL` inside `.env` is right. |
| Every page shows an error / no data | The backend must be running on port **8001** (step 7). |
| `alembic` or `seed` fails halfway | Repeat from step 4 (fresh database), then step 6. |
