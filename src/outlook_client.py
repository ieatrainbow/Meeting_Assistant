import datetime
import os
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


def get_current_or_next_meeting_details(log_callback=None):
    """
    Ищет текущую или ближайшую встречу в Outlook (включая повторяющиеся серии).
    Порядок попыток: DASL/UTC (locale-независимый) -> Jet Restrict -> обратный проход.
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

        matched_items = []

        # Попытка 1: DASL — не зависит от региональных форматов даты,
        # корректно разворачивает повторяющиеся встречи (Sort + IncludeRecurrences).
        # Пробуем UTC ('...Z') и локальный ISO: поведение зависит от версии Outlook.
        for dasl_label, val_end, val_start in (
            ("UTC", _to_utc_iso(search_end), _to_utc_iso(search_start)),
            ("local", search_end.strftime("%Y-%m-%d %H:%M:%S"), search_start.strftime("%Y-%m-%d %H:%M:%S")),
        ):
            try:
                restriction = (
                    '@SQL="urn:schemas:calendar:dtstart" < \'{}\' AND '
                    '"urn:schemas:calendar:dtend" > \'{}\''.format(val_end, val_start)
                )
                res = items.Restrict(restriction)
                cands = []
                for item in res:
                    cands.append(item)
                    if len(cands) >= 50:
                        break
                log(f"[Outlook] DASL filter ({dasl_label}): {len(cands)} candidates")
                if cands:
                    valid, _st = _validate_candidates(cands, search_start, search_end)
                    if valid:
                        matched_items = valid
                        break
                    log("[Outlook Warning] DASL candidates failed validation")
            except Exception as e:
                log(f"[Outlook Warning] DASL filter ({dasl_label}) failed: {e}")

        # Попытка 2: Jet Restrict с перебором региональных форматов даты.
        # Формат принимается, только если валидация оставила >= 1 кандидата —
        # защита от неверного парсинга даты в не-US локалях.
        if not matched_items:
            date_formats = ["%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"]
            for fmt in date_formats:
                try:
                    start_str = search_start.strftime(fmt)
                    end_str = search_end.strftime(fmt)
                    restriction = f"[Start] >= '{start_str}' AND [Start] <= '{end_str}'"
                    res = items.Restrict(restriction)
                    if res.Count <= 0:
                        continue
                    cands = []
                    for item in res:
                        cands.append(item)
                        if len(cands) >= 200:
                            break
                    try:
                        log(f"[Outlook] Jet sample start: {cands[0].Start!r}")
                    except Exception:
                        pass
                    valid, stats = _validate_candidates(cands, search_start, search_end)
                    log(f"[Outlook] Jet filter ({fmt}): raw={len(cands)}, valid={len(valid)} "
                        f"(future={stats['future']}, ended_past={stats['ended']})")
                    if valid:
                        matched_items = valid
                        break
                except Exception:
                    continue

        # Попытка 3: обратный проход с конца отсортированной коллекции.
        # Обрабатывает только разовые встречи; вхождения серий покрыты попытками 1-2.
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

        # Извлечение описания встречи
        body = ""
        try:
            body = best_item.Body.strip() if best_item.Body else ""
        except Exception:
            pass

        return {
            "subject": best_item.Subject,
            "organizer": organizer,
            "attendees": attendees,
            "body": body,
            "start": str(best_item.Start)
        }

    except Exception as e:
        log(f"[Outlook Error] {e}")
        return None
