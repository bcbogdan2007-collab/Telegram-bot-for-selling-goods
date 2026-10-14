import os

# Токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Ваш Telegram ID (узнать у @userinfobot). Нужен, чтобы:
#  - получать уведомления о новых заказах
#  - пользоваться админ-командами (/products, /setphoto, /addpromo)
ADMIN_ID = int(os.getenv("ADMIN_ID", ""))

SHOP_NAME = "Urban Wear"
SIZES = ["S", "M", "L", "XL"]
PAGE_SIZE = 3          # сколько товаров показывать на одной странице категории
IMAGES_DIR = "images"  # папка с фотографиями товаров

# Стартовые промокоды (создаются при первом запуске):
# (код, тип "percent"/"fixed", значение, мин. сумма заказа, лимит использований или None)
PROMOS = [
    ("WELCOME10", "percent", 10, 0, None),     # -10% на любой заказ
    ("SALE20", "percent", 20, 5000, 100),      # -20% от 5 000 ₽, первые 100 использований
    ("MINUS500", "fixed", 500, 3000, None),    # -500 ₽ от 3 000 ₽
]
