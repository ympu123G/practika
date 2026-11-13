from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STUDENTS_FILE = DATA_DIR / "students.json"
BACKUP_DIR = DATA_DIR / "backups"


class StudentError(Exception):
    pass


class BackupError(Exception):
    pass


def _load_students() -> List[Dict]:
    if not STUDENTS_FILE.is_file():
        return []
    try:
        text = STUDENTS_FILE.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError):
        return []


def _save_students(students: List[Dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STUDENTS_FILE.write_text(
        json.dumps(students, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_student(name: str, group: str, grade: float) -> Dict:
    if not name.strip():
        raise StudentError("ФИО не может быть пустым")
    if not group.strip():
        raise StudentError("Группа не может быть пустой")
    if not (0 <= grade <= 5):
        raise StudentError("Оценка должна быть от 0 до 5")
    students = _load_students()
    new_id = max((s.get("id", 0) for s in students), default=0) + 1
    student = {
        "id": new_id,
        "name": name.strip(),
        "group": group.strip(),
        "grade": round(grade, 2),
    }
    students.append(student)
    _save_students(students)
    return student


def list_students() -> List[Dict]:
    return _load_students()


def find_student(query: str) -> List[Dict]:
    students = _load_students()
    q = query.strip().lower()
    if not q:
        return students
    return [s for s in students if q in s["name"].lower() or q in s["group"].lower()]


def delete_student(student_id: int) -> bool:
    students = _load_students()
    new_list = [s for s in students if s["id"] != student_id]
    if len(new_list) == len(students):
        return False
    _save_students(new_list)
    return True


# ---------- резервное копирование ----------
def _stamp(now: dt.datetime) -> str:
    return now.strftime("%Y%m%d_%H%M%S_%f")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_backup() -> Path:
    if not STUDENTS_FILE.is_file():
        raise BackupError("Нет файла с данными для копирования")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    content = STUDENTS_FILE.read_bytes()
    manifest = {"students.json": _sha256(content)}
    target = BACKUP_DIR / f"backup_{_stamp(dt.datetime.now(dt.timezone.utc))}.zip"
    fd, tmp_name = tempfile.mkstemp(suffix=".zip", dir=BACKUP_DIR)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("students.json", content)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(str(tmp_path), str(target))
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise BackupError(f"Не удалось создать копию: {exc}") from exc
    return target


def list_backups() -> List[Path]:
    if not BACKUP_DIR.is_dir():
        return []
    return sorted(BACKUP_DIR.glob("backup_*.zip"))


def restore_backup(archive: Path) -> None:
    archive = Path(archive)
    if not archive.is_file():
        raise BackupError(f"Архив не найден: {archive}")
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                raise BackupError("В архиве нет манифеста")
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            for name, checksum in manifest.items():
                if name not in names:
                    raise BackupError(f"В архиве нет файла {name}")
                if _sha256(zf.read(name)) != checksum:
                    raise BackupError(f"Контрольная сумма не совпадает: {name}")
    except zipfile.BadZipFile as exc:
        raise BackupError("Файл не является ZIP-архивом") from exc

    if STUDENTS_FILE.is_file():
        safety = STUDENTS_FILE.with_suffix(".json.old")
        if safety.exists():
            safety.unlink()
        STUDENTS_FILE.rename(safety)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        (DATA_DIR / "students.json").write_bytes(zf.read("students.json"))


def _print_students(students: List[Dict]) -> None:
    if not students:
        print("Список студентов пуст.")
        return
    print(f"{'ID':<4} {'ФИО':<30} {'Группа':<12} {'Оценка':<6}")
    print("-" * 55)
    for s in students:
        print(f"{s['id']:<4} {s['name']:<30} {s['group']:<12} {s['grade']:<6}")


def menu() -> None:
    while True:
        print("\n" + "=" * 50)
        print(" student_manager — учёт студентов")
        print("=" * 50)
        print("1. Добавить студента")
        print("2. Показать всех студентов")
        print("3. Найти студента (по ФИО или группе)")
        print("4. Удалить студента по ID")
        print("5. Создать резервную копию")
        print("6. Показать список копий")
        print("7. Восстановить из копии")
        print("0. Выход")
        choice = input("Выберите пункт: ").strip()

        if choice == "1":
            try:
                name = input("ФИО: ").strip()
                group = input("Группа: ").strip()
                grade_str = input("Средняя оценка (0-5): ").strip()
                grade = float(grade_str)
                student = add_student(name, group, grade)
                print(f"Добавлен студент ID={student['id']}")
            except ValueError:
                print("Ошибка: оценка должна быть числом.")
            except StudentError as exc:
                print(f"Ошибка: {exc}")

        elif choice == "2":
            _print_students(list_students())

        elif choice == "3":
            query = input("Введите часть ФИО или группы: ").strip()
            _print_students(find_student(query))

        elif choice == "4":
            _print_students(list_students())
            raw = input("ID для удаления (Enter — отмена): ").strip()
            if not raw:
                continue
            try:
                sid = int(raw)
            except ValueError:
                print("Ошибка: ID должен быть числом.")
                continue
            if delete_student(sid):
                print(f"Студент ID={sid} удалён.")
            else:
                print(f"Студент с ID={sid} не найден.")

        elif choice == "5":
            try:
                path = create_backup()
                print(f"Копия создана: {path.name}")
            except BackupError as exc:
                print(f"Ошибка: {exc}")

        elif choice == "6":
            items = list_backups()
            if not items:
                print("Копий нет.")
            else:
                for p in items:
                    print(f"  {p.name}")

        elif choice == "7":
            items = list_backups()
            if not items:
                print("Копий нет — восстанавливать нечего.")
                continue
            print("Доступные копии:")
            for i, p in enumerate(items, 1):
                print(f"  {i}. {p.name}")
            raw = input(f"Номер копии (Enter = последняя): ").strip()
            if not raw:
                archive = items[-1]
            else:
                try:
                    idx = int(raw) - 1
                    if not (0 <= idx < len(items)):
                        print("Неверный номер.")
                        continue
                    archive = items[idx]
                except ValueError:
                    print("Введите число.")
                    continue
            try:
                restore_backup(archive)
                print(f"Восстановлено из: {archive.name}")
            except BackupError as exc:
                print(f"Ошибка: {exc}")

        elif choice == "0":
            print("До свидания.")
            break
        else:
            print("Неизвестный пункт.")


if __name__ == "__main__":
    if os.name == "nt":
        for s in ("stdout", "stderr"):
            st = getattr(sys, s)
            if hasattr(st, "reconfigure"):
                try:
                    st.reconfigure(encoding="utf-8")
                except Exception:
                    pass
    try:
        menu()
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")