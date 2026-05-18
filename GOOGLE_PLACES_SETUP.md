# Google Places API Setup For Lead Finder

The Lead Finder uses Google Places Text Search to find public businesses such as interior designers, builders, property managers, remodelers, and real estate agents.

## What You Need

- A Google account.
- A Google Cloud project.
- Billing enabled in Google Cloud.
- Places API enabled.
- One API key saved in `.env` as `GOOGLE_PLACES_API_KEY`.

## Steps

1. Go to Google Cloud Console.
2. Create or select a project for `1L Lead Engine`.
3. Enable billing for the project.
4. Enable **Places API**.
5. Go to **APIs & Services > Credentials**.
6. Create an API key.
7. Restrict the key:
   - API restriction: **Places API**.
   - Application restriction: for local testing, leave unrestricted temporarily or restrict later to your server/IP when deployed.
8. Copy the key.
9. Open `.env` in the project folder.
10. Add:

```text
GOOGLE_PLACES_API_KEY=your_real_key_here
```

11. Restart the dashboard:

```powershell
cd "C:\Users\tyler\OneDrive\Documents\New project"
python dashboard.py 8787
```

12. Open the dashboard and test Lead Finder with:

```text
interior designers
Sarasota FL
```

## Safety Notes

- Do not paste the API key into chat.
- Do not commit `.env` to GitHub.
- Keep API restrictions on the key once testing works.
- Watch Google Cloud usage/billing while testing.
