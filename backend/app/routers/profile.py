"""Модуль 2: One-Click Enrichment и Evidence.

Каждый изменяющий эндпоинт возвращает профиль целиком. Так страница
перерисовывается из одного источника правды и не расходится с базой - это
дешевле, чем чинить рассинхрон частичных обновлений на фронтенде.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.declines import (
    TARGET_EVIDENCE,
    TARGET_STATEMENT,
    record_decline,
    revoke_declines,
)
from app.enrichment import (
    DECLINED,
    PENDING,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_FREE_TEXT,
    TYPE_LINK,
    EvidenceFacts,
    compute_status,
    parse_free_text,
    source_category_from_url,
)
from app.models import DeclineRecord, Evidence, RawInput, Statement, User
from app.routers.auth import current_user
from app.schemas_profile import (
    AcceptIn,
    BlindWitnessIn,
    DeclineIn,
    FreeTextIn,
    LinkIn,
    ParsedItemOut,
    ParseOut,
    ProfileOut,
    StatementIn,
)
from app.taxonomy import BY_KEY

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Ограничения загрузки из FR1.3.
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
MAX_FILE_BYTES = 10 * 1024 * 1024


# --- публичные идентификаторы (stmt_001, ev_003, dec_001) -----------------


def public_id(prefix: str, number: int) -> str:
    return f"{prefix}_{number:03d}"


def parse_id(prefix: str, value: str) -> int:
    """Разбирает `ev_003` обратно в 3. Мусор считаем «не найдено»."""
    head, _, tail = value.partition("_")
    if head != prefix or not tail.isdigit():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден.")
    return int(tail)


# --- выборка и сериализация ----------------------------------------------


def _statements(db: Session, user: User) -> list[Statement]:
    return list(
        db.scalars(
            select(Statement).where(Statement.user_id == user.id).order_by(Statement.id)
        )
    )


def _evidence(db: Session, user: User) -> list[Evidence]:
    return list(
        db.scalars(select(Evidence).where(Evidence.user_id == user.id).order_by(Evidence.id))
    )


def _declines(db: Session, user: User) -> list[DeclineRecord]:
    return list(
        db.scalars(
            select(DeclineRecord)
            .where(DeclineRecord.user_id == user.id)
            .order_by(DeclineRecord.id)
        )
    )


def _serialize_evidence(item: Evidence) -> dict:
    return {
        "id": public_id("ev", item.id),
        "type": item.type,
        "source_category": item.source_category,
        "url": item.url,
        "file_ref": item.file_ref,
        "file_name": item.file_name,
        "raw_text": item.raw_text,
        "nda": item.nda,
        "status": item.status,
        "linked_statement_ids": [public_id("stmt", s.id) for s in item.statements],
        "created_at": item.created_at,
    }


def _serialize_statement(item: Statement, declined_ids: set[int]) -> dict:
    view = compute_status(
        [
            EvidenceFacts(type=e.type, source_category=e.source_category, status=e.status)
            for e in item.evidence
        ]
    )
    return {
        "id": public_id("stmt", item.id),
        "skill_name": item.skill_name,
        "skill_name_ru": item.skill_name_ru,
        "category": item.category,
        "source_of_claim": item.source_of_claim,
        "status": view.status,
        "status_reason": view.reason,
        "next_action": view.next_action,
        "next_action_kind": view.next_action_kind,
        "evidence_ids": [public_id("ev", e.id) for e in item.evidence],
        "declined": item.id in declined_ids,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _profile(db: Session, user: User) -> ProfileOut:
    # Отказы по вопросам Contextual Probe (target_type "question") сюда не
    # попадают: их место - история вопросов модуля 4, а не карта доказательств.
    declines = [d for d in _declines(db, user) if d.target_type != "question"]
    declined_statement_ids = {d.target_id for d in declines if d.target_type == "statement"}

    return ProfileOut.model_validate(
        {
            "statements": [
                _serialize_statement(s, declined_statement_ids) for s in _statements(db, user)
            ],
            "evidence": [_serialize_evidence(e) for e in _evidence(db, user)],
            "declines": [
                {
                    "id": public_id("dec", d.id),
                    "target_type": d.target_type,
                    "target_id": public_id(
                        "stmt" if d.target_type == "statement" else "ev", d.target_id
                    ),
                    "reason": d.reason,
                    "timestamp": d.timestamp,
                }
                for d in declines
            ],
        }
    )


def _get_statement(db: Session, user: User, statement_id: str) -> Statement:
    item = db.get(Statement, parse_id("stmt", statement_id))
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компетенция не найдена.")
    return item


def _get_evidence(db: Session, user: User, evidence_id: str) -> Evidence:
    item = db.get(Evidence, parse_id("ev", evidence_id))
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Доказательство не найдено.")
    return item


def _ensure_statement(
    db: Session, user: User, *, key: str, ru: str, category: str, source_of_claim: str
) -> Statement:
    """Находит компетенцию кандидата или заводит новую.

    Повторная находка той же компетенции не создаёт дубль, а усиливает
    существующую (FR2.4).
    """
    existing = db.scalar(
        select(Statement).where(Statement.user_id == user.id, Statement.skill_name == key)
    )
    if existing is not None:
        return existing

    item = Statement(
        user_id=user.id,
        skill_name=key,
        skill_name_ru=ru,
        category=category,
        source_of_claim=source_of_claim,
    )
    db.add(item)
    db.flush()
    return item


# --- профиль целиком ------------------------------------------------------


@router.get("", response_model=ProfileOut)
def read_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProfileOut:
    return _profile(db, user)


# --- US2: свободный текст -> компетенции ---------------------------------


@router.post("/parse", response_model=ParseOut)
def parse(
    data: FreeTextIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ParseOut:
    """Разбирает текст, но ничего не добавляет в профиль.

    Сохраняется только сам текст - дословно, как контрольный образец (FR2.5).
    Что из разбора попадёт в профиль, решает кандидат отдельным запросом.
    """
    raw = RawInput(user_id=user.id, text=data.raw_text)
    db.add(raw)
    db.commit()
    db.refresh(raw)

    items = [
        ParsedItemOut(
            skill_name=item.skill_name,
            skill_name_ru=item.skill_name_ru,
            category=item.category,
            excerpt=item.excerpt,
            confidence=item.confidence,
        )
        for item in parse_free_text(data.raw_text)
    ]
    return ParseOut(raw_input_id=public_id("raw", raw.id), items=items)


@router.post("/statements/accept", response_model=ProfileOut)
def accept_parsed(
    data: AcceptIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    """Принимает то, что кандидат оставил после разбора (FR2.3, FR2.4)."""
    raw = db.get(RawInput, parse_id("raw", data.raw_input_id))
    if raw is None or raw.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Исходный текст не найден.")

    for item in data.items:
        key = item.skill_name or item.skill_name_ru
        statement = _ensure_statement(
            db,
            user,
            key=key,
            ru=item.skill_name_ru,
            category=item.category,
            source_of_claim="free_text",
        )
        evidence = Evidence(
            user_id=user.id,
            type=TYPE_FREE_TEXT,
            raw_text=item.excerpt or raw.text,
            status=PENDING,
        )
        db.add(evidence)
        evidence.statements.append(statement)

    db.commit()
    return _profile(db, user)


@router.post("/statements", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_statement(
    data: StatementIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    """Компетенция, добавленная руками: пока без доказательств - Not started."""
    known = next((c for c in BY_KEY.values() if c.ru.lower() == data.skill_name_ru.lower()), None)
    _ensure_statement(
        db,
        user,
        key=known.key if known else data.skill_name_ru,
        ru=known.ru if known else data.skill_name_ru,
        category=known.category if known else data.category,
        source_of_claim="manual",
    )
    db.commit()
    return _profile(db, user)


# --- US1: ссылки и файлы --------------------------------------------------


@router.post("/evidence/link", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def add_link(
    data: LinkIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    url = str(data.url)
    evidence = Evidence(
        user_id=user.id,
        type=TYPE_LINK,
        source_category=data.source_category or source_category_from_url(url),
        url=url,
        status=PENDING,
    )
    db.add(evidence)

    for statement_id in data.statement_ids:
        evidence.statements.append(_get_statement(db, user, statement_id))

    db.commit()
    return _profile(db, user)


@router.post("/evidence/file", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
async def add_file(
    file: UploadFile = File(...),
    # Через форму список приходит строкой: "stmt_001,stmt_004".
    statement_ids: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Файл-артефакт: портфолио, сертификат, презентация (FR1.3, FR1.4)."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Подойдут PDF, DOCX, PNG или JPG.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Файл больше 10 МБ - выберите файл поменьше.",
        )
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пустой.")

    # Сначала проверяем, к чему привязываем, и только потом пишем на диск:
    # иначе неверный идентификатор оставил бы файл-сироту в хранилище.
    targets = [
        _get_statement(db, user, statement_id)
        for statement_id in (s.strip() for s in statement_ids.split(",") if s.strip())
    ]

    folder = Path(settings.upload_dir) / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    stored_path = folder / stored_name
    stored_path.write_bytes(content)

    evidence = Evidence(
        user_id=user.id,
        type=TYPE_FILE,
        file_ref=f"{user.id}/{stored_name}",
        file_name=file.filename,
        status=PENDING,
    )
    db.add(evidence)
    evidence.statements.extend(targets)

    try:
        db.commit()
    except Exception:
        # Запись в базу не прошла - файл на диске тоже не нужен.
        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise
    return _profile(db, user)


@router.get("/evidence/{evidence_id}/file")
def download_file(
    evidence_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> FileResponse:
    evidence = _get_evidence(db, user, evidence_id)
    if evidence.type != TYPE_FILE or not evidence.file_ref:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У этого доказательства нет файла.")

    path = Path(settings.upload_dir) / evidence.file_ref
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден на диске.")
    return FileResponse(path, filename=evidence.file_name or path.name)


# --- US3: связь доказательства с компетенцией -----------------------------


@router.post("/statements/{statement_id}/evidence/{evidence_id}", response_model=ProfileOut)
def link_evidence(
    statement_id: str,
    evidence_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Связь многие-ко-многим: одна ссылка может подтверждать несколько
    компетенций, одну компетенцию - несколько доказательств (FR3.5)."""
    statement = _get_statement(db, user, statement_id)
    evidence = _get_evidence(db, user, evidence_id)

    if statement not in evidence.statements:
        evidence.statements.append(statement)
        db.commit()
    return _profile(db, user)


@router.delete("/statements/{statement_id}/evidence/{evidence_id}", response_model=ProfileOut)
def unlink_evidence(
    statement_id: str,
    evidence_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    statement = _get_statement(db, user, statement_id)
    evidence = _get_evidence(db, user, evidence_id)

    if statement in evidence.statements:
        evidence.statements.remove(statement)
        db.commit()
    return _profile(db, user)


# --- US4: NDA, Слепой свидетель и отказы ----------------------------------


@router.post(
    "/evidence/blind-witness", response_model=ProfileOut, status_code=status.HTTP_201_CREATED
)
def add_blind_witness(
    data: BlindWitnessIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    """Подтверждение под NDA: логика решений вместо артефакта (FR4.4).

    Ни названия клиента, ни кода, ни документов здесь нет и быть не может -
    сюда приходит только ответ кандидата, и он же единственное, что сохраняется.

    Слепой свидетель - это НЕ отказ. Кандидат подтверждает, что опыт есть, и
    объясняет логику решений; он лишь не раскрывает материалы. Поэтому
    DeclineRecord здесь не создаётся: отказ - это отдельное явное действие
    кандидата «не подтверждать / не раскрывать этот факт», и только оно.
    Иначе NDA превращался бы в пометку «отказался», то есть в наказание за
    отсутствие публичного следа.
    """
    evidence = Evidence(
        user_id=user.id,
        type=TYPE_BLIND_WITNESS,
        raw_text=data.answer,
        nda=True,
        status=PENDING,
    )
    db.add(evidence)

    statements: list[Statement] = []
    if data.statement_ids:
        statements = [_get_statement(db, user, sid) for sid in data.statement_ids]
    else:
        # Кандидат пришёл из описания проекта, а не из конкретной компетенции:
        # разбираем сам ответ - он уже у нас и ничего конфиденциального
        # раскрывать не потребовал.
        for item in parse_free_text(data.answer):
            statements.append(
                _ensure_statement(
                    db,
                    user,
                    key=item.skill_name,
                    ru=item.skill_name_ru,
                    category=item.category,
                    source_of_claim="free_text",
                )
            )

    # Пометка «материалы не раскрывались» живёт на самом доказательстве
    # (Evidence.nda), а не отдельной записью об отказе.
    for statement in statements:
        evidence.statements.append(statement)

    db.commit()
    return _profile(db, user)


@router.post("/evidence/{evidence_id}/decline", response_model=ProfileOut)
def decline_evidence(
    evidence_id: str,
    data: DeclineIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Отказ раскрывать источник. Причину указывать не обязательно (FR4.3)."""
    evidence = _get_evidence(db, user, evidence_id)
    evidence.status = DECLINED
    record_decline(
        db, user, target_type=TARGET_EVIDENCE, target_id=evidence.id, reason=data.reason
    )
    db.commit()
    return _profile(db, user)


@router.delete("/evidence/{evidence_id}/decline", response_model=ProfileOut)
def restore_evidence(
    evidence_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    """Отказ обратим: кандидат может вернуться и раскрыть источник (FR4.7)."""
    evidence = _get_evidence(db, user, evidence_id)
    evidence.status = PENDING
    revoke_declines(db, user, target_type=TARGET_EVIDENCE, target_id=evidence.id)
    db.commit()
    return _profile(db, user)


@router.delete("/evidence/{evidence_id}", response_model=ProfileOut)
def remove_evidence(
    evidence_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    """Удаление до связи с компетенцией - настоящее; после связи -
    превращается в отказ и остаётся в истории (FR1.6)."""
    evidence = _get_evidence(db, user, evidence_id)

    if evidence.statements:
        evidence.status = DECLINED
        record_decline(db, user, target_type=TARGET_EVIDENCE, target_id=evidence.id)
    else:
        if evidence.type == TYPE_FILE and evidence.file_ref:
            (Path(settings.upload_dir) / evidence.file_ref).unlink(missing_ok=True)
        db.delete(evidence)

    db.commit()
    return _profile(db, user)


@router.post("/statements/{statement_id}/decline", response_model=ProfileOut)
def decline_statement(
    statement_id: str,
    data: DeclineIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Отказ раскрывать факт за компетенцией.

    Сама компетенция остаётся в профиле и открыта для подтверждения другим
    способом - отказ ничего не отнимает (§3.3, FR4.3).
    """
    statement = _get_statement(db, user, statement_id)
    record_decline(
        db, user, target_type=TARGET_STATEMENT, target_id=statement.id, reason=data.reason
    )
    db.commit()
    return _profile(db, user)


@router.delete("/statements/{statement_id}/decline", response_model=ProfileOut)
def restore_statement(
    statement_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    statement = _get_statement(db, user, statement_id)
    revoke_declines(db, user, target_type=TARGET_STATEMENT, target_id=statement.id)
    db.commit()
    return _profile(db, user)
