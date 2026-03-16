from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Config, load_config
from .db import (
    STATUS_AVAILABLE,
    STATUS_LABELS,
    STATUS_RESERVED,
    STATUS_WITH_READER,
    Book,
    BookRepository,
)
from .photos import build_local_photo_ref, extract_local_filename, is_local_photo_ref

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

STATUS_OPTIONS = [
    (STATUS_AVAILABLE, STATUS_LABELS[STATUS_AVAILABLE]),
    (STATUS_RESERVED, STATUS_LABELS[STATUS_RESERVED]),
    (STATUS_WITH_READER, STATUS_LABELS[STATUS_WITH_READER]),
]

ALLOWED_UPLOAD_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

CONFIG: Config = load_config()
REPO = BookRepository(CONFIG.db_path)
REPO.init()
CONFIG.upload_dir.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
security = HTTPBasic()
app = FastAPI(title="Bookbot Admin")
app.mount("/media", StaticFiles(directory=str(CONFIG.upload_dir)), name="media")


def _normalize_status(raw_status: str) -> str | None:
    return STATUS_ALIASES.get(raw_status.strip().lower())


def _photo_preview_url(photo_ref: str) -> str | None:
    if not is_local_photo_ref(photo_ref):
        return None
    filename = extract_local_filename(photo_ref)
    return f"/media/{quote(filename)}"


def _save_uploaded_photo(photo_upload: UploadFile) -> str:
    original_name = photo_upload.filename or ""
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        suffix = ".jpg"

    filename = f"{uuid4().hex}{suffix}"
    target_path = CONFIG.upload_dir / filename

    with target_path.open("wb") as destination:
        shutil.copyfileobj(photo_upload.file, destination)

    return build_local_photo_ref(filename)


def _require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    username_ok = secrets.compare_digest(credentials.username, CONFIG.web_admin_user)
    password_ok = secrets.compare_digest(credentials.password, CONFIG.web_admin_password)
    if username_ok and password_ok:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


def _render_form(
    request: Request,
    *,
    mode: str,
    action_url: str,
    error: str | None,
    book: Book | None,
    form_data: dict[str, str] | None,
):
    return templates.TemplateResponse(
        request=request,
        name="book_form.html",
        context={
            "mode": mode,
            "action_url": action_url,
            "error": error,
            "book": book,
            "form_data": form_data or {},
            "status_options": STATUS_OPTIONS,
            "status_labels": STATUS_LABELS,
            "photo_preview_url": _photo_preview_url,
        },
    )


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root(_: None = Depends(_require_admin)):
    return RedirectResponse(url="/books", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/books")
def books_list(request: Request, _: None = Depends(_require_admin)):
    books = REPO.list_books()
    return templates.TemplateResponse(
        request=request,
        name="books_list.html",
        context={
            "books": books,
            "status_options": STATUS_OPTIONS,
            "status_labels": STATUS_LABELS,
            "photo_preview_url": _photo_preview_url,
        },
    )


@app.get("/books/new")
def book_create_form(request: Request, _: None = Depends(_require_admin)):
    return _render_form(
        request,
        mode="create",
        action_url="/books/new",
        error=None,
        book=None,
        form_data=None,
    )


@app.post("/books/new")
async def book_create(
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    description: str = Form(...),
    status_raw: str = Form(..., alias="status"),
    photo_file_id: str = Form(""),
    photo_upload: UploadFile | None = File(default=None),
    _: None = Depends(_require_admin),
):
    status_value = _normalize_status(status_raw)
    form_data = {
        "title": title,
        "author": author,
        "description": description,
        "status": status_raw,
        "photo_file_id": photo_file_id,
    }

    if status_value is None:
        return _render_form(
            request,
            mode="create",
            action_url="/books/new",
            error="Некорректный статус книги.",
            book=None,
            form_data=form_data,
        )

    title = title.strip()
    author = author.strip()
    description = description.strip()
    photo_ref = photo_file_id.strip()

    if photo_upload and photo_upload.filename:
        photo_ref = _save_uploaded_photo(photo_upload)

    if not title or not author or not description or not photo_ref:
        return _render_form(
            request,
            mode="create",
            action_url="/books/new",
            error="Заполните все обязательные поля и фото.",
            book=None,
            form_data=form_data,
        )

    REPO.add_book(
        title=title,
        author=author,
        description=description,
        status=status_value,
        photo_file_id=photo_ref,
    )
    return RedirectResponse(url="/books", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/books/{book_id}/edit")
def book_edit_form(book_id: int, request: Request, _: None = Depends(_require_admin)):
    book = REPO.get_book(book_id)
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    return _render_form(
        request,
        mode="edit",
        action_url=f"/books/{book_id}/edit",
        error=None,
        book=book,
        form_data=None,
    )


@app.post("/books/{book_id}/edit")
async def book_edit(
    book_id: int,
    request: Request,
    title: str = Form(...),
    author: str = Form(...),
    description: str = Form(...),
    status_raw: str = Form(..., alias="status"),
    photo_file_id: str = Form(""),
    photo_upload: UploadFile | None = File(default=None),
    _: None = Depends(_require_admin),
):
    existing_book = REPO.get_book(book_id)
    if existing_book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    status_value = _normalize_status(status_raw)
    form_data = {
        "title": title,
        "author": author,
        "description": description,
        "status": status_raw,
        "photo_file_id": photo_file_id,
    }
    if status_value is None:
        return _render_form(
            request,
            mode="edit",
            action_url=f"/books/{book_id}/edit",
            error="Некорректный статус книги.",
            book=existing_book,
            form_data=form_data,
        )

    title = title.strip()
    author = author.strip()
    description = description.strip()
    photo_ref = existing_book.photo_file_id

    manual_photo_ref = photo_file_id.strip()
    if manual_photo_ref:
        photo_ref = manual_photo_ref
    if photo_upload and photo_upload.filename:
        photo_ref = _save_uploaded_photo(photo_upload)

    if not title or not author or not description or not photo_ref:
        return _render_form(
            request,
            mode="edit",
            action_url=f"/books/{book_id}/edit",
            error="Заполните все обязательные поля и фото.",
            book=existing_book,
            form_data=form_data,
        )

    REPO.update_book(
        book_id=book_id,
        title=title,
        author=author,
        description=description,
        status=status_value,
        photo_file_id=photo_ref,
    )
    return RedirectResponse(url="/books", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/books/{book_id}/status")
def book_set_status(
    book_id: int,
    status_raw: str = Form(..., alias="status"),
    _: None = Depends(_require_admin),
):
    status_value = _normalize_status(status_raw)
    if status_value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    updated = REPO.update_status(book_id, status_value)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return RedirectResponse(url="/books", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/books/{book_id}/delete")
def book_delete(book_id: int, _: None = Depends(_require_admin)):
    deleted = REPO.delete_book(book_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return RedirectResponse(url="/books", status_code=status.HTTP_303_SEE_OTHER)
