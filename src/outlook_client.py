import datetime
import os
import re
import sys
import time

import win32com.client

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OUTLOOK_LOOKBACK_MINUTES, OUTLOOK_LOOKAHEAD_HOURS


def _naive(dt):
    """pywintypes/datetime -> naive локальный datetime.

    Если значение timezone-aware (напр. UTC при early-binding), сначала
    приводим к локальной зоне: 'replace(tzinfo=None)' без конвертации
    оставит UTC-время и сдвинет все встречи на величину смещения.
    """
    if getattr(dt, "tzinfo", None) is not None:
        try:
            dt = dt.astimezone()
        except Exception:
            pass
    if hasattr(dt, "replace"):
        return dt.replace(tzinfo=None)
    return datetime.datetime.fromtimestamp(int(dt))


def _validate_candidates(cands, search_start, search_end):
    """Фильтрует кандидатов: отменённые, нереальные времена. Возвращает (valid, stats)."""
    valid, future, ended, canceled = [], 0, 0, 0
    for item in cands:
        try:
            # Отменённые: MeetingStatus=5 (olMeetingCanceled) или префикс в теме
            try:
                status = getattr(item, "MeetingStatus", 0) or 0
            except Exception:
                status = 0
            try:
                subj = (item.Subject or "").strip().lower()
            except Exception:
                subj = ""
            if status == 5 or subj.startswith(
                ("canceled:", "cancelled:", "отменено:", "отменена:", "отменён:", "отмена:")
            ):
                canceled += 1
                continue
            st_naive = _naive(item.Start)
            if st_naive > search_end:
                future += 1  # ложное срабатывание из будущего (misparse даты)
                continue
            if st_naive >= search_start:
                valid.append(item)
                continue
            if _naive(item.End) >= search_start:
                valid.append(item)  # идёт прямо сейчас
            else:
                ended += 1
        except Exception:
            ended += 1
    return valid, {"future": future, "ended": ended, "canceled": canceled}


def _to_utc_iso(dt):
    """Локальный naive datetime -> ISO 8601 UTC (DASL-фильтры не зависят от локали)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.mktime(dt.timetuple())))


# Строки-разделители таблиц/подчёркивания из ASCII-графики: "---", "___",
# "+----+----+", "***", "..." и т.п. (3+ символов, ничего кроме этих знаков).
_TABLE_BORDER_RE = re.compile(r"^[\s\-=_+*.~]{3,}$")


def clean_meeting_body(text):
    """Нормализует описание встречи из Outlook для заметки.

    AppointmentItem.Body — plain text: таблицы из rich text разворачиваются
    в колонки, выровненные цепочками пробелов, плюс CRLF и неразрывные
    пробелы. Из-за этого текст в заметке «плывёт». Здесь: убираем
    выравнивающие пробелы, строки-разделители таблиц и лишние пустые строки.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\t", " ")

    lines = []
    for raw in text.split("\n"):
        # Цепочки 2+ пробелов — это выравнивание колонок таблицы: сжимаем.
        line = re.sub(r" {2,}", " ", raw).strip()
        if _TABLE_BORDER_RE.match(raw):
            continue
        lines.append(line)

    # Максимум одна пустая строка подряд, без пустот по краям.
    out = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)

def _query_current_meeting(items, now_local, log=None):
    """Отдельный запрос идущей сейчас встречи: [Start] <= now < [End].

    Общий фильтр по окну поиска может не вернуть вхождение, которое уже
    началось (особенности Restrict/IncludeRecurrences для серий), поэтому
    текущая встреча запрашивается явно. Возвращает список активных элементов.
    """
    log = log or (lambda *a, **k: None)
    val_utc = _to_utc_iso(now_local)
    val_local = now_local.strftime("%Y-%m-%d %H:%M:%S")
    variants = [
        (
            "@SQL=\"urn:schemas:calendar:dtstart\" <= '{}' AND "
            "\"urn:schemas:calendar:dtend\" > '{}'".format(val_utc, val_utc),
            "DASL/UTC",
        ),
        (
            "@SQL=\"urn:schemas:calendar:dtstart\" <= '{}' AND "
            "\"urn:schemas:calendar:dtend\" > '{}'".format(val_local, val_local),
            "DASL/local",
        ),
    ]
    for fmt in ("%d.%m.%Y %H:%M", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M"):
        val = now_local.strftime(fmt)
        variants.append((f"[Start] <= '{val}' AND [End] > '{val}'", f"Jet/{fmt}"))

    for restriction, label in variants:
        try:
            res = items.Restrict(restriction)
            cands = []
            for item in res:
                cands.append(item)
                if len(cands) >= 50:
                    break
            if not cands:
                continue
            active = []
            for item in cands:
                try:
                    status = getattr(item, "MeetingStatus", 0) or 0
                    subj = (item.Subject or "").strip().lower()
                    if status == 5 or subj.startswith(
                        ("canceled:", "cancelled:", "отменено:", "отменена:", "отменён:", "отмена:")
                    ):
                        continue
                    if _naive(item.Start) <= now_local < _naive(item.End):
                        active.append(item)
                except Exception:
                    continue
            log(f"[Outlook] Current query ({label}): raw={len(cands)}, active={len(active)}")
            if active:
                return active
        except Exception as e:
            log(f"[Outlook Warning] Current query ({label}) failed: {e}")
    return []


def get_current_or_next_meeting_details(log_callback=None):
    """
    Ищет текущую или ближайшую встречу в Outlook (включая повторяющиеся серии).
    Приоритет: встреча, которая уже началась и ещё не закончена ([Start] <= now < [End])
    — запрашивается отдельным Restrict, т.к. общий фильтр по окну может её терять.
    Порядок попыток: текущая -> DASL/UTC (locale-независимый) -> Jet Restrict -> обратный проход.
    """
    log = log_callback or print
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)  # 9 = olFolderCalendar

        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True

        now_local = datetime.datetime.now()

        # Окно поиска: начавшиеся не ранее N минут назад (идущие сейчас ловятся
        # dtend-условием независимо от давности старта) или ближайшие N часов
        search_start = now_local - datetime.timedelta(minutes=OUTLOOK_LOOKBACK_MINUTES)
        search_end = now_local + datetime.timedelta(hours=OUTLOOK_LOOKAHEAD_HOURS)

        log(f"[Outlook] Search window: {search_start:%Y-%m-%d %H:%M} .. {search_end:%Y-%m-%d %H:%M}")

        # Сбор кандидатов из нескольких источников с объединением (dedupe).
        # На этой сборке Outlook DASL/UTC возвращает пусто, а DASL/local с
        # условиями на двух свойствах (dtstart+dtend) молча теряет часть
        # вхождений (проверено зондом: нашёл 4 из 5, ближайшая пропала).
        # Поэтому объединяем результаты DASL и всех Jet-форматов: мусор
        # нераспарсенных форматов отбраковывается финальной валидацией по окну.
        collected = {}

        def _collect(source_label, restriction):
            try:
                res = items.Restrict(restriction)
                added = 0
                for item in res:
                    try:
                        key = (str(item.Subject or ""), str(_naive(item.Start)), str(_naive(item.End)))
                    except Exception:
                        key = (f"opaque-{len(collected)}-{added}",)
                    if key not in collected:
                        collected[key] = item
                        added += 1
                    if len(collected) >= 200:
                        break
                log(f"[Outlook] Restrict ({source_label}): +{added}, total unique={len(collected)}")
            except Exception as e:
                log(f"[Outlook Warning] Restrict ({source_label}) failed: {e}")

        # DASL: перекрытие окна (dtstart < end AND dtend > start) — ловит и
        # идущие сейчас, начавшиеся до search_start. UTC и локальный варианты.
        for dasl_label, val_end, val_start in (
            ("DASL/UTC", _to_utc_iso(search_end), _to_utc_iso(search_start)),
            ("DASL/local", search_end.strftime("%Y-%m-%d %H:%M:%S"), search_start.strftime("%Y-%m-%d %H:%M:%S")),
        ):
            _collect(
                dasl_label,
                '@SQL="urn:schemas:calendar:dtstart" < \'{}\' AND '
                '"urn:schemas:calendar:dtend" > \'{}\''.format(val_end, val_start),
            )

        # Jet: перебор региональных форматов, start-in-window. На этой сборке
        # даёт полный корректный набор (проверено зондом: 5 из 5).
        for fmt in ("%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
            _collect(
                f"Jet/{fmt}",
                f"[Start] >= '{search_start.strftime(fmt)}' AND [Start] <= '{search_end.strftime(fmt)}'",
            )

        matched_items = list(collected.values())

        # Попытка 3 (если Restrict ничего не дал): обратный проход с конца
        # отсортированной коллекции. Обрабатывает только разовые встречи.
        if not matched_items:
            try:
                items.IncludeRecurrences = False  # конечная коллекция для обратного прохода
                total = items.Count
            except Exception:
                total = 0

            scanned = 0
            for idx in range(total, 0, -1):
                if scanned >= 500:
                    break
                scanned += 1
                try:
                    item = items.Item(idx)
                    if getattr(item, "IsRecurring", False):
                        # Мастер серии: Start = первое вхождение (обычно в прошлом).
                        continue
                    st_naive = _naive(item.Start)
                    if st_naive < search_start:
                        break  # дальше вглубь — только более старые встречи
                    if st_naive <= search_end:
                        matched_items.append(item)
                except Exception:
                    continue
            log(f"[Outlook] Backward scan: {len(matched_items)} candidates")
            # Возвращаем режим разворачивания серий — он нужен current-запросу ниже.
            try:
                items.IncludeRecurrences = True
            except Exception:
                pass

        # Финальная валидация + диагностика причин отбраковки
        if matched_items:
            valid, stats = _validate_candidates(matched_items, search_start, search_end)
            log(f"[Outlook] Validation: kept={len(valid)}, future={stats['future']}, "
                f"ended_past={stats['ended']}, canceled={stats['canceled']}")
            matched_items = valid
            if matched_items:
                try:
                    log("[Outlook] Candidates start: " + ", ".join(
                        _naive(i.Start).strftime("%Y-%m-%d %H:%M") for i in matched_items[:5]))
                except Exception:
                    pass

        # Приоритет: идущая сейчас встреча (уже началась и ещё не закончена).
        # Общий фильтр по окну может терять активное вхождение — запрашиваем
        # её отдельно; если найдена, она заменяет всех кандидатов из окна.
        current_items = _query_current_meeting(items, now_local, log)
        if current_items:
            log(f"[Outlook] Current meeting overrides candidates: {len(current_items)} active")
            matched_items = current_items

        if not matched_items:
            log(f"[Outlook] No meetings found in window {search_start:%Y-%m-%d %H:%M} .. {search_end:%Y-%m-%d %H:%M}")
            return None

        # Выбираем встречу: активная (Start <= сейчас <= End) приоритетнее ближайшей.
        # Из активных — начавшаяся последней (актуальный слот); иначе ближайшая по времени.
        active_items = []
        for item in matched_items:
            try:
                if _naive(item.Start) <= now_local <= _naive(item.End):
                    active_items.append(item)
            except Exception:
                continue

        if active_items:
            log(f"[Outlook] Active right now: {len(active_items)}")
            best_item = max(active_items, key=lambda it: _naive(it.Start))
        else:
            best_item = min(
                matched_items,
                key=lambda it: abs((_naive(it.Start) - now_local).total_seconds()),
            )

        if not best_item:
            return None

        # Извлечение участников
        attendees = []
        try:
            for rec in best_item.Recipients:
                attendees.append(rec.Name)
        except Exception:
            pass

        # Извлечение организатора
        organizer = ""
        try:
            organizer = best_item.Organizer
        except Exception:
            pass

        # Извлечение описания встречи (с нормализацией таблиц/пробелов)
        body = ""
        try:
            body = clean_meeting_body(best_item.Body)
        except Exception:
            try:
                body = (best_item.Body or "").strip()
            except Exception:
                pass

        return {
            "subject": best_item.Subject,
            "organizer": organizer,
            "attendees": attendees,
            "body": body,
            # Локальное naive-время: str(Start) у pywintypes даёт UTC и в UI
            # отображается со сдвигом относительно календаря Outlook.
            "start": str(_naive(best_item.Start)),
        }

    except Exception as e:
        log(f"[Outlook Error] {e}")
        return None
