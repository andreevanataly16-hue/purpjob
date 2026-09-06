"""Модуль 9: экспорт профессионального профиля.

Документ, который можно унести с собой. Всё, что накопили модули 2-8, имеет
смысл только если оно работает за пределами платформы, куда рекрутеру пока
незачем заходить.

Жёсткое ограничение этого модуля: **он никуда ничего не отправляет.** Ни
почтой, ни на job-борды, ни в ATS. Единственное, что он производит, - файл,
который кандидат скачивает сам. Это не «пока не сделали», а требование: в
модели данных нет поля получателя, и добавлять его нельзя даже про запас.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExportRequest, Statement, User
from app.resume import (
    FONT_MISSING_RU,
    FontMissing,
    ResumeData,
    build_pdf,
    pick_projects,
    pick_skills,
    register_font,
)
from app.routers.auth import current_user
from app.routers.profile import parse_id
from app.routers.trust import LEGEND_RU
from app.schemas_export import ExportOptionsIn, ExportPreviewOut

router = APIRouter(prefix="/api/export", tags=["export"])

PDF = "pdf"
FORMATS = (PDF,)

NOTE_RU = (
    "Файл собирается прямо сейчас из текущего состояния профиля и просто скачивается к вам. "
    "PurpJob никому его не отправляет и не может узнать, кто и когда его открыл."
)

NO_ROLE_RU = "Сначала выберите целевую роль — без неё резюме собирать не из чего."


def _collect(db: Session, user: User, include_contacts: bool) -> ResumeData:
    """Собирает данные документа из живого состояния профиля (FR2.3).

    Никаких сохранённых копий: каждый экспорт заново читает то, что есть
    сейчас. Замороженный снимок здесь был бы не бережливостью, а способом
    выдать вчерашний профиль за сегодняшний.
    """
    from app.routers.prof import _payload
    from app.routers.trust import _state

    prof = _payload(db, user)
    if not prof.snapshots:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_ROLE_RU)

    snapshot = prof.snapshots[0]
    trust = _state(db, user)

    statements = list(
        db.scalars(select(Statement).where(Statement.user_id == user.id).order_by(Statement.id))
    )
    statuses: dict[str, str] = {}
    for component in snapshot.components:
        for statement_id in component.statement_ids:
            statuses[str(parse_id("stmt", statement_id))] = component.status

    return ResumeData(
        # Имени в профиле нет - его никто не собирает. Шапка строится вокруг
        # целевой роли, а не вокруг придуманного из адреса имени (см. resume.py).
        role_ru=f"{snapshot.level} — {snapshot.segment}",
        segment_ru=f"Профессиональный профиль PurpJob · эталон {snapshot.reference_profile_id}",
        prof_score=snapshot.overall_score,
        trust_score=trust.overall_score,
        trust_measured=trust.overall_measured,
        # Легенда берётся у модуля 6 как есть: это фиксированный абзац, а не
        # место для второй, «своей» формулировки (FR3.2).
        trust_legend_ru=LEGEND_RU,
        skills=pick_skills(snapshot.components),
        projects=pick_projects(statements, statuses),
        contact_email=user.email if include_contacts else None,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/preview", response_model=ExportPreviewOut)
def preview(
    include_contacts: bool = True,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ExportPreviewOut:
    """Что окажется в файле - до того, как файл создан (§6 FRD).

    Экспорт не должен быть сюрпризом: человек отправляет этот документ людям,
    и он вправе увидеть содержимое заранее.
    """
    data = _collect(db, user, include_contacts)
    return ExportPreviewOut.model_validate(
        {
            "format": PDF,
            "note_ru": NOTE_RU,
            "font_available": register_font(),
            "font_hint_ru": FONT_MISSING_RU,
            "role_ru": data.role_ru,
            "segment_ru": data.segment_ru,
            "prof_score": data.prof_score,
            "trust_score": data.trust_score,
            "trust_measured": data.trust_measured,
            "trust_legend_ru": data.trust_legend_ru,
            "skills": [{"name_ru": name, "status_ru": status} for name, status in data.skills],
            "projects": [{"name_ru": name, "text": text} for name, text in data.projects],
            "contact_email": data.contact_email,
        }
    )


@router.post("/pdf")
def export_pdf(
    options: ExportOptionsIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Собирает PDF и отдаёт его кандидату. Больше он никуда не идёт (FR4.1).

    Ответ - сами байты файла. Ни адресата, ни очереди отправки, ни хранилища
    готовых документов в этом модуле нет.
    """
    if options.format not in FORMATS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"В этой версии есть один формат: {', '.join(FORMATS)}.",
        )

    data = _collect(db, user, options.include_contacts)
    try:
        content = build_pdf(data)
    except FontMissing as missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, FONT_MISSING_RU
        ) from missing

    # Запись только для самого кандидата: по ней он потом поймёт, каким был
    # профиль в момент выгрузки. Ни получателя, ни статуса доставки здесь нет
    # и быть не может (§4.1).
    db.add(
        ExportRequest(
            user_id=user.id,
            format=PDF,
            include_contacts=options.include_contacts,
            prof_segment=data.segment_ru,
            prof_level=data.role_ru,
            trust_score_version=data.trust_score,
        )
    )
    db.commit()

    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="purpjob-profile.pdf"'},
    )
