# NexusCart Tkinter Frontend

## Files

- `main.py` — full Tkinter store UI, including customer and admin screens.
- `api_client.py` — standard-library HTTP client for the Flask API.
- `theme.py` — shared colours, fonts and ttk styles.
- `assets/images/{electronics,clothing,footwear,accessories}/` — product image folders.
- `pages/`, `screens/`, `widgets/` — reserved for splitting the UI into smaller modules later.

## Run

From the NexusCart project root:

```bash
python frontend/main.py
```

Optional image support for JPG/WEBP and smoother image resizing:

```bash
pip install pillow
```

## Product catalog and inventory import

In the Admin screen, open **Products** and choose **Import / Update CSV + Images**. Select the CSV, then select the folder containing the product images. The CSV must include `name`, `category`, `price`, and `stock`; `description` and `image_path` are optional. `product_id` is optional. If a row has a `product_id` matching an existing product, that product is updated; otherwise a matching product name is updated; otherwise a new product is added. Rows with image filenames are copied into `frontend/assets/images/<category>/`.

Example CSV header:

```csv
product_id,name,category,price,stock,description,image_path
,Wireless Mouse,Electronics,799,25,Ergonomic wireless mouse,wireless_mouse.jpg
```

For an image path, you can provide a filename such as `wireless_mouse.jpg` (the app looks in the selected image folder), or a project-root-relative path such as `frontend/assets/images/electronics/wireless_mouse.jpg`. Keep image filenames and extensions accurate. After a successful import, the catalog is saved to `database/products.csv`; manual Add, Update and Delete actions also save the catalog. Import is an upsert: it adds new products and updates matching products without deleting products absent from the CSV. The catalog and images persist locally across app restarts.

## Backend integration status

The UI uses an in-memory `MockStore` for account, cart, checkout, reviews and admin interactions. Backend AI search and recommendations are opt-in: install the root `requirements.txt`, start the Flask app from `backend/` with `flask --app app:create_app run`, then launch the UI with `NEXUSCART_API_URL=http://127.0.0.1:5000/api python frontend/main.py`. If the AI API is unavailable, the home screen falls back to `MockStore` search and recommendations.

The backend reads products from `database/products.csv` when it contains product rows. Reviews and shopper activity are still held only in the UI's in-memory store, so backend sentiment summaries use demo reviews when the catalog is empty and have no live reviews when a real catalog is loaded. Account, cart, checkout and admin actions are not connected to the backend; the demo store does not persist those records across restarts and is not production authentication/payment handling.
