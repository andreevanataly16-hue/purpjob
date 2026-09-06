"""Границы файлового хранилища (подготовка к Candidate Pilot).

Файлы кандидата лежат на диске рядом с кодом. Для закрытого пилота это
допустимо, но допустимо ровно при условиях, которые здесь и проверяются: имя
файла от человека нигде не становится путём, чужой файл не отдаётся, а
заявленный тип содержимого ничего не доказывает.

Это не проверка объектного хранилища и не подготовка к нему. Это проверка
того, что нынешнее хранилище не хуже, чем о нём написано.
"""

from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.models import Evidence

PROFILE = "/api/profile"
FILE = "/api/profile/evidence/file"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def upload(client, name="diploma.png", content=PNG, content_type="image/png"):
    return client.post(FILE, files={"file": (name, content, content_type)})


def stored_refs():
    with SessionLocal() as db:
        return [item.file_ref for item in db.query(Evidence).all() if item.file_ref]


def uploads_root() -> Path:
    return Path(settings.upload_dir).resolve()


# --- имя файла не становится путём ---------------------------------------


def test_a_traversing_filename_does_not_escape_the_upload_folder(signed_client):
    """Имя от человека - подпись, а не адрес на диске.

    Классическая дыра: сохранить файл под присланным именем и получить запись
    куда угодно. Здесь имя вообще не участвует в пути - только расширение, и
    только из белого списка.
    """
    response = upload(signed_client, name="../../../../evil.png")

    assert response.status_code == 201
    for ref in stored_refs():
        resolved = (uploads_root() / ref).resolve()
        assert resolved.is_relative_to(uploads_root())
        assert ".." not in ref


def test_the_stored_name_is_generated_not_taken_from_the_request(signed_client):
    upload(signed_client, name="diploma.png")
    ref = stored_refs()[0]

    # Ссылка - идентификатор кандидата и случайное имя, ничего от человека.
    owner, name = ref.split("/")
    assert owner.isdigit()
    assert name.endswith(".png")
    assert "diploma" not in name
    assert len(Path(name).stem) == 32


def test_a_windows_style_path_in_the_name_is_also_ignored(signed_client):
    """Разделитель бывает и обратным - на Windows это тот же приём."""
    assert upload(signed_client, name=r"C:\Windows\System32\evil.png").status_code == 201
    assert all("\\" not in ref for ref in stored_refs())


def test_a_name_that_is_only_a_dot_extension_has_no_extension_at_all(signed_client):
    """«.png» - это имя скрытого файла, а не расширение, и разбор это знает.

    Отказ здесь правильный: продукт не должен додумывать за человека, что он
    имел в виду, когда прислал файл без расширения.
    """
    assert upload(signed_client, name=".png").status_code == 400


# --- заявленный тип ничего не доказывает ---------------------------------


def test_the_declared_content_type_is_not_believed(signed_client):
    """Заголовок присылает клиент, значит он ничего не подтверждает.

    Расширение .exe с заявленным image/png должно быть отклонено именно по
    расширению - а если бы решал заявленный тип, файл бы прошёл.
    """
    response = upload(signed_client, name="payload.exe", content_type="image/png")

    assert response.status_code == 400
    assert stored_refs() == []


def test_an_allowed_extension_with_foreign_content_is_still_only_an_attachment(
    signed_client,
):
    """Внутри .png может лежать что угодно - и это нормально, пока файл не
    исполняется и не открывается как страница."""
    upload(signed_client, name="page.png", content=b"<html><script>alert(1)</script>")

    evidence_id = signed_client.get(PROFILE).json()["evidence"][0]["id"]
    response = signed_client.get(f"/api/profile/evidence/{evidence_id}/file")

    assert response.status_code == 200
    # Отдаётся вложением, а не страницей: браузер не станет его исполнять.
    assert response.headers["content-disposition"].startswith("attachment")
    assert "text/html" not in response.headers["content-type"]


def test_a_script_extension_is_refused(signed_client):
    for name in ("run.sh", "run.bat", "app.py", "page.html", "lib.dll"):
        assert upload(signed_client, name=name).status_code == 400


def test_a_double_extension_is_judged_by_the_last_one(signed_client):
    """«отчёт.png.exe» - это .exe, и решать должно последнее расширение."""
    assert upload(signed_client, name="отчёт.png.exe").status_code == 400
    assert upload(signed_client, name="отчёт.exe.png").status_code == 201


# --- чужой файл ----------------------------------------------------------


def test_another_candidate_cannot_download_the_file(signed_client, client):
    """Ссылка на файл не должна работать у того, кому файл не принадлежит."""
    upload(signed_client)
    evidence_id = signed_client.get(PROFILE).json()["evidence"][0]["id"]
    signed_client.post("/api/auth/logout")

    client.post(
        "/api/auth/register",
        json={"email": "someone@example.com", "password": "verysecret123"},
    )

    assert client.get(f"/api/profile/evidence/{evidence_id}/file").status_code == 404


def test_the_file_is_not_reachable_without_signing_in(client, signed_client):
    upload(signed_client)
    evidence_id = signed_client.get(PROFILE).json()["evidence"][0]["id"]
    signed_client.post("/api/auth/logout")

    assert signed_client.get(f"/api/profile/evidence/{evidence_id}/file").status_code == 401


def test_the_client_never_names_the_file_it_wants(signed_client):
    """Скачивание адресуется идентификатором доказательства, а не путём.

    Пока в запросе нет пути, обходить нечего: проверка владения стоит до того,
    как путь вообще появится.
    """
    upload(signed_client)
    evidence_id = signed_client.get(PROFILE).json()["evidence"][0]["id"]

    for attempt in ("../../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "1/../2"):
        assert signed_client.get(
            f"/api/profile/evidence/{attempt}/file"
        ).status_code in (404, 422)

    assert signed_client.get(f"/api/profile/evidence/{evidence_id}/file").status_code == 200


# --- где файлы лежат ------------------------------------------------------


def test_every_file_lands_under_the_upload_folder_and_nowhere_else(signed_client):
    # Папка загрузок общая на прогон, поэтому смотрим на разницу, а не на
    # общее число файлов: иначе тест зависел бы от порядка тестов.
    before = {path for path in uploads_root().rglob("*") if path.is_file()}

    upload(signed_client, name="a.png")
    upload(signed_client, name="b.pdf", content=b"%PDF-1.4 " + b"0" * 50)

    written = {path for path in uploads_root().rglob("*") if path.is_file()} - before
    assert len(written) == 2
    assert all(path.resolve().is_relative_to(uploads_root()) for path in written)


def test_files_of_different_candidates_live_apart(signed_client, client):
    upload(signed_client)
    signed_client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "someone@example.com", "password": "verysecret123"},
    )
    upload(client)

    owners = {ref.split("/")[0] for ref in stored_refs()}
    assert len(owners) == 2
