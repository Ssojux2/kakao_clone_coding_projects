from __future__ import annotations

"""외부 멤버의 과거 대화와 공유 일정을 담는 SQLite 저장소입니다.

수업에서는 실제 카카오톡/캘린더 데이터 대신 이 저장소를 외부 시스템처럼 사용합니다.
Week 5 MCP 서버는 이 저장소를 tool로 감싸고, Week 6은 여기서 나온 busy time과
앱 내부 개인 일정을 합쳐 공통 가능 시간을 계산합니다.
"""

import os
from pathlib import Path
from typing import Any

from fixed.config import CONFIG
from fixed.runtime_clock import app_started_at_iso, next_weekday_iso
from fixed.store_base import SQLiteFileStore, new_id


EXTERNAL_MEMBER_ALIAS: dict[str, str] = {}
PERSONAL_SHARED_MEMBER_NAME = "나"


def external_db_path_from_env() -> Path:
    """환경 변수 또는 기본 설정에서 외부 멤버 SQLite DB 경로를 얻습니다."""

    return Path(os.getenv("KANANA_EXTERNAL_DB_PATH", str(CONFIG.external_db_path)))


def normalize_external_member_names(member_names: list[str] | None) -> list[str]:
    """외부 저장소에서 쓰는 멤버 이름 목록으로 정규화합니다."""

    return [
        EXTERNAL_MEMBER_ALIAS.get(str(name).strip(), str(name).strip())
        for name in (member_names or [])
        if str(name).strip()
    ]


def normalize_external_schedule_date_bounds(
    member_names: list[str] | None,
    date_from: str,
    date_to: str,
) -> tuple[str, str]:
    """외부 일정 조회 날짜 범위의 ISO datetime에서 날짜 부분만 남깁니다."""

    normalized_date_from = str(date_from).split("T", 1)[0].strip() if date_from is not None else ""
    normalized_date_to = str(date_to).split("T", 1)[0].strip() if date_to is not None else ""
    return normalized_date_from, normalized_date_to


def external_schedule_summary(rows: list[dict[str, Any]]) -> str:
    """일정 row 목록을 LLM 답변 근거로 쓰기 쉬운 한글 요약 문자열로 바꿉니다."""

    if not rows:
        return "조회된 외부 일정이 없습니다."
    lines: list[str] = []
    for row in rows:
        member_name = row.get("member_name") or "이름 미정"
        title = row.get("title") or "제목 없음"
        date_text = row.get("date") or "날짜 미정"
        start_time = row.get("start_time") or "시간 미정"
        end_time = row.get("end_time") or "시간 미정"
        notes = row.get("notes") or "비고 없음"
        lines.append(f"- {member_name} | {title} | {date_text} {start_time}-{end_time} | {notes}")
    return "\n".join(lines)


class ExternalPeopleSQLiteStore(SQLiteFileStore):
    """외부 멤버 대화/일정 샘플 DB 저장소입니다.

    Week 5 MCP 도구와 Week 6 Kana agent가 여러 사람의 이전 대화와 바쁜 시간을
    조회할 때 사용합니다. 앱 내부 DB와 분리된 SQLite 파일을 씁니다.
    """

    def __init__(self, path: Path):
        """DB 파일을 준비하고 스키마 생성 및 데모 데이터 보정을 수행합니다."""

        super().__init__(path)
        self.initialize()
        self.seed()

    def initialize(self) -> None:
        """외부 대화/메시지/일정 테이블을 생성합니다."""

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
        """수업 fixture용 외부 멤버 대화와 일정을 현재 실행 날짜 기준으로 채웁니다.

        이미 오래된 데모 row가 있으면 지우거나 날짜를 갱신합니다. 이렇게 해야 테스트와
        데모가 실행 날짜에 맞춰 "다음 주" 데이터를 안정적으로 보여 줍니다.
        """

        with self.connect() as conn:
            legacy_conversation_ids = ["ext_mj", "ext_sy", "ext_jh"]
            placeholders = ",".join("?" for _ in legacy_conversation_ids)
            conn.execute(
                f"DELETE FROM external_schedules WHERE source_conversation_id IN ({placeholders})",
                legacy_conversation_ids,
            )
            conn.execute(
                f"DELETE FROM external_messages WHERE conversation_id IN ({placeholders})",
                legacy_conversation_ids,
            )
            conn.execute(
                f"DELETE FROM external_conversations WHERE conversation_id IN ({placeholders})",
                legacy_conversation_ids,
            )

            conversations = [
                ("ext_cs", "철수", "철수의 다음 주 일정 공유", "철수: 다음 주 화요일 11시는 영업 미팅, 목요일 14시는 파트너 콜이 있어요."),
                ("ext_yh", "영희", "영희의 다음 주 일정 공유", "영희: 다음 주 수요일 13시는 리서치 리뷰, 15시는 마케팅 싱크, 목요일 16시는 콘텐츠 점검입니다."),
            ]
            created_at = app_started_at_iso()
            next_tuesday = next_weekday_iso(1)
            next_wednesday = next_weekday_iso(2)
            next_thursday = next_weekday_iso(3)
            schedules = [
                ("철수", "영업 미팅", next_tuesday, "11:00", "12:00", "ext_cs", "화요일 11시 불가"),
                ("철수", "파트너 콜", next_thursday, "14:00", "15:00", "ext_cs", "목요일 14시 불가"),
                ("영희", "리서치 리뷰", next_wednesday, "13:00", "14:00", "ext_yh", "수요일 13시 불가"),
                ("영희", "마케팅 싱크", next_wednesday, "15:00", "16:00", "ext_yh", "수요일 15시 불가"),
                ("영희", "콘텐츠 점검", next_thursday, "16:00", "17:00", "ext_yh", "목요일 16시 불가"),
            ]
            for conversation_id, member_name, title, content in conversations:
                conn.execute(
                    """
                    INSERT INTO external_conversations VALUES (?, ?, ?, ?)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        member_name = excluded.member_name,
                        title = excluded.title
                    """,
                    (conversation_id, member_name, title, created_at),
                )
                message_exists = conn.execute(
                    """
                    SELECT 1
                    FROM external_messages
                    WHERE conversation_id = ?
                      AND sender = ?
                      AND content = ?
                    LIMIT 1
                    """,
                    (conversation_id, member_name, content),
                ).fetchone()
                if not message_exists:
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
                existing = conn.execute(
                    """
                    SELECT schedule_id
                    FROM external_schedules
                    WHERE member_name = ?
                      AND title = ?
                      AND COALESCE(source_conversation_id, '') = ?
                    LIMIT 1
                    """,
                    (member_name, title, conversation_id),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE external_schedules
                        SET date = ?,
                            start_time = ?,
                            end_time = ?,
                            notes = ?,
                            source_conversation_id = ?
                        WHERE schedule_id = ?
                        """,
                        (date, start_time, end_time, notes, conversation_id, existing["schedule_id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO external_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (new_id("extsch"), member_name, title, date, start_time, end_time, conversation_id, notes),
                    )

    def create_shared_schedule(
        self,
        member_name: str,
        title: str,
        date: str,
        start_time: str,
        end_time: str = "미정",
        notes: str | None = None,
        source_conversation_id: str | None = None,
        schedule_id: str | None = None,
    ) -> dict[str, Any]:
        """공유 일정 저장소에 일정 하나를 등록하거나 같은 ID의 일정을 갱신합니다."""

        normalized_member_name = str(member_name or PERSONAL_SHARED_MEMBER_NAME).strip() or PERSONAL_SHARED_MEMBER_NAME
        normalized_title = str(title or "제목 없음").strip() or "제목 없음"
        normalized_date = str(date).split("T", 1)[0].strip() if date is not None else ""
        if not normalized_date:
            raise ValueError("date is required to create a shared schedule")
        normalized_start_time = str(start_time or "미정").strip() or "미정"
        normalized_end_time = str(end_time or "미정").strip() or "미정"
        normalized_notes = notes or "공유 일정"
        selected_schedule_id = schedule_id or new_id("shared")
        sync_status = "created"

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT schedule_id FROM external_schedules WHERE schedule_id = ?",
                (selected_schedule_id,),
            ).fetchone()
            if existing:
                sync_status = "updated"
            conn.execute(
                """
                INSERT INTO external_schedules
                    (schedule_id, member_name, title, date, start_time, end_time, source_conversation_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    member_name = excluded.member_name,
                    title = excluded.title,
                    date = excluded.date,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    source_conversation_id = excluded.source_conversation_id,
                    notes = excluded.notes
                """,
                (
                    selected_schedule_id,
                    normalized_member_name,
                    normalized_title,
                    normalized_date,
                    normalized_start_time,
                    normalized_end_time,
                    source_conversation_id,
                    normalized_notes,
                ),
            )

        return {
            "schedule_id": selected_schedule_id,
            "member_name": normalized_member_name,
            "title": normalized_title,
            "date": normalized_date,
            "start_time": normalized_start_time,
            "end_time": normalized_end_time,
            "source_conversation_id": source_conversation_id,
            "notes": normalized_notes,
            "sync_status": sync_status,
        }

    def delete_shared_schedules(
        self,
        schedule_id: str | None = None,
        source_conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """공유 일정 저장소에서 ID 또는 원본 요청 ID에 해당하는 일정을 삭제합니다."""

        if not schedule_id and not source_conversation_id:
            return []

        where: list[str] = []
        params: list[Any] = []
        if schedule_id:
            where.append("schedule_id = ?")
            params.append(schedule_id)
        if source_conversation_id:
            where.append("source_conversation_id = ?")
            params.append(source_conversation_id)

        with self.connect() as conn:
            cur = conn.execute(
                f"""
                SELECT schedule_id, member_name, title, date, start_time, end_time, notes, source_conversation_id
                FROM external_schedules
                WHERE {" OR ".join(where)}
                """,
                params,
            )
            rows = [dict(row) for row in cur.fetchall()]
            conn.execute(f"DELETE FROM external_schedules WHERE {' OR '.join(where)}", params)
        return rows

    def list_shared_schedules(
        self,
        member_names: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """공유 일정 저장소의 row를 필터링해 조회합니다."""

        where: list[str] = []
        params: list[Any] = []
        normalized_members = [
            EXTERNAL_MEMBER_ALIAS.get(str(name).strip(), str(name).strip())
            for name in (member_names or [])
            if str(name).strip()
        ]
        if member_names is not None and not normalized_members:
            return []
        if normalized_members:
            placeholders = ",".join("?" for _ in normalized_members)
            where.append(f"member_name IN ({placeholders})")
            params.extend(normalized_members)

        normalized_date_from = str(date_from).split("T", 1)[0].strip() if date_from is not None else ""
        normalized_date_to = str(date_to).split("T", 1)[0].strip() if date_to is not None else ""
        if normalized_date_from:
            where.append("date >= ?")
            params.append(normalized_date_from)
        if normalized_date_to:
            where.append("date <= ?")
            params.append(normalized_date_to)
        if source_conversation_id:
            where.append("source_conversation_id = ?")
            params.append(source_conversation_id)

        sql = """
            SELECT schedule_id, member_name, title, date, start_time, end_time, notes, source_conversation_id
            FROM external_schedules
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date, start_time, member_name LIMIT ?"
        params.append(max(1, min(int(limit or 50), 200)))
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def search_previous_conversations(
        self,
        query: str,
        member_names: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """LLM이 넘긴 query와 멤버 필터로 외부 멤버의 과거 메시지를 검색합니다."""

        query_text = str(query or "").strip()
        clauses: list[str] = []
        params: list[Any] = []
        if member_names is not None:
            normalized_members = normalize_external_member_names(member_names)
            if not normalized_members:
                return []
            placeholders = ",".join("?" for _ in normalized_members)
            clauses.append(f"c.member_name IN ({placeholders})")
            params.extend(normalized_members)
        if query_text:
            clauses.append("(m.content LIKE ? OR c.title LIKE ?)")
            token = f"%{query_text}%"
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
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def load_conversation_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """conversation_id 하나에 속한 외부 메시지를 작성 순서대로 반환합니다."""

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
            return [dict(row) for row in cur.fetchall()]

    def extract_schedules_from_history(
        self,
        member_names: list[str] | None,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """멤버와 날짜 범위에 맞는 외부 busy-time row를 반환합니다.

        이 프로젝트에서는 "대화에서 일정을 추출"하는 기능을 실제 LLM 추출 대신
        seed된 `external_schedules` 테이블 조회로 재현합니다.
        """

        normalized_members = normalize_external_member_names(member_names)
        date_from, date_to = normalize_external_schedule_date_bounds(member_names, date_from, date_to)
        member_filter = ""
        params: list[Any] = [date_from, date_to]
        if member_names is not None:
            if not normalized_members:
                return []
            placeholders = ",".join("?" for _ in normalized_members)
            member_filter = f"AND member_name IN ({placeholders})"
            params.extend(normalized_members)
        with self.connect() as conn:
            cur = conn.execute(
                f"""
                SELECT member_name, title, date, start_time, end_time, notes, source_conversation_id
                FROM external_schedules
                WHERE date >= ?
                  AND date <= ?
                  {member_filter}
                ORDER BY date, start_time
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
