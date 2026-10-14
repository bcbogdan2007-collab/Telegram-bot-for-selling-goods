"""Telegram-бот интернет-магазина одежды (aiogram 3 + SQLite)."""
import asyncio
import html
import logging
import math
import re
import sqlite3
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           KeyboardButton, Message, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from catalog import CATALOG
from config import ADMIN_ID, BOT_TOKEN, IMAGES_DIR, PAGE_SIZE, PROMOS, SHOP_NAME, SIZES

router = Router()
db = sqlite3.connect("shop.db")


# ============================ БАЗА ДАННЫХ ============================
def init_db():
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
            name TEXT NOT NULL, description TEXT, price INTEGER NOT NULL, photo TEXT);
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
            size TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, product_id, size));
        CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY, kind TEXT NOT NULL, value INTEGER NOT NULL,
            min_total INTEGER NOT NULL DEFAULT 0, uses_left INTEGER,
            active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS user_promo (
            user_id INTEGER PRIMARY KEY, code TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            user_name TEXT, phone TEXT, address TEXT,
            subtotal INTEGER, discount INTEGER, total INTEGER, promo_code TEXT,
            status TEXT DEFAULT 'Новый', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS order_items (
            order_id INTEGER NOT NULL, name TEXT NOT NULL, size TEXT NOT NULL,
            qty INTEGER NOT NULL, price INTEGER NOT NULL);
        """
    )
    # Первичное наполнение каталога
    if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        for cat in CATALOG:
            cur = db.execute("INSERT INTO categories (name) VALUES (?)", (cat["category"],))
            for p in cat["products"]:
                db.execute(
                    "INSERT INTO products (category_id, name, description, price, photo) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cur.lastrowid, p["name"], p["description"], p["price"], p.get("photo")),
                )
    # Стартовые промокоды
    if db.execute("SELECT COUNT(*) FROM promos").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO promos (code, kind, value, min_total, uses_left) VALUES (?, ?, ?, ?, ?)",
            PROMOS,
        )
    db.commit()


# ============================ ПОМОЩНИКИ ============================
def rub(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 10 <= len(digits) <= 15:
        return None
    return "+" + digits


def photo_source(photo: str | None):
    """Фото товара: ссылка, файл из папки images/ или file_id Telegram."""
    if not photo:
        return None
    if photo.startswith("http"):
        return photo
    path = Path(IMAGES_DIR) / photo
    if path.exists():
        return FSInputFile(path)
    if "." in photo:      # похоже на имя файла, но файла нет
        return None
    return photo          # иначе считаем, что это file_id


def get_product(pid: int):
    return db.execute(
        "SELECT id, category_id, name, description, price, photo FROM products WHERE id=?", (pid,)
    ).fetchone()


async def show(call: CallbackQuery, text: str, kb):
    """Показывает экран: редактирует сообщение, а если это фото-карточка — пересоздаёт."""
    if call.message.photo:
        try:
            await call.message.delete()
        except TelegramBadRequest:
            pass
        await call.message.answer(text, reply_markup=kb)
        return
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass  # «message is not modified»


# ----- корзина и расчёты -----
def cart_items(uid: int):
    return db.execute(
        "SELECT c.product_id, c.size, c.qty, p.name, p.price FROM cart c "
        "JOIN products p ON p.id = c.product_id WHERE c.user_id=? ORDER BY c.rowid",
        (uid,),
    ).fetchall()


def cart_count(uid: int) -> int:
    return db.execute("SELECT COALESCE(SUM(qty), 0) FROM cart WHERE user_id=?", (uid,)).fetchone()[0]


def check_promo(uid: int, code: str, subtotal: int):
    """Возвращает (True, (код, скидка)) или (False, текст ошибки)."""
    row = db.execute(
        "SELECT code, kind, value, min_total, uses_left, active FROM promos WHERE code=?",
        (code.strip().upper(),),
    ).fetchone()
    if not row or not row[5]:
        return False, "Промокод не найден или не действует."
    if row[4] is not None and row[4] <= 0:
        return False, "Лимит использований промокода исчерпан."
    if db.execute("SELECT 1 FROM orders WHERE user_id=? AND promo_code=?", (uid, row[0])).fetchone():
        return False, "Вы уже использовали этот промокод."
    if subtotal < row[3]:
        return False, f"Промокод действует для заказов от {rub(row[3])}."
    discount = subtotal * row[2] // 100 if row[1] == "percent" else min(row[2], subtotal)
    return True, (row[0], discount)


def get_totals(uid: int):
    items = cart_items(uid)
    subtotal = sum(q * price for _, _, q, _, price in items)
    discount, code = 0, None
    saved = db.execute("SELECT code FROM user_promo WHERE user_id=?", (uid,)).fetchone()
    if saved:
        ok, res = check_promo(uid, saved[0], subtotal)
        if ok:
            code, discount = res
        else:  # промокод перестал подходить (например, корзину уменьшили)
            db.execute("DELETE FROM user_promo WHERE user_id=?", (uid,))
            db.commit()
    return items, subtotal, discount, subtotal - discount, code


def format_items(items) -> str:
    return "\n".join(
        f"• {html.escape(name)} ({size}) × {qty} = {rub(qty * price)}"
        for _, size, qty, name, price in items
    )


def create_order(user, phone: str, address: str):
    items, subtotal, discount, total, code = get_totals(user.id)
    if not items:
        return None
    cur = db.execute(
        "INSERT INTO orders (user_id, user_name, phone, address, subtotal, discount, total, promo_code) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user.id, user.full_name, phone, address, subtotal, discount, total, code),
    )
    oid = cur.lastrowid
    db.executemany(
        "INSERT INTO order_items (order_id, name, size, qty, price) VALUES (?, ?, ?, ?, ?)",
        [(oid, name, size, qty, price) for _, size, qty, name, price in items],
    )
    if code:
        db.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code=? AND uses_left IS NOT NULL", (code,))
    db.execute("DELETE FROM cart WHERE user_id=?", (user.id,))
    db.execute("DELETE FROM user_promo WHERE user_id=?", (user.id,))
    db.commit()
    return {"id": oid, "items": items, "subtotal": subtotal, "discount": discount, "total": total, "code": code}


# ============================ КЛАВИАТУРЫ ============================
def main_menu(uid: int):
    count = cart_count(uid)
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data="catalog")
    kb.button(text=f"🛒 Корзина ({count})" if count else "🛒 Корзина", callback_data="cart")
    kb.button(text="📦 Мои заказы", callback_data="orders")
    kb.adjust(1, 2)
    return kb.as_markup()


def back_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В главное меню", callback_data="menu")
    return kb.as_markup()


def phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Или напишите номер: +7 999 123-45-67",
    )


def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)


class PromoState(StatesGroup):
    code = State()


class Checkout(StatesGroup):
    phone = State()
    address = State()


# ============================ МЕНЮ ============================
def welcome_text() -> str:
    return (
        f"👋 <b>Добро пожаловать в {SHOP_NAME}!</b>\n\n"
        f"Одежда известных брендов с доставкой.\n"
        f"(для заказа такого бота для любых задач с полным обслуживанием напишите сюда: @dark_baga7)\n\n"
        f"Что вас интересует?"
    )



@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(welcome_text(), reply_markup=main_menu(message.from_user.id))


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, welcome_text(), main_menu(call.from_user.id))
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ============================ КАТАЛОГ ============================
@router.callback_query(F.data == "catalog")
async def cb_catalog(call: CallbackQuery):
    cats = db.execute("SELECT id, name FROM categories ORDER BY id").fetchall()
    kb = InlineKeyboardBuilder()
    for cid, name in cats:
        kb.button(text=name, callback_data=f"cat:{cid}:0")
    kb.adjust(1)
    kb.row(
        InlineKeyboardButton(text="🛒 Корзина", callback_data="cart"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
    )
    await show(call, "🛍 <b>Каталог</b>\n\nВыберите категорию:", kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    _, cid, page = call.data.split(":")
    cid, page = int(cid), int(page)
    name = db.execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (cid,)).fetchone()[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    rows = db.execute(
        "SELECT id, name, price FROM products WHERE category_id=? ORDER BY id LIMIT ? OFFSET ?",
        (cid, PAGE_SIZE, page * PAGE_SIZE),
    ).fetchall()

    kb = InlineKeyboardBuilder()
    for pid, pname, price in rows:
        kb.button(text=f"{pname} · {rub(price)}", callback_data=f"p:{pid}:{cid}:{page}")
    kb.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"cat:{cid}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"cat:{cid}:{page + 1}"))
    kb.row(*nav)
    kb.row(
        InlineKeyboardButton(text="⬅️ Категории", callback_data="catalog"),
        InlineKeyboardButton(text="🛒 Корзина", callback_data="cart"),
    )
    await show(call, f"<b>{html.escape(name)}</b>\nТоваров: {total} · страница {page + 1} из {pages}", kb.as_markup())
    await call.answer()


# ============================ КАРТОЧКА ТОВАРА ============================
def card_text(p) -> str:
    return f"<b>{html.escape(p[2])}</b>\n\n{html.escape(p[3] or '')}\n\n💰 <b>{rub(p[4])}</b>\n\nВыберите размер 👇"


def card_kb(pid, cid, page, size="-"):
    kb = InlineKeyboardBuilder()
    for s in SIZES:
        kb.button(text=f"✅ {s}" if s == size else s, callback_data=f"s:{pid}:{cid}:{page}:{s}")
    kb.adjust(len(SIZES))
    kb.row(InlineKeyboardButton(text="🛒 Добавить в корзину", callback_data=f"a:{pid}:{cid}:{page}:{size}"))
    kb.row(
        InlineKeyboardButton(text="⬅️ К списку", callback_data=f"cat:{cid}:{page}"),
        InlineKeyboardButton(text="🛒 Корзина", callback_data="cart"),
    )
    return kb.as_markup()


@router.callback_query(F.data.startswith("p:"))
async def cb_product(call: CallbackQuery):
    _, pid, cid, page = call.data.split(":")
    p = get_product(int(pid))
    text, kb = card_text(p), card_kb(pid, cid, page)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    src = photo_source(p[5])
    if src:
        try:
            await call.message.answer_photo(src, caption=text, reply_markup=kb)
            await call.answer()
            return
        except Exception as e:  # битая ссылка / неверный file_id — показываем без фото
            logging.warning("Не удалось отправить фото товара %s: %s", pid, e)
    await call.message.answer(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("s:"))
async def cb_size(call: CallbackQuery):
    _, pid, cid, page, size = call.data.split(":")
    try:
        await call.message.edit_reply_markup(reply_markup=card_kb(pid, cid, page, size))
    except TelegramBadRequest:
        pass
    await call.answer(f"Размер {size}")


@router.callback_query(F.data.startswith("a:"))
async def cb_add(call: CallbackQuery):
    _, pid, cid, page, size = call.data.split(":")
    if size not in SIZES:
        await call.answer("Сначала выберите размер 👆", show_alert=True)
        return
    uid = call.from_user.id
    db.execute(
        "INSERT INTO cart (user_id, product_id, size, qty) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, product_id, size) DO UPDATE SET qty = MIN(qty + 1, 10)",
        (uid, int(pid), size),
    )
    db.commit()
    await call.answer(f"✅ Добавлено (размер {size}). В корзине: {cart_count(uid)} шт.")


# ============================ КОРЗИНА ============================
def render_cart(uid: int):
    items, subtotal, discount, total, code = get_totals(uid)
    kb = InlineKeyboardBuilder()
    if not items:
        kb.button(text="🛍 В каталог", callback_data="catalog")
        kb.button(text="🏠 Меню", callback_data="menu")
        kb.adjust(1)
        return "🛒 Ваша корзина пуста.", kb.as_markup()

    lines = ["🛒 <b>Ваша корзина</b>\n"]
    for i, (pid, size, qty, name, price) in enumerate(items, 1):
        lines.append(f"{i}. {html.escape(name)} · <b>{size}</b>\n    {qty} × {rub(price)} = <b>{rub(qty * price)}</b>")
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"q:dec:{pid}:{size}"),
            InlineKeyboardButton(text=f"{i}) {qty} шт.", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"q:inc:{pid}:{size}"),
            InlineKeyboardButton(text="❌", callback_data=f"q:del:{pid}:{size}"),
        )
    lines.append(f"\nСумма: {rub(subtotal)}")
    if code:
        lines.append(f"🎟 Промокод {code}: −{rub(discount)}")
    lines.append(f"<b>Итого: {rub(total)}</b>")

    if code:
        kb.row(InlineKeyboardButton(text="🎟 Убрать промокод", callback_data="nopromo"))
    else:
        kb.row(InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="promo"))
    kb.row(InlineKeyboardButton(text="🧾 Оформить заказ", callback_data="checkout"))
    kb.row(
        InlineKeyboardButton(text="🗑 Очистить", callback_data="clear"),
        InlineKeyboardButton(text="🛍 В каталог", callback_data="catalog"),
    )
    return "\n".join(lines), kb.as_markup()


async def refresh_cart(call: CallbackQuery):
    text, kb = render_cart(call.from_user.id)
    await show(call, text, kb)


@router.callback_query(F.data == "cart")
async def cb_cart(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await refresh_cart(call)
    await call.answer()


@router.callback_query(F.data.startswith("q:"))
async def cb_qty(call: CallbackQuery):
    _, op, pid, size = call.data.split(":")
    uid = call.from_user.id
    if op == "inc":
        db.execute("UPDATE cart SET qty = MIN(qty + 1, 10) WHERE user_id=? AND product_id=? AND size=?", (uid, int(pid), size))
    elif op == "dec":
        db.execute("UPDATE cart SET qty = qty - 1 WHERE user_id=? AND product_id=? AND size=?", (uid, int(pid), size))
        db.execute("DELETE FROM cart WHERE user_id=? AND qty <= 0", (uid,))
    else:
        db.execute("DELETE FROM cart WHERE user_id=? AND product_id=? AND size=?", (uid, int(pid), size))
    db.commit()
    await refresh_cart(call)
    await call.answer()


@router.callback_query(F.data == "clear")
async def cb_clear(call: CallbackQuery):
    db.execute("DELETE FROM cart WHERE user_id=?", (call.from_user.id,))
    db.execute("DELETE FROM user_promo WHERE user_id=?", (call.from_user.id,))
    db.commit()
    await refresh_cart(call)
    await call.answer("Корзина очищена")


# ============================ ПРОМОКОДЫ ============================
@router.callback_query(F.data == "promo")
async def cb_promo(call: CallbackQuery, state: FSMContext):
    await state.set_state(PromoState.code)
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Вернуться в корзину", callback_data="cart")
    await show(call, "🎟 Отправьте промокод сообщением:", kb.as_markup())
    await call.answer()


@router.callback_query(F.data == "nopromo")
async def cb_nopromo(call: CallbackQuery):
    db.execute("DELETE FROM user_promo WHERE user_id=?", (call.from_user.id,))
    db.commit()
    await refresh_cart(call)
    await call.answer("Промокод убран")


@router.message(PromoState.code, F.text)
async def got_promo(message: Message, state: FSMContext):
    uid = message.from_user.id
    subtotal = sum(q * price for _, _, q, _, price in cart_items(uid))
    ok, res = check_promo(uid, message.text, subtotal)
    if not ok:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Вернуться в корзину", callback_data="cart")
        await message.answer(f"❌ {res}\n\nПопробуйте другой код.", reply_markup=kb.as_markup())
        return
    db.execute("INSERT OR REPLACE INTO user_promo (user_id, code) VALUES (?, ?)", (uid, res[0]))
    db.commit()
    await state.clear()
    text, kb = render_cart(uid)
    await message.answer(f"✅ Промокод <b>{res[0]}</b> применён!\n\n" + text, reply_markup=kb)


# ============================ ОФОРМЛЕНИЕ ЗАКАЗА ============================
@router.callback_query(F.data == "checkout")
async def cb_checkout(call: CallbackQuery, state: FSMContext):
    if not cart_items(call.from_user.id):
        await call.answer("Корзина пуста", show_alert=True)
        return
    await state.set_state(Checkout.phone)
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await call.message.answer(
        "🧾 <b>Оформление заказа</b>\n\n<b>Шаг 1/2.</b> Отправьте номер телефона для связи — "
        "нажмите кнопку ниже или напишите номер сообщением.",
        reply_markup=phone_kb(),
    )
    await call.answer()


@router.message(StateFilter(Checkout.phone, Checkout.address), F.text == "❌ Отмена")
async def checkout_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Оформление отменено. Корзина сохранена.", reply_markup=ReplyKeyboardRemove())
 
