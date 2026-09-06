"""Шаблон резюме и правила отбора содержимого (модуль 9).

Один файл на весь экспорт - и это осознанно (§7 FRD): правило «что попадает в
документ» размазанное по коду означает, что через полгода никто не сможет
ответить, почему в PDF попал именно этот проект.

Что здесь важнее удобства:

* **Ничего не сочиняется.** Документ собирается из того, что уже есть в
  профиле. Ни одного поля, которое кандидат должен дописать руками.
* **Из документа ничего не утекает.** Подтверждения под NDA и материалы,
  помеченные как закрытые, в текст не попадают вообще - иначе экспорт стал бы
  дырой в том самом обещании, ради которого делался модуль 5.
* **Никакой слежки.** В документе нет ни уникальных ссылок, ни счётчиков, ни
  чего-либо, по чему можно узнать, когда и кто его открыл.

Про имя кандидата. FRD ожидает в шапке имя, но профиль его нигде не собирает:
модуль 1 спрашивает только почту. Выдумывать имя из адреса нельзя, поэтому
шапка построена вокруг целевой роли, а имя появится здесь, когда его начнёт
собирать профиль. Это отмечено в README как пробел, а не как решение.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.enrichment import (
    DECLINED,
    TYPE_BLIND_WITNESS,
    TYPE_FILE,
    TYPE_LINK,
    TYPE_MIRROR_TASK,
    TYPE_PROBE_ANSWER,
)

# --- сколько чего показываем (§2.2: один вариант длины) -------------------
#
# Правило отбора должно быть названным и одним. «Несколько ключевых проектов»
# без определения - это способ получить разный документ на одних и тех же
# данных.

KEY_PROJECTS_SHOWN = 3
SKILLS_SHOWN = 10
PROJECT_TEXT_LIMIT = 320

STATUS_RU = {
    "strong": "подтверждено независимыми источниками",
    "medium": "подтверждено",
    "limited": "заявлено, подтверждено частично",
}

# Типы доказательств, которые не покидают платформу ни при каких условиях:
# это подтверждения закрытого опыта, и весь их смысл был в том, что содержание
# проекта не раскрывается (модуль 5).
NDA_BOUND_TYPES = (TYPE_BLIND_WITNESS, TYPE_MIRROR_TASK)

# Ответы на вопросы Contextual Probe в резюме не идут. Это не про качество
# ответов: такой текст - стенограмма разговора, и в нём вперемешку слова
# кандидата и наши собственные формулировки, включая уточняющий вопрос. В
# резюме должен быть рассказ человека о своей работе, а не наша беседа с ним.
NOT_FOR_RESUME_TYPES = NDA_BOUND_TYPES + (TYPE_PROBE_ANSWER,)


@dataclass(frozen=True)
class ResumeData:
    """Всё, что попадает в документ. Собирается роутером, читается шаблоном."""

    role_ru: str
    segment_ru: str
    prof_score: int
    trust_score: int
    # Балл доверия может быть ещё не рассчитан. В резюме это должно быть
    # написано словами: «0 из 100» читается как приговор, которого никто не
    # выносил.
    trust_measured: bool
    trust_legend_ru: str
    skills: list[tuple[str, str]]
    projects: list[tuple[str, str]]
    contact_email: str | None
    generated_at: datetime


# --- шрифт ----------------------------------------------------------------
#
# Кириллица требует встроенного TTF: базовые шрифты PDF её не содержат.
# Свободный шрифт в репозитории - самый предсказуемый вариант, но класть в
# репозиторий системный проприетарный шрифт нельзя. Поэтому порядок поиска
# такой: сначала свой, потом системные, и внятная ошибка, если ничего нет.

FONT_NAME = "PurpJobSans"
BUNDLED_FONT = Path(__file__).parent / "assets" / "fonts" / "DejaVuSans.ttf"

SYSTEM_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)

FONT_MISSING_RU = (
    "Не нашли шрифт с кириллицей для PDF. Положите свободный DejaVuSans.ttf в "
    "backend/app/assets/fonts/ — и экспорт заработает."
)


class FontMissing(RuntimeError):
    """Шрифта с кириллицей нет - собирать документ нечем."""


def find_font() -> Path | None:
    if BUNDLED_FONT.exists():
        return BUNDLED_FONT
    for candidate in SYSTEM_FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def register_font() -> bool:
    """Регистрирует шрифт один раз на процесс. False - шрифта нет вообще."""
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return True
    found = find_font()
    if found is None:
        return False
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(found)))
    return True


# --- отбор содержимого (FR2.2) -------------------------------------------


def pick_skills(components: list) -> list[tuple[str, str]]:
    """Компетенции по весу эталона, от самых важных.

    Неподтверждённые не показываем: резюме - это про подтверждённый опыт, а не
    список того, чего не хватает. Белые пятна кандидат видит у себя в профиле,
    и они его дело, а не читателя документа.
    """
    shown = [item for item in components if item.status in STATUS_RU]
    shown.sort(key=lambda item: (-item.weight, item.name_ru))
    return [(item.name_ru, STATUS_RU[item.status]) for item in shown[:SKILLS_SHOWN]]


def _open_texts(statement) -> list[str]:
    """Открытые описания компетенции, от самого развёрнутого.

    Закрытые материалы сюда не попадают ни при каких условиях: подтверждение
    под NDA доказывает опыт, но не разрешает его пересказывать. Без этого
    экспорт стал бы дырой в обещании модуля 5.
    """
    texts = [
        (item.raw_text or "").strip()
        for item in statement.evidence
        if item.status != DECLINED
        and not item.nda
        and item.type not in NOT_FOR_RESUME_TYPES
        and item.raw_text
    ]
    return sorted({text for text in texts if text}, key=len, reverse=True)


def _shorten(text: str) -> str:
    if len(text) <= PROJECT_TEXT_LIMIT:
        return text
    return text[:PROJECT_TEXT_LIMIT].rsplit(" ", 1)[0] + "…"


def _text_of(statement) -> str:
    """Самое развёрнутое открытое описание компетенции."""
    texts = _open_texts(statement)
    return _shorten(texts[0]) if texts else ""


def _artifact_count(statement) -> int:
    return sum(
        1
        for item in statement.evidence
        if item.status != DECLINED and item.type in (TYPE_LINK, TYPE_FILE)
    )


def pick_projects(statements: list, statuses: dict[str, str]) -> list[tuple[str, str]]:
    """Правило отбора проектов, названное явно (FR2.2).

    Сначала самые подтверждённые, среди равных - те, за которыми больше
    артефактов, затем - те, что описаны подробнее. Берём не больше трёх:
    документ должен читаться, а не пересказывать профиль целиком.
    """
    rank = {"strong": 0, "medium": 1, "limited": 2}

    candidates = [
        item
        for item in statements
        if statuses.get(str(item.id)) in rank and _open_texts(item)
    ]
    candidates.sort(
        key=lambda item: (
            rank[statuses[str(item.id)]],
            -_artifact_count(item),
            -len(_open_texts(item)[0]),
        )
    )

    # Один и тот же кусок рассказа обычно подтверждает сразу несколько
    # компетенций. В профиле это нормально, а в резюме три пункта с
    # одинаковым текстом выглядят как ошибка вёрстки - и читать их незачем.
    picked: list[tuple[str, str]] = []
    used: set[str] = set()
    for item in candidates:
        text = next((value for value in _open_texts(item) if value not in used), None)
        if text is None:
            continue
        used.add(text)
        picked.append((item.skill_name_ru, _shorten(text)))
        if len(picked) == KEY_PROJECTS_SHOWN:
            break
    return picked


# --- вёрстка --------------------------------------------------------------

LEFT = 20 * mm
RIGHT = 20 * mm
TOP = 20 * mm
BOTTOM = 18 * mm


class _Page:
    """Простая колонка текста с переносом строк и разрывом страниц."""

    def __init__(self, pdf: canvas.Canvas):
        self.pdf = pdf
        self.width, self.height = A4
        self.y = self.height - TOP

    def _space(self, needed: float) -> None:
        if self.y - needed < BOTTOM:
            self.pdf.showPage()
            self.y = self.height - TOP

    def gap(self, amount: float) -> None:
        self.y -= amount

    def line(self, text: str, size: float, *, color=(0.1, 0.1, 0.12), leading=1.35) -> None:
        self._space(size * leading)
        self.pdf.setFont(FONT_NAME, size)
        self.pdf.setFillColorRGB(*color)
        self.pdf.drawString(LEFT, self.y, text)
        self.y -= size * leading

    def paragraph(self, text: str, size: float, *, color=(0.25, 0.25, 0.3)) -> None:
        limit = self.width - LEFT - RIGHT
        words = text.split()
        current = ""
        for word in words:
            probe = f"{current} {word}".strip()
            if pdfmetrics.stringWidth(probe, FONT_NAME, size) <= limit:
                current = probe
                continue
            self.line(current, size, color=color)
            current = word
        if current:
            self.line(current, size, color=color)

    def rule(self) -> None:
        self._space(6)
        self.pdf.setStrokeColorRGB(0.85, 0.85, 0.88)
        self.pdf.line(LEFT, self.y, self.width - RIGHT, self.y)
        self.y -= 6


def build_pdf(data: ResumeData) -> bytes:
    """Собирает документ. Ничего не сохраняет и никуда не отправляет.

    Возвращаются просто байты: у этого модуля нет ни хранилища готовых файлов,
    ни адресатов, ни очереди отправки - и это требование, а не упущение.
    """
    from io import BytesIO

    # Шрифт регистрируется здесь же, а не «где-то раньше по коду»: сборка
    # документа не должна зависеть от того, вызвал ли кто-то до неё нужную
    # функцию. Иначе первый же вызов из другого места молча падает на
    # внутренностях reportlab вместо понятного сообщения.
    if not register_font():
        raise FontMissing(FONT_MISSING_RU)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Профессиональный профиль PurpJob")
    # Ни автора, ни идентификаторов: документ не должен нести следов,
    # по которым его можно связать с сеансом или отследить (FR4.3).
    pdf.setAuthor("")
    pdf.setSubject("")

    page = _Page(pdf)

    page.line(data.role_ru, 20)
    page.line(data.segment_ru, 10.5, color=(0.4, 0.4, 0.46))
    page.gap(10)
    page.rule()
    page.gap(6)

    page.line(f"PROF.индекс: {data.prof_score} из 100", 12)
    page.paragraph(
        "Насколько подтверждённый опыт закрывает требования эталона роли. Это не оценка знаний: "
        "показатель растёт от доказательств, а не от самооценки.",
        9,
    )
    page.gap(6)

    page.line(
        f"Trust Score: {data.trust_score} из 100"
        if data.trust_measured
        else "Trust Score: пока не рассчитан",
        12,
    )
    page.paragraph(data.trust_legend_ru, 9)
    page.gap(10)

    if data.skills:
        page.rule()
        page.gap(4)
        page.line("Компетенции", 13)
        page.gap(3)
        for name, status in data.skills:
            page.line(f"• {name} — {status}", 10)
        page.gap(8)

    if data.projects:
        page.rule()
        page.gap(4)
        page.line("Из опыта", 13)
        page.gap(3)
        for name, text in data.projects:
            page.line(name, 11)
            page.paragraph(text, 9.5)
            page.gap(5)

    if data.contact_email:
        page.rule()
        page.gap(4)
        page.line("Контакты", 13)
        page.line(data.contact_email, 10)
        page.gap(6)

    page.gap(6)
    page.paragraph(
        f"Документ собран автоматически из профиля PurpJob "
        f"{data.generated_at.astimezone(timezone.utc).strftime('%d.%m.%Y')}. "
        "Чтобы его прочитать, PurpJob не нужен.",
        8,
        color=(0.55, 0.55, 0.6),
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
