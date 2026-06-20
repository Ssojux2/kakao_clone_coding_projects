from __future__ import annotations

"""일정 payload에서 참석자 기본값을 보정하는 정책입니다."""

from typing import Any


PRIVATE_MEMBER = "나"
DEFAULT_EXTERNAL_MEMBERS = ["철수", "영희"]
KNOWN_MEMBERS = ["철수", "영희", "민준", "서연", "지훈", "유나", "도현"]
SCHEDULE_KINDS = {"personal_schedule", "group_schedule"}
EXPLICIT_GROUP_PHRASES = (
    "외부 팀원",
    "외부팀원",
    "팀원",
    "팀원들",
    "팀 사람",
    "동료",
    "멤버",
    "멤버들",
    "여러 사람",
    "여러 명",
    "다 같이",
    "같이",
    "함께",
    "모두",
    "그룹",
    "단체",
    "공통",
    "참석자",
)


def _text_contains_any(text: str, needles: list[str] | tuple[str, ...]) -> bool:
    return any(needle and needle in text for needle in needles)


def normalize_schedule_payload_for_private_default(
    payload: dict[str, Any],
    *,
    source_text: str | None = None,
) -> dict[str, Any]:
    """명시된 참석자가 없는 일정은 개인 일정으로 저장되도록 보정합니다.

    "회의"나 "미팅"이라는 단어만으로는 그룹 일정으로 보지 않습니다. 사용자가
    특정 이름, 외부 팀원, 팀원들, 같이/함께 같은 단서를 말했을 때만 여러 사람
    일정으로 둡니다.
    """

    normalized = dict(payload)
    if source_text and not normalized.get("original_text"):
        normalized["original_text"] = source_text

    if normalized.get("kind") not in SCHEDULE_KINDS:
        return normalized

    members = [str(member) for member in (normalized.get("members") or []) if str(member).strip()]
    context = " ".join(
        str(value or "")
        for value in (
            source_text,
            normalized.get("original_text"),
            normalized.get("title"),
        )
    )
    has_named_member = _text_contains_any(context, KNOWN_MEMBERS)
    has_group_context = _text_contains_any(context, EXPLICIT_GROUP_PHRASES)
    has_non_default_member = any(member not in {PRIVATE_MEMBER, *DEFAULT_EXTERNAL_MEMBERS} for member in members)

    if has_named_member or has_group_context or has_non_default_member:
        return normalized

    normalized["kind"] = "personal_schedule"
    normalized["members"] = [PRIVATE_MEMBER]
    reason = str(normalized.get("reason") or "").strip()
    private_reason = "별도 참석자가 명시되지 않아 나만 포함한 개인 일정으로 저장합니다."
    normalized["reason"] = f"{reason} {private_reason}".strip() if reason else private_reason
    return normalized
