from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


STATUS_AVAILABLE = "available"
STATUS_RESERVED = "reserved"
STATUS_WITH_READER = "with_reader"

STATUS_LABELS = {
    STATUS_AVAILABLE: "Доступна",
    STATUS_RESERVED: "Забронирована",
    STATUS_WITH_READER: "У читателя",
}

VALID_STATUSES = set(STATUS_LABELS)


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    author: str
    description: str
    status: str
    photo_file_id: str
    created_at: str


class BookRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    photo_file_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()

    def add_book(
        self,
        *,
        title: str,
        author: str,
        description: str,
        status: str,
        photo_file_id: str,
    ) -> int:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO books (title, author, description, status, photo_file_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title.strip(), author.strip(), description.strip(), status, photo_file_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_books(self) -> list[Book]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, author, description, status, photo_file_id, created_at
                FROM books
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_book(row) for row in rows]

    def list_book_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM books ORDER BY id ASC").fetchall()
        return [int(row["id"]) for row in rows]

    def get_book(self, book_id: int) -> Book | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, author, description, status, photo_file_id, created_at
                FROM books
                WHERE id = ?
                """,
                (book_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_book(row)

    def update_status(self, book_id: int, status: str) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE books SET status = ? WHERE id = ?",
                (status, book_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def update_book(
        self,
        *,
        book_id: int,
        title: str,
        author: str,
        description: str,
        status: str,
        photo_file_id: str | None = None,
    ) -> bool:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        fields = [
            "title = ?",
            "author = ?",
            "description = ?",
            "status = ?",
        ]
        params: list[str | int] = [
            title.strip(),
            author.strip(),
            description.strip(),
            status,
        ]

        if photo_file_id is not None:
            fields.append("photo_file_id = ?")
            params.append(photo_file_id)

        params.append(book_id)
        sql = f"UPDATE books SET {', '.join(fields)} WHERE id = ?"

        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
        return cursor.rowcount > 0

    def delete_book(self, book_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()
        return cursor.rowcount > 0

    def iter_books_with_status(self) -> Iterable[tuple[int, str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, status FROM books ORDER BY id ASC"
            ).fetchall()
        for row in rows:
            yield int(row["id"]), str(row["title"]), str(row["status"])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_book(row: sqlite3.Row) -> Book:
        return Book(
            id=int(row["id"]),
            title=str(row["title"]),
            author=str(row["author"]),
            description=str(row["description"]),
            status=str(row["status"]),
            photo_file_id=str(row["photo_file_id"]),
            created_at=str(row["created_at"]),
        )
