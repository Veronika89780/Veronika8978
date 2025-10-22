# -*- coding: utf-8 -*-
"""
Парсер ключевой ставки ЦБ РФ.

Требования задания:
- Парсер запускается вызовом Parser.start() и сохраняет данные в JSON.
- Все методы с логикой выгрузки/сохранения — приватные.
- Код оформлен по PEP8.
- В классах реализованы методы сериализации и десериализации.

Реализация:
- Класс ParserCBRF имеет единственный публичный метод start().
- По умолчанию парсится HTML-таблица с историей ключевой ставки:
  https://cbr.ru/hd_base/KeyRate/
- Данные сохраняются в файл cbr_key_rate.json с мапой:
  { "YYYY-MM-DD": <float ключевая_ставка>, ... }

Структуры данных:
- KeyRateRecord  — одна запись (дата + ставка) с to_dict()/from_dict().
- KeyRateDataset — набор записей с to_json()/from_json() и сохранением в файл.

Пример запуска:
    if __name__ == "__main__":
        ParserCBRF().start()
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag


# ==========================
# Структуры данных + (де)сериализация
# ==========================

@dataclass
class KeyRateRecord:
    """
    Одна запись ключевой ставки.

    Атрибуты:
        dt (date): дата, на которую зафиксирована ставка.
        rate (float): значение ключевой ставки в процентах (например, 16.0).
    """
    dt: date
    rate: float

    def to_dict(self) -> Dict[str, str]:
        """
        Сериализация в примитивный словарь (для JSON).

        Returns:
            dict: {"date": "YYYY-MM-DD", "rate": <float>}
        """
        return {
            "date": self.dt.isoformat(),
            "rate": self.rate,
        }

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "KeyRateRecord":
        """
        Десериализация из словаря.

        Args:
            data: словарь формата {"date": "YYYY-MM-DD", "rate": <float>}

        Returns:
            KeyRateRecord
        """
        dt_raw = data.get("date")
        rate_raw = data.get("rate")
        if not isinstance(dt_raw, str):
            raise ValueError("Field 'date' must be ISO string.")
        if not isinstance(rate_raw, (int, float)):
            raise ValueError("Field 'rate' must be a number.")
        return KeyRateRecord(
            dt=datetime.fromisoformat(dt_raw).date(),
            rate=float(rate_raw),
        )


@dataclass
class KeyRateDataset:
    """
    Набор записей ключевой ставки.
    Предоставляет удобную мапу по дате и (де)сериализацию в/из JSON.
    """
    records: List[KeyRateRecord] = field(default_factory=list)

    def to_mapping(self) -> Dict[str, float]:
        """
        Преобразовать в словарь { "YYYY-MM-DD": rate }.

        Returns:
            dict[str, float]
        """
        result: Dict[str, float] = {}
        for rec in self.records:
            iso = rec.dt.isoformat()
            result[iso] = rec.rate
        return result

    def to_json_str(self, indent: int = 2, ensure_ascii: bool = False) -> str:
        """
        Сериализовать в строку JSON (словарь маппинга).

        Returns:
            str: JSON
        """
        payload = self.to_mapping()
        return json.dumps(payload, indent=indent, ensure_ascii=ensure_ascii)

    def save_json(self, path: str) -> None:
        """
        Сохранить JSON в файл.

        Args:
            path: путь к файлу (например, 'cbr_key_rate.json')
        """
        text = self.to_json_str()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def from_json_str(s: str) -> "KeyRateDataset":
        """
        Восстановить набор из JSON-строки формата { "YYYY-MM-DD": rate }.

        Args:
            s: JSON-строка

        Returns:
            KeyRateDataset
        """
        obj = json.loads(s)
        if not isinstance(obj, dict):
            raise ValueError("JSON must represent a mapping {date: rate}.")
        records: List[KeyRateRecord] = []
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError("Date keys must be strings (ISO).")
            if not isinstance(v, (int, float)):
                raise ValueError("Rate values must be numeric.")
            records.append(
                KeyRateRecord(
                    dt=datetime.fromisoformat(k).date(),
                    rate=float(v),
                )
            )
        # Отсортируем по дате на всякий случай
        records.sort(key=lambda r: r.dt)
        return KeyRateDataset(records=records)

    @staticmethod
    def from_json_file(path: str) -> "KeyRateDataset":
        """
        Восстановить набор из JSON-файла.

        Args:
            path: путь к файлу

        Returns:
            KeyRateDataset
        """
        with open(path, "r", encoding="utf-8") as f:
            return KeyRateDataset.from_json_str(f.read())


# ==========================
# Парсер ЦБ РФ (единственный публичный метод start)
# ==========================

class ParserCBRF:
    """
    Парсер данных с сайта ЦБ РФ.

    Публичный метод:
        start(): запускает процесс получения данных и сохраняет результат в JSON.

    Все прочие методы приватные (начинаются с подчёркивания).
    По умолчанию парсится таблица ключевой ставки:
        https://cbr.ru/hd_base/KeyRate/

    Конфигурация по умолчанию:
        - out_json      = 'cbr_key_rate.json'
        - base_url_html = 'https://cbr.ru/hd_base/KeyRate/'
        - user_agent    = корректный UA, чтобы сервер не отвергал запрос.
        - таймаут       = 30 с
    """

    def __init__(self,
                 out_json: str = "cbr_key_rate.json",
                 base_url_html: str = "https://cbr.ru/hd_base/KeyRate/",
                 timeout: int = 30) -> None:
        self._out_json = out_json
        self._base_url_html = base_url_html
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    # ---------- Публичный метод ----------

    def start(self) -> None:
        """
        Запускает парсер:
            1) Загружает страницу ЦБ с таблицей ключевой ставки.
            2) Извлекает пары (дата, ставка).
            3) Сохраняет в JSON (self._out_json) в формате { "YYYY-MM-DD": rate }.

        Результат:
            Файл JSON в рабочей директории. При ошибках — понятные сообщения и
            завершение с ненулевым кодом возврата (для удобства автопроверки).
        """
        try:
            html = self._fetch_html(self._base_url_html)
            rows = self._parse_key_rate_rows(html)
            dataset = self._build_dataset(rows)
            self._save_json(dataset, self._out_json)
            print(f"[OK] Данные сохранены в '{self._out_json}'. Записей: {len(dataset.records)}")
        except Exception as exc:
            # В учебной задаче логируем в stderr и выходим с кодом 1
            print(f"[ERROR] Не удалось выполнить парсинг: {exc}", file=sys.stderr)
            sys.exit(1)

    # ---------- Приватные методы ----------

    def _fetch_html(self, url: str) -> str:
        """
        Приватный метод: скачивает HTML указанной страницы.

        Args:
            url: адрес страницы ЦБ

        Returns:
            str: HTML-разметка

        Raises:
            RuntimeError: при HTTP-ошибке или таймауте.
        """
        resp = self._session.get(url, timeout=self._timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} при обращении к {url}")
        return resp.text

    def _parse_key_rate_rows(self, html: str) -> List[Tuple[date, float]]:
        """
        Приватный метод: парсит HTML таблицу с ключевой ставкой.

        Допущение:
            На странице https://cbr.ru/hd_base/KeyRate/ присутствует таблица
            с колонками вида "Дата" и "Ключевая ставка, % годовых".
            Мы ищем первую таблицу, где есть 2 колонки: дата и ставка.

        Returns:
            list[tuple[date, float]]: список пар (дата, ставка)

        Raises:
            RuntimeError: если таблица не найдена или распарсить не удалось.
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            raise RuntimeError("На странице не найдено ни одной таблицы.")

        # Попробуем найти подходящую таблицу по хедерам/структуре.
        for table in tables:
            parsed = self._try_parse_table(table)
            if parsed:
                # Отсортируем по дате по возрастанию
                parsed.sort(key=lambda pair: pair[0])
                return parsed

        raise RuntimeError("Не удалось распознать таблицу с ключевой ставкой.")

    def _try_parse_table(self, table: Tag) -> Optional[List[Tuple[date, float]]]:
        """
        Приватный метод: попробовать вытащить пары (дата, ставка) из таблицы.

        Эвристики:
        - Ищем строки <tr>, в которых две/три ячейки: первая — дата, вторая — число.
        - Дату распознаём в форматах 'DD.MM.YYYY' или ISO 'YYYY-MM-DD'.
        - Число может иметь запятую как десятичный разделитель.

        Returns:
            список пар или None, если таблица не подходит
        """
        rows: List[Tuple[date, float]] = []
        trs = table.find_all("tr")
        if not trs:
            return None

        # Пройдём по строкам, пропускаем заголовки, собираем валидные пары
        for tr in trs:
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue

            # Попытка распознать дату и ставку из первых двух ячеек
            dt_obj = self._parse_date_safe(cells[0])
            rate_val = self._parse_rate_safe(cells[1])

            if dt_obj is not None and rate_val is not None:
                rows.append((dt_obj, rate_val))

        # Возвращаем список, если он выглядит разумно (например, >= 5 записей)
        return rows if len(rows) >= 5 else None

    @staticmethod
    def _parse_date_safe(s: str) -> Optional[date]:
        """
        Приватный метод: распознаёт дату в популярных форматах.

        Поддерживаемые форматы:
            - DD.MM.YYYY
            - YYYY-MM-DD

        Returns:
            date или None, если формат не распознан.
        """
        s = s.strip()
        # DD.MM.YYYY
        m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        if m:
            day, month, year = map(int, m.groups())
            return date(year, month, day)

        # ISO YYYY-MM-DD
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            year, month, day = map(int, m.groups())
            return date(year, month, day)

        # Иногда попадаются "01.01.2016*" с примечаниями — очистим хвосты
        s_clean = re.sub(r"[^\d\.\-]", "", s)
        if s_clean != s:
            return ParserCBRF._parse_date_safe(s_clean)

        return None

    @staticmethod
    def _parse_rate_safe(s: str) -> Optional[float]:
        """
        Приватный метод: распознать число со знаком процента/запятой.

        Примеры входа:
            '16,00'  -> 16.0
            '17.5'   -> 17.5
            '8,25%'  -> 8.25

        Returns:
            float или None
        """
        if not s:
            return None
        s = s.strip().replace("%", "").replace(" ", "")
        # Заменим русскую запятую на точку
        s = s.replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    @staticmethod
    def _build_dataset(rows: List[Tuple[date, float]]) -> KeyRateDataset:
        """
        Приватный метод: собрать KeyRateDataset из пар (дата, ставка).

        Args:
            rows: список пар (date, float)

        Returns:
            KeyRateDataset
        """
        records = [KeyRateRecord(dt=r[0], rate=r[1]) for r in rows]
        # На всякий случай отфильтруем дубликаты по дате, берём последнее значение
        dedup: Dict[date, float] = {}
        for rec in records:
            dedup[rec.dt] = rec.rate
        normalized = [KeyRateRecord(dt=k, rate=v) for k, v in dedup.items()]
        normalized.sort(key=lambda r: r.dt)
        return KeyRateDataset(records=normalized)

    @staticmethod
    def _save_json(dataset: KeyRateDataset, path: str) -> None:
        """
        Приватный метод: сохранить набор в JSON-файл.

        Args:
            dataset: KeyRateDataset
            path: путь к файлу
        """
        dir_name = os.path.dirname(os.path.abspath(path))
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        dataset.save_json(path)


# ==========================
# Точка входа (для самостоятельного запуска)
# ==========================
if __name__ == "__main__":
    ParserCBRF().start()
