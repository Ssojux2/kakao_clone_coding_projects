from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fixed.config import CONFIG
from fixed.runtime_clock import app_started_at_iso, next_weekday_iso


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def rows_to_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def decode_schedule_row(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    raw_attendees = decoded.pop("attendees_json", "[]") or "[]"
    try:
        decoded["attendees"] = json.loads(raw_attendees)
    except Exception:
        decoded["attendees"] = []
    return decoded


SCHEDULE_COLUMNS = (
    "schedule_id, request_id, owner, title, date, start_time, end_time, "
    "attendees_json, source, created_at"
)


class SQLiteFileStore:
    """파일 기반 SQLite 저장소가 공유하는 경로 준비와 연결 설정입니다."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


class AppSQLiteStore(SQLiteFileStore):
    """앱 내부 DB 저장소입니다.

    대화 로그, Week 3 structured output, 정규화된 개인 일정/할 일/알림을 같은
    SQLite 파일에 보관합니다. Week 4+ 도구는 이 저장소의 schedules 테이블을
    RAG 후보 데이터로 사용합니다.
    """

    def __init__(self, path: Path):
        super().__init__(path)
        self.initialize()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
                );

                CREATE TABLE IF NOT EXISTS structured_requests (
                    request_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT,
                    date TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    members_json TEXT NOT NULL DEFAULT '[]',
                    priority TEXT,
                    reason TEXT,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    owner TEXT NOT NULL DEFAULT 'me',
                    title TEXT NOT NULL,
                    date TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    attendees_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'structured_output',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS todos (
                    todo_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    title TEXT NOT NULL,
                    due_date TEXT,
                    priority TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    title TEXT NOT NULL,
                    date TEXT,
                    start_time TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    # Conversation history

    def create_conversation(self, title: str = "새 대화") -> dict[str, Any]:
        conversation_id = new_id("conv")
        created_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (conversation_id, title, status, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?)
                """,
                (conversation_id, title[:80] or "새 대화", created_at, created_at),
            )
        return {"conversation_id": conversation_id, "title": title[:80] or "새 대화"}

    def append_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        message_id = new_id("msg")
        created_at = now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (message_id, conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, role, content, created_at),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ?, title = CASE WHEN title = '새 대화' THEN ? ELSE title END WHERE conversation_id = ?",
                (created_at, content[:40] or "새 대화", conversation_id),
            )
        return {"message_id": message_id, "conversation_id": conversation_id}

    def list_conversations(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT c.conversation_id, c.title, c.status, c.updated_at,
                       COUNT(m.message_id) AS message_count,
                       COALESCE((SELECT content FROM messages WHERE conversation_id = c.conversation_id ORDER BY created_at DESC, rowid DESC LIMIT 1), '') AS last_message
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                WHERE c.status = 'active'
                GROUP BY c.conversation_id
                ORDER BY c.updated_at DESC, c.rowid DESC
                LIMIT 30
                """
            )
            return rows_to_dicts(cur)

    def load_conversation(self, conversation_id: str) -> list[dict[str, str]]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            )
            return rows_to_dicts(cur)

    def archive_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                "UPDATE conversations SET status = 'archived', updated_at = ? WHERE conversation_id = ?",
                (now_iso(), conversation_id),
            )
        return {"conversation_id": conversation_id, "status": "archived"}

    def delete_conversation(self, conversation_id: str | None) -> dict[str, Any]:
        if not conversation_id:
            return {"conversation_id": "", "deleted": False}
        with self.connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cur = conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        return {"conversation_id": conversation_id, "deleted": cur.rowcount > 0}

    # Week 3 structured output persistence

    def save_structured_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = new_id("req")
        kind = payload.get("kind", "unknown")
        title = payload.get("title") or "제목 없음"
        date = payload.get("date")
        start_time = payload.get("start_time")
        end_time = payload.get("end_time")
        members = payload.get("members") or []
        priority = payload.get("priority")
        reason = payload.get("reason")
        created_at = now_iso()
        saved_rows: list[dict[str, Any]] = []

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_requests
                    (request_id, kind, title, date, start_time, end_time, members_json, priority, reason, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    kind,
                    title,
                    date,
                    start_time,
                    end_time,
                    json.dumps(members, ensure_ascii=False),
                    priority,
                    reason,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
            saved_rows.append({"table": "structured_requests", "id": request_id})

            if kind in {"personal_schedule", "group_schedule"}:
                schedule_id = new_id("sch")
                conn.execute(
                    """
                    INSERT INTO schedules
                        (schedule_id, request_id, owner, title, date, start_time, end_time, attendees_json, source, created_at)
                    VALUES (?, ?, 'me', ?, ?, ?, ?, ?, 'structured_output', ?)
                    """,
                    (
                        schedule_id,
                        request_id,
                        title,
                        date,
                        start_time,
                        end_time,
                        json.dumps(members, ensure_ascii=False),
                        created_at,
                    ),
                )
                saved_rows.append({"table": "schedules", "id": schedule_id})
            elif kind == "todo":
                todo_id = new_id("todo")
                conn.execute(
                    """
                    INSERT INTO todos (todo_id, request_id, title, due_date, priority, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (todo_id, request_id, title, date, priority, created_at),
                )
                saved_rows.append({"table": "todos", "id": todo_id})
            elif kind == "reminder":
                reminder_id = new_id("rem")
                conn.execute(
                    """
                    INSERT INTO reminders (reminder_id, request_id, title, date, start_time, reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (reminder_id, request_id, title, date, start_time, reason, created_at),
                )
                saved_rows.append({"table": "reminders", "id": reminder_id})

        return {"request_id": request_id, "kind": kind, "saved_rows": saved_rows}

    # Structured request lookup

    def list_saved_requests(
        self,
        kind: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if date_from:
            where.append("date >= ?")
            params.append(date_from)
        if date_to:
            where.append("date <= ?")
            params.append(date_to)
        query = "SELECT * FROM structured_requests"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return rows_to_dicts(conn.execute(query, params))

    def get_saved_request(self, request_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM structured_requests WHERE request_id = ?", (request_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def search_saved_requests(self, query: str, kind: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        terms = [term for term in query.replace(",", " ").split() if term]
        clauses = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if terms:
            like_clause = " OR ".join(["raw_json LIKE ? OR title LIKE ? OR reason LIKE ?" for _ in terms])
            clauses.append(f"({like_clause})")
            for term in terms:
                token = f"%{term}%"
                params.extend([token, token, token])
        sql = "SELECT * FROM structured_requests"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return rows_to_dicts(conn.execute(sql, params))

    # Schedule lookup and deletion

    def list_schedules(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                f"""
                SELECT {SCHEDULE_COLUMNS}
                FROM schedules
                ORDER BY (date IS NULL), date ASC, (start_time IS NULL), start_time ASC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = rows_to_dicts(cur)
        return [decode_schedule_row(row) for row in rows]

    def find_schedules(
        self,
        schedule_ids: list[str] | None = None,
        date: str | None = None,
        title: str | None = None,
        start_time: str | None = None,
        time_unspecified: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """일정 ID나 날짜/제목/시간 필터에 맞는 저장 일정을 찾습니다."""

        if schedule_ids is not None and not schedule_ids:
            return []

        where: list[str] = []
        params: list[Any] = []
        if schedule_ids is not None:
            placeholders = ", ".join("?" for _ in schedule_ids)
            where.append(f"schedule_id IN ({placeholders})")
            params.extend(schedule_ids)
        if date:
            where.append("date = ?")
            params.append(date)
        if title:
            where.append("(title LIKE ? OR REPLACE(title, ' ', '') LIKE ?)")
            params.extend([f"%{title}%", f"%{title.replace(' ', '')}%"])
        if start_time:
            where.append("start_time = ?")
            params.append(start_time)
        if time_unspecified:
            where.append("(start_time IS NULL OR start_time = '' OR start_time = '미정')")

        sql = f"""
            SELECT {SCHEDULE_COLUMNS}
            FROM schedules
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = rows_to_dicts(conn.execute(sql, params))
        return [decode_schedule_row(row) for row in rows]

    def delete_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT {SCHEDULE_COLUMNS}
                FROM schedules
                WHERE schedule_id = ?
                """,
                (schedule_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
            conn.execute(
                """
                DELETE FROM structured_requests
                WHERE request_id = ?
                  AND kind IN ('personal_schedule', 'group_schedule')
                """,
                (row["request_id"],),
            )

        return decode_schedule_row(dict(row))

    def delete_schedules_by_filter(
        self,
        schedule_ids: list[str] | None = None,
        date: str | None = None,
        title: str | None = None,
        start_time: str | None = None,
        time_unspecified: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """일정 ID나 날짜/제목/시간 필터에 맞는 저장 일정을 삭제합니다."""

        if schedule_ids is None and not any([date, title, start_time, time_unspecified]):
            return []

        rows = self.find_schedules(
            schedule_ids=schedule_ids,
            date=date,
            title=title,
            start_time=start_time,
            time_unspecified=time_unspecified,
            limit=limit,
        )
        deleted: list[dict[str, Any]] = []
        for row in rows:
            deleted_row = self.delete_schedule(row["schedule_id"])
            if deleted_row:
                deleted.append(deleted_row)
        return deleted

    def delete_all_schedules(self) -> list[dict[str, Any]]:
        """앱 DB에 저장된 모든 일정과 일정 구조화 요청을 삭제합니다."""

        with self.connect() as conn:
            cur = conn.execute(
                f"""
                SELECT {SCHEDULE_COLUMNS}
                FROM schedules
                ORDER BY created_at DESC
                """
            )
            deleted_rows = rows_to_dicts(cur)
            conn.execute("DELETE FROM schedules")
            conn.execute(
                """
                DELETE FROM structured_requests
                WHERE kind IN ('personal_schedule', 'group_schedule')
                """
            )

        return [decode_schedule_row(row) for row in deleted_rows]


class ExternalPeopleSQLiteStore(SQLiteFileStore):
    """외부 멤버 대화/일정 샘플 DB 저장소입니다.

    Week 5 MCP 도구와 Week 6 Kana agent가 여러 사람의 이전 대화와 바쁜 시간을
    조회할 때 사용합니다. 앱 내부 DB와 분리된 SQLite 파일을 씁니다.
    """

    def __init__(self, path: Path):
        super().__init__(path)
        self.initialize()
        self.seed()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    member_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS external_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES external_conversations(conversation_id)
                );

                CREATE TABLE IF NOT EXISTS external_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    member_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    source_conversation_id TEXT,
                    notes TEXT
                );
                """
            )

    def seed(self) -> None:
        with self.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM external_schedules").fetchone()["count"]
            if count:
                return

            conversations = [
                ("ext_mj", "민준", "민준의 다음 주 일정 공유", "민준: 다음 주 화요일 10시에는 면담, 수요일 14시에는 코드 리뷰가 있어요."),
                ("ext_sy", "서연", "서연의 다음 주 일정 공유", "서연: 화요일 13시는 디자인 싱크, 수요일 10시는 고객 미팅입니다."),
                ("ext_jh", "지훈", "지훈의 다음 주 일정 공유", "지훈: 화요일 15시 배포 점검, 목요일 오전은 워크숍으로 막혀 있어요."),
            ]
            created_at = app_started_at_iso()
            next_tuesday = next_weekday_iso(1)
            next_wednesday = next_weekday_iso(2)
            next_thursday = next_weekday_iso(3)
            schedules = [
                ("민준", "멘토 면담", next_tuesday, "10:00", "11:00", "ext_mj", "다음 주 화요일 오전 불가"),
                ("민준", "코드 리뷰", next_wednesday, "14:00", "15:00", "ext_mj", "수요일 14시 불가"),
                ("서연", "디자인 싱크", next_tuesday, "13:00", "14:00", "ext_sy", "화요일 점심 직후 불가"),
                ("서연", "고객 미팅", next_wednesday, "10:00", "11:00", "ext_sy", "수요일 오전 불가"),
                ("지훈", "배포 점검", next_tuesday, "15:00", "16:00", "ext_jh", "화요일 오후 불가"),
                ("지훈", "워크숍", next_thursday, "10:00", "12:00", "ext_jh", "목요일 오전 불가"),
            ]
            for conversation_id, member_name, title, content in conversations:
                conn.execute(
                    "INSERT INTO external_conversations VALUES (?, ?, ?, ?)",
                    (conversation_id, member_name, title, created_at),
                )
                conn.execute(
                    "INSERT INTO external_messages VALUES (?, ?, 'user', ?, ?, ?)",
                    (
                        new_id("extmsg"),
                        conversation_id,
                        member_name,
                        content,
                        created_at,
                    ),
                )
            for member_name, title, date, start_time, end_time, conversation_id, notes in schedules:
                conn.execute(
                    "INSERT INTO external_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("extsch"), member_name, title, date, start_time, end_time, conversation_id, notes),
                )

    def search_previous_conversations(
        self,
        query: str,
        member_names: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        terms = [term for term in query.replace(",", " ").split() if term]
        clauses: list[str] = []
        params: list[Any] = []
        if member_names:
            placeholders = ",".join("?" for _ in member_names)
            clauses.append(f"c.member_name IN ({placeholders})")
            params.extend(member_names)
        if terms:
            like_clause = " OR ".join(["m.content LIKE ? OR c.title LIKE ?" for _ in terms])
            clauses.append(f"({like_clause})")
            for term in terms:
                token = f"%{term}%"
                params.extend([token, token])
        sql = """
            SELECT c.conversation_id, c.member_name, c.title, m.content, m.created_at
            FROM external_conversations c
            JOIN external_messages m ON m.conversation_id = c.conversation_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            return rows_to_dicts(conn.execute(sql, params))

    def load_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT role, sender, content, created_at
                FROM external_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            return rows_to_dicts(cur)

    def extract_schedules_from_history(
        self,
        member_names: list[str],
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in member_names)
        with self.connect() as conn:
            cur = conn.execute(
                f"""
                SELECT member_name, title, date, start_time, end_time, notes, source_conversation_id
                FROM external_schedules
                WHERE member_name IN ({placeholders})
                  AND date >= ?
                  AND date <= ?
                ORDER BY date, start_time
                """,
                [*member_names, date_from, date_to],
            )
            return rows_to_dicts(cur)


class OpenAIEmbeddingFunction:
    """ChromaDB가 호출할 수 있는 OpenAI embeddings adapter입니다."""

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model
        self._client: Any | None = None

    def name(self) -> str:
        return f"openai_{self.model}"

    def is_legacy(self) -> bool:
        # ChromaDB의 custom embedding function 호환 경로를 사용합니다.
        return True

    def _openai_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY가 필요합니다. .env에 키를 추가한 뒤 다시 실행하세요.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def __call__(self, input: list[str]) -> list[list[float]]:
        response = self._openai_client().embeddings.create(model=self.model, input=input)
        return [item.embedding for item in response.data]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)


class PersonalReferenceStore:
    """Week 4 개인 참고자료 RAG 저장소입니다.

    참고자료는 ChromaDB에 저장하고, 벡터는 `.env`의 OpenAI embedding 설정으로
    생성합니다. OPENAI_API_KEY가 없으면 앱 import는 가능하지만 실제 add/query
    시점에 명확한 오류를 냅니다.
    """

    COLLECTION_NAME = "kanana_personal_references_openai"
    DEFAULT_REFERENCES = [
        {
            "id": "ref_focus",
            "title": "집중 회의 선호",
            "content": "나는 오전 10시에서 12시 사이에 집중도가 높아서 중요한 회의는 오전 중반을 선호한다.",
            "tags": ["preference", "meeting"],
        },
        {
            "id": "ref_lunch",
            "title": "점심 시간 보호",
            "content": "점심 시간 12:00-13:00은 되도록 회의 없이 비워둔다.",
            "tags": ["preference", "lunch"],
        },
        {
            "id": "ref_sync",
            "title": "팀 싱크 방식",
            "content": "팀 싱크는 60분 이하로 잡고 회의 전날 아젠다를 공유하면 좋다.",
            "tags": ["team", "meeting"],
        },
    ]

    def __init__(self, chroma_dir: Path):
        import chromadb

        self.chroma_dir = chroma_dir
        chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(chroma_dir))
        self.collection = client.get_or_create_collection(
            self.COLLECTION_NAME,
            embedding_function=OpenAIEmbeddingFunction(
                api_key=CONFIG.openai_api_key,
                model=CONFIG.openai_embedding_model,
            ),
            metadata={
                "description": "Kanana course personal references",
                "embedding_provider": "openai",
                "embedding_model": CONFIG.openai_embedding_model,
            },
        )
        if CONFIG.has_openai_key:
            self.seed()

    def backend_info(self) -> dict[str, Any]:
        """Week 4가 사용하는 vector store와 embedding backend를 설명합니다."""

        return {
            "vector_store": "chromadb",
            "embedding_provider": "openai",
            "embedding_model": CONFIG.openai_embedding_model,
            "collection_name": self.COLLECTION_NAME,
            "chroma_dir": str(self.chroma_dir),
        }

    def seed(self) -> None:
        if self.collection.count():
            return
        self.collection.add(
            ids=[item["id"] for item in self.DEFAULT_REFERENCES],
            documents=[item["content"] for item in self.DEFAULT_REFERENCES],
            metadatas=[{"title": item["title"], "tags": ",".join(item["tags"])} for item in self.DEFAULT_REFERENCES],
        )

    def add_personal_reference(self, title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
        reference_id = new_id("ref")
        self.collection.add(
            ids=[reference_id],
            documents=[content],
            metadatas=[{"title": title, "tags": ",".join(tags or [])}],
        )
        return {
            "reference_id": reference_id,
            "title": title,
            "content": content,
            "tags": tags or [],
            "backend": self.backend_info(),
        }

    def search_personal_references(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        result = self.collection.query(query_texts=[query], n_results=limit)
        hits: list[dict[str, Any]] = []
        for index, document in enumerate(result.get("documents", [[]])[0]):
            metadata = result.get("metadatas", [[]])[0][index] or {}
            distance = result.get("distances", [[]])[0][index]
            hits.append(
                {
                    "id": result.get("ids", [[]])[0][index],
                    "title": metadata.get("title", ""),
                    "content": document,
                    "tags": metadata.get("tags", ""),
                    "distance": distance,
                }
            )
        return hits
