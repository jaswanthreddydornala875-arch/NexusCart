# NexusCart Tkinter Frontend

## Files

- `main.py` — full Tkinter store UI, including customer and admin screens.
- `api_client.py` — standard-library HTTP client for the Django API.
- `theme.py` — shared colours, fonts and ttk styles.
- `assets/images/` — product image folders grouped by category.

## Run with the persistent backend

From the project root, install the requirements and initialize the Django database:

```bash
python3 -m pip install -r requirements.txt
python3 backend/manage.py migrate
python3 backend/manage.py createsuperuser
```

In one terminal, start the API:

```bash
python3 backend/manage.py runserver
```

In another terminal, start the desktop app in backend mode:

```bash
NEXUSCART_API_URL=http://127.0.0.1:8000/api python3 frontend/main.py
```

The Django API persists accounts, profiles, products, cart contents, orders, reviews, and shopper
activity. Use the superuser created above to sign in to the admin screens. A normal customer account
can be created from the sign-up screen. Without `NEXUSCART_API_URL`, the app uses its in-memory demo
store instead.

In the customer screen, choose **Ask AI** to search products, get recommendations, ask about orders or
reviews, and add products to the cart after confirming. In the admin screen, the **Reports** tab shows
explainable order-risk flags and a demand/restocking forecast based on stored orders and stock. Risk
flags are for human review only; forecasts are estimates and need sufficient sales history.

To load the project catalog into the Django database, run migrations first and then use the importer:

```bash
python3 scripts/import_products.py database/products.csv --django --dry-run
python3 scripts/import_products.py database/products.csv --django
```

The import is an upsert by SKU; it does not remove products missing from the file. For image support
in the desktop app, optionally install Pillow:

```bash
python3 -m pip install pillow
```

## Other backend components

Flask remains available for the separate AI demonstration endpoints and the legacy importer mode.
The persistent desktop app uses Django as its canonical API and database.
