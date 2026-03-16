from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Config, load_config
from .db import (
    Book,
    BookRepository,
    STATUS_AVAILABLE,
    STATUS_LABELS,
    STATUS_RESERVED,
    STATUS_WITH_READER,
)
from .texts import ADMIN_HELP_TEXT, RULES_TEXT, START_TEXT
from .photos import is_local_photo_ref, resolve_local_photo_path

LOGGER = logging.getLogger(__name__)

STATUS_ALIASES = {
    "available": STATUS_AVAILABLE,
    "доступна": STATUS_AVAILABLE,
    "reserved": STATUS_RESERVED,
    "забронирована": STATUS_RESERVED,
    "занята": STATUS_RESERVED,
    "with_reader": STATUS_WITH_READER,
    "у читателя": STATUS_WITH_READER,
    "у_читателя": STATUS_WITH_READER,
}


class AddBookFlow(StatesGroup):
    title = State()
    author = State()
    description = State()
    status = State()
    photo = State()


def _is_admin(user_id: int | None, config: Config) -> bool:
    return bool(user_id and user_id == config.admin_id)


def _main_menu_keyboard(*, is_admin: bool) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Каталог"), KeyboardButton(text="Правила чтения")]
    ]
    if is_admin:
        rows.append(
            [
                KeyboardButton(text="Админ: добавить книгу"),
                KeyboardButton(text="Админ: список книг"),
            ]
        )
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def _status_picker_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Доступна")],
            [KeyboardButton(text="Забронирована")],
            [KeyboardButton(text="У читателя")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _normalize_status(raw_status: str) -> str | None:
    return STATUS_ALIASES.get(raw_status.strip().lower())


def _book_caption(book: Book) -> str:
    status_label = STATUS_LABELS.get(book.status, book.status)
    return (
        f"<b>{escape(book.title)}</b>\n"
        f"Автор: {escape(book.author)}\n"
        f"Статус: <b>{escape(status_label)}</b>\n\n"
        f"{escape(book.description)}"
    )


def _photo_for_telegram(photo_ref: str, config: Config) -> str | FSInputFile | None:
    if not is_local_photo_ref(photo_ref):
        return photo_ref

    local_path = resolve_local_photo_path(photo_ref, config.upload_dir)
    if not local_path.exists():
        LOGGER.warning("Local photo file not found: %s", local_path)
        return None
    return FSInputFile(local_path)


def _book_card_keyboard(
    *,
    book_ids: list[int],
    current_index: int,
    current_book_id: int,
    is_admin: bool,
):
    builder = InlineKeyboardBuilder()

    nav_row: list[InlineKeyboardButton] = []
    if current_index > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"book_open:{book_ids[current_index - 1]}",
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            text=f"{current_index + 1}/{len(book_ids)}",
            callback_data="book_noop",
        )
    )
    if current_index < len(book_ids) - 1:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"book_open:{book_ids[current_index + 1]}",
            )
        )
    builder.row(*nav_row)

    builder.row(
        InlineKeyboardButton(
            text="Хочу прочитать",
            callback_data=f"book_interest:{current_book_id}",
        )
    )

    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text="✅ Доступна",
                callback_data=f"book_setstatus:{current_book_id}:{STATUS_AVAILABLE}",
            ),
            InlineKeyboardButton(
                text="⏳ Забронирована",
                callback_data=f"book_setstatus:{current_book_id}:{STATUS_RESERVED}",
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="📚 У читателя",
                callback_data=f"book_setstatus:{current_book_id}:{STATUS_WITH_READER}",
            )
        )

    return builder.as_markup()


def _first_book_id(repo: BookRepository) -> int | None:
    book_ids = repo.list_book_ids()
    if not book_ids:
        return None
    return book_ids[0]


def _get_book_position(repo: BookRepository, book_id: int) -> tuple[Book, list[int], int] | None:
    book = repo.get_book(book_id)
    if book is None:
        return None

    book_ids = repo.list_book_ids()
    try:
        current_index = book_ids.index(book_id)
    except ValueError:
        return None

    return book, book_ids, current_index


async def _send_book_card(
    message: Message,
    repo: BookRepository,
    book_id: int,
    is_admin: bool,
    config: Config,
) -> None:
    payload = _get_book_position(repo, book_id)
    if payload is None:
        await message.answer("Книга не найдена.")
        return

    book, book_ids, current_index = payload
    photo = _photo_for_telegram(book.photo_file_id, config)
    if photo is None:
        await message.answer("Не удалось открыть фото книги. Обновите обложку в админке.")
        return

    await message.answer_photo(
        photo=photo,
        caption=_book_caption(book),
        reply_markup=_book_card_keyboard(
            book_ids=book_ids,
            current_index=current_index,
            current_book_id=book.id,
            is_admin=is_admin,
        ),
    )


async def _edit_book_card(
    callback: CallbackQuery,
    repo: BookRepository,
    book_id: int,
    is_admin: bool,
    config: Config,
) -> None:
    if callback.message is None or not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    payload = _get_book_position(repo, book_id)
    if payload is None:
        await callback.answer("Книга не найдена", show_alert=True)
        return

    book, book_ids, current_index = payload
    photo = _photo_for_telegram(book.photo_file_id, config)
    if photo is None:
        await callback.answer("Фото книги не найдено. Обновите обложку в админке.", show_alert=True)
        return

    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=photo, caption=_book_caption(book)),
            reply_markup=_book_card_keyboard(
                book_ids=book_ids,
                current_index=current_index,
                current_book_id=book.id,
                is_admin=is_admin,
            ),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def _build_router(config: Config, repo: BookRepository) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        is_admin = _is_admin(message.from_user.id if message.from_user else None, config)
        await message.answer(START_TEXT, reply_markup=_main_menu_keyboard(is_admin=is_admin))
        if is_admin:
            await message.answer(ADMIN_HELP_TEXT)

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        is_admin = _is_admin(message.from_user.id if message.from_user else None, config)
        text = START_TEXT
        if is_admin:
            text = f"{START_TEXT}\n\n{ADMIN_HELP_TEXT}"
        await message.answer(text, reply_markup=_main_menu_keyboard(is_admin=is_admin))

    @router.message(Command("rules"))
    @router.message(F.text == "Правила чтения")
    async def rules_handler(message: Message) -> None:
        await message.answer(RULES_TEXT)

    @router.message(Command("catalog"))
    @router.message(F.text == "Каталог")
    async def catalog_handler(message: Message) -> None:
        first_book_id = _first_book_id(repo)
        if first_book_id is None:
            await message.answer("Каталог пока пуст.")
            return
        is_admin = _is_admin(message.from_user.id if message.from_user else None, config)
        await _send_book_card(
            message,
            repo,
            first_book_id,
            is_admin=is_admin,
            config=config,
        )

    @router.message(F.text == "Админ: добавить книгу")
    @router.message(Command("addbook"))
    async def addbook_start_handler(message: Message, state: FSMContext) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, config):
            await message.answer("Эта команда доступна только администратору.")
            return
        await state.set_state(AddBookFlow.title)
        await message.answer(
            "Добавление книги: введите название.",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(Command("cancel"))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state is None:
            await message.answer("Нет активного действия для отмены.")
            return

        await state.clear()
        is_admin = _is_admin(message.from_user.id if message.from_user else None, config)
        await message.answer(
            "Действие отменено.",
            reply_markup=_main_menu_keyboard(is_admin=is_admin),
        )

    @router.message(AddBookFlow.title)
    async def addbook_title_handler(message: Message, state: FSMContext) -> None:
        title = (message.text or "").strip()
        if not title:
            await message.answer("Название не может быть пустым. Введите название книги.")
            return
        await state.update_data(title=title)
        await state.set_state(AddBookFlow.author)
        await message.answer("Введите автора.")

    @router.message(AddBookFlow.author)
    async def addbook_author_handler(message: Message, state: FSMContext) -> None:
        author = (message.text or "").strip()
        if not author:
            await message.answer("Автор не может быть пустым. Введите автора.")
            return
        await state.update_data(author=author)
        await state.set_state(AddBookFlow.description)
        await message.answer("Введите краткое описание.")

    @router.message(AddBookFlow.description)
    async def addbook_description_handler(message: Message, state: FSMContext) -> None:
        description = (message.text or "").strip()
        if not description:
            await message.answer("Описание не может быть пустым. Введите краткое описание.")
            return
        await state.update_data(description=description)
        await state.set_state(AddBookFlow.status)
        await message.answer(
            "Выберите статус книги.",
            reply_markup=_status_picker_keyboard(),
        )

    @router.message(AddBookFlow.status)
    async def addbook_status_handler(message: Message, state: FSMContext) -> None:
        status = _normalize_status(message.text or "")
        if status is None:
            await message.answer(
                "Не распознал статус. Выберите один из вариантов.",
                reply_markup=_status_picker_keyboard(),
            )
            return
        await state.update_data(status=status)
        await state.set_state(AddBookFlow.photo)
        await message.answer(
            "Пришлите фото книги (обложки).",
            reply_markup=ReplyKeyboardRemove(),
        )

    @router.message(AddBookFlow.photo)
    async def addbook_photo_handler(message: Message, state: FSMContext) -> None:
        if not message.photo:
            await message.answer("Нужна фотография. Пришлите фото книги.")
            return

        data = await state.get_data()
        photo_file_id = message.photo[-1].file_id

        book_id = repo.add_book(
            title=data["title"],
            author=data["author"],
            description=data["description"],
            status=data["status"],
            photo_file_id=photo_file_id,
        )

        await state.clear()
        await message.answer(
            f"Книга добавлена. ID: {book_id}",
            reply_markup=_main_menu_keyboard(is_admin=True),
        )

    @router.message(F.text == "Админ: список книг")
    @router.message(Command("books"))
    async def books_list_handler(message: Message) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, config):
            await message.answer("Эта команда доступна только администратору.")
            return

        rows = list(repo.iter_books_with_status())
        if not rows:
            await message.answer("В каталоге пока нет книг.")
            return

        lines = ["Книги в каталоге:"]
        for book_id, title, status in rows:
            lines.append(
                f"{book_id}. {escape(title)} — {STATUS_LABELS.get(status, status)}"
            )
        await message.answer("\n".join(lines))

    @router.message(Command("setstatus"))
    async def setstatus_handler(message: Message) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, config):
            await message.answer("Эта команда доступна только администратору.")
            return

        if not message.text:
            await message.answer("Использование: /setstatus &lt;id&gt; &lt;status&gt;")
            return

        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("Использование: /setstatus &lt;id&gt; &lt;status&gt;")
            return

        book_id_raw, status_raw = parts[1], parts[2]
        if not book_id_raw.isdigit():
            await message.answer("ID книги должен быть числом.")
            return

        status = _normalize_status(status_raw)
        if status is None:
            await message.answer(
                "Неизвестный статус. Используйте: available, reserved, with_reader "
                "или русские варианты."
            )
            return

        updated = repo.update_status(int(book_id_raw), status)
        if not updated:
            await message.answer("Книга с таким ID не найдена.")
            return
        await message.answer(
            f"Статус книги {book_id_raw} обновлен: {STATUS_LABELS[status]}"
        )

    @router.callback_query(F.data == "book_noop")
    async def noop_callback(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data.startswith("book_open:"))
    async def open_book_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректная команда", show_alert=True)
            return
        _, raw_book_id = callback.data.split(":", maxsplit=1)
        if not raw_book_id.isdigit():
            await callback.answer("Некорректный ID книги", show_alert=True)
            return

        is_admin = _is_admin(callback.from_user.id if callback.from_user else None, config)
        await _edit_book_card(
            callback,
            repo,
            int(raw_book_id),
            is_admin=is_admin,
            config=config,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("book_interest:"))
    async def interest_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            await callback.answer("Некорректная команда", show_alert=True)
            return
        _, raw_book_id = callback.data.split(":", maxsplit=1)
        if not raw_book_id.isdigit():
            await callback.answer("Некорректный ID книги", show_alert=True)
            return

        book = repo.get_book(int(raw_book_id))
        if book is None:
            await callback.answer("Книга не найдена", show_alert=True)
            return

        user = callback.from_user
        username = f"@{user.username}" if user and user.username else "без username"
        full_name = escape(user.full_name) if user else "Unknown user"
        user_line = full_name
        if user:
            user_line = f"<a href=\"tg://user?id={user.id}\">{full_name}</a>"

        admin_message = (
            "Новый интерес к книге\n"
            f"Книга: <b>{escape(book.title)}</b>\n"
            f"Пользователь: {user_line}\n"
            f"Ник: {escape(username)}"
        )
        try:
            await callback.bot.send_message(config.admin_id, admin_message)
        except TelegramForbiddenError:
            LOGGER.warning("Cannot notify admin: forbidden to send messages")
        except Exception:  # pragma: no cover
            LOGGER.exception("Failed to send admin notification")

        await callback.answer("Спасибо! Я получил ваш интерес и свяжусь с вами вручную.")

    @router.callback_query(F.data.startswith("book_setstatus:"))
    async def setstatus_callback(callback: CallbackQuery) -> None:
        if not _is_admin(callback.from_user.id if callback.from_user else None, config):
            await callback.answer("Только администратор может менять статус.", show_alert=True)
            return

        if not callback.data:
            await callback.answer("Некорректная команда", show_alert=True)
            return

        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Некорректная команда", show_alert=True)
            return

        _, raw_book_id, status = parts
        if not raw_book_id.isdigit():
            await callback.answer("Некорректный ID книги", show_alert=True)
            return
        if status not in STATUS_LABELS:
            await callback.answer("Некорректный статус", show_alert=True)
            return

        updated = repo.update_status(int(raw_book_id), status)
        if not updated:
            await callback.answer("Книга не найдена", show_alert=True)
            return

        await _edit_book_card(
            callback,
            repo,
            int(raw_book_id),
            is_admin=True,
            config=config,
        )
        await callback.answer(f"Статус обновлен: {STATUS_LABELS[status]}")

    return router


async def run_bot() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    config = load_config()
    repo = BookRepository(config.db_path)
    repo.init()
    config.upload_dir.mkdir(parents=True, exist_ok=True)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(_build_router(config, repo))

    LOGGER.info("Bot started")
    await dispatcher.start_polling(bot)
