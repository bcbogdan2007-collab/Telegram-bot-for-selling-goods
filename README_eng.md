# 🛍️ Telegram Bot for Selling Goods (Clothing Store Example)

A demo project with a focused set of features: a **Telegram bot for selling goods**, built on the example of an **online clothing store**. It includes a catalog, cart, promo codes, checkout, and orders — all driven by **Inline keyboards** and stored in a local **SQLite** database.

The user browses the catalog, picks a size, adds items to the cart, applies a promo code, enters a phone number and address, and confirms the order. The administrator receives an instant notification.

## Features

- **Catalog with categories and pagination:** interactive browsing of products by category with page navigation;
- **Product cards with photos:** images from a URL, a local `images/` folder, or a Telegram `file_id`;
- **Size selection:** the chosen size is highlighted with ✅ before adding to the cart;
- **Cart management:** increase/decrease quantity, remove items, clear the whole cart;
- **Promo codes:** percentage or fixed discounts with a minimum order amount and usage limits, one promo per user;
- **Checkout wizard:** step-by-step collection of phone number (via contact button or text) and delivery address;
- **Order confirmation screen:** review of items, subtotal, discount, and total before submitting;
- **“My orders” section:** the last 10 orders of the user with date, total, and status;
- **Admin notifications:** instant Telegram alert to `ADMIN_ID` about every new order;
- **Admin commands:** `/products` (list product IDs), `/setphoto` (attach a photo to a product), `/addpromo` (create a promo code);
- **Robust input handling:** phone number normalization, address length validation, clear error messages.

## Privacy

- only data required for orders is stored: **Telegram user ID, name, phone, address, cart contents, and order history**;
- no message text is logged (logs contain only service information);
- all data is kept in a **local SQLite database** (`shop.db`) and never sent to third parties.

## Tech Stack

- Python 3.11+
- [aiogram 3.x](https://docs.aiogram.dev/)
- SQLite3 (built-in relational DB)
- python-dotenv (optional), logging

## Project Structure

```text
project/
├── main.py            # bot code, handlers, FSM, database logic
├── catalog.py         # product catalog loaded into the DB on first launch
├── config.py          # bot token, admin ID, sizes, promos, shop settings
├── requirements.txt   # dependencies
├── .env.example       # example environment variables
├── images/            # product photos (optional)
└── README.md
```

Installation and Usage

1. Get a Telegram bot token: message @BotFather and use the /newbot command.
2. Find out your Telegram ID (for admin notifications and commands): message @userinfobot.
3. Install the dependencies (using a virtual environment is recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Create a .env file from the example and enter your data:
   ```bash
   cp .env.example .env            # Windows: copy .env.example .env
   ```
   ```env
   BOT_TOKEN=your_telegram_bot_token
   ADMIN_ID=your_telegram_id
   ```
5. (Optional) add product photos to the images/ folder using the file names from catalog.py.
6. Start the bot:
   ```bash
   python main.py
   ```
7. Open the bot in Telegram, send /start, and go to the catalog.

Configuration

Setting Where Description
Bot token BOT_TOKEN in config.py (from .env) Token from @BotFather
Admin ID ADMIN_ID in config.py (from .env) Telegram ID for notifications and admin commands
Shop name SHOP_NAME in config.py Displayed in the welcome message
Sizes SIZES list in config.py Available sizes (["S", "M", "L", "XL"])
Pagination PAGE_SIZE in config.py Products per page in a category
Images folder IMAGES_DIR in config.py Folder with product photos
Starting promos PROMOS in config.py Created on first launch (code, type, value, min total, usage limit)
Product catalog CATALOG in catalog.py Categories, products, descriptions, prices, photos

Database

On first launch the bot automatically creates shop.db with the tables:

· categories, products — catalog loaded from catalog.py;
· cart — items by (user_id, product_id, size);
· promos, user_promo — active promo codes and the code applied by each user;
· orders, order_items — placed orders and their line items.

The catalog and starting promo codes are inserted only once — when the corresponding tables are empty.

Admin Commands

Command Purpose
/products List product IDs (and 📷 if a photo is set)
/setphoto НОМЕР Send as a photo caption to attach an image to that product
/addpromo КОД percent\|fixed ЗНАЧЕНИЕ [МИН_СУММА] Create or replace a promo code

Troubleshooting

· “BOT_TOKEN is empty” / bot does not start — make sure the .env file is next to main.py and contains BOT_TOKEN.
· Admin does not receive notifications — check that ADMIN_ID is a numeric Telegram ID (not a @username).
· Product photo is not shown — verify the file exists in images/, or the URL is valid, or the file_id is correct for this bot.
· Promo code is rejected — the code may be inactive, used up, already used by this user, or the order total may be below the minimum.
· “message is not modified” — harmless Telegram error, already handled by the code.
· Database error — make sure the script has write permission for the project folder to create/update shop.db.

Security

Do not publish the .env file or the shop.db database. Add .env, *.db, and venv/ to .gitignore.

---

💼 To order a custom bot for any task with full support, contact me on Telegram: @dark_baga7
