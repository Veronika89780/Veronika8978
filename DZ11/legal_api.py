"""
LegalAPI — универсальный клиент для https://legal-api.sirotinsky.com/

Идея:
- При инициализации забираем OpenAPI-схему (обычно /openapi.json у FastAPI).
- Разбираем все paths/operations, строим словарь operationId -> (method, path).
- Даём универсальный вызов через .call(operation_id, ...), а также «ленивые»
  псевдо-методы через __getattr__: client.someOperationId(query=..., body=...).
- Для ЕФРСБ предоставляем публичные методы с понятными docstring:
  - efrsb_search(...)
  - efrsb_get_debtor(...)
  - efrsb_get_case(...)
  - efrsb_list_notices(...)
  Эти методы автоматически ищут подходящие operationId/пути по ключевым словам
  ('efrsb', 'bankrupt', 'debtor', 'notice', 'case') и проксируют вызов.
  Если подходящих операций нет — сообщают, какие есть (list_efrsb_methods()).

Требования:
- Python 3.9+
- requests

Пример:
    from legal_api import LegalAPI

    TOKEN = "4123saedfasedfsadf4324234f223ddf23"
    api = LegalAPI(token=TOKEN, base_url="https://legal-api.sirotinsky.com")

    # Список всех operationId:
    for op in api.list_endpoints()[:10]:
        print(op)

    # Вызов по operationId напрямую:
    data = api.call("searchEFRSBNotices", query={"inn": "7707083893"})

    # Удобные ЕФРСБ-методы (подберут подходящие операции по схеме):
    notices = api.efrsb_list_notices(query={"inn": "7707083893"})
    debtor = api.efrsb_get_debtor(query={"inn": "7707083893"})
"""

from __future__ import annotations

import json
import time
import typing as t
from dataclasses import dataclass
from urllib.parse import urlencode

import requests


DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.8


class LegalAPIError(Exception):
    """Исключение верхнего уровня для ошибок HTTP/сети/API."""

    def __init__(self, message: str, status: t.Optional[int] = None, payload: t.Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


@dataclass
class Operation:
    method: str          # HTTP метод (GET/POST/…)
    path: str            # Шаблон пути (например, /efrsb/notices)
    operation_id: str    # operationId из OpenAPI


class LegalAPI:
    """
    Универсальный клиент OpenAPI для https://legal-api.sirotinsky.com/.

    - Авторизация: Bearer <token> (передаётся в заголовке Authorization).
    - Автозагрузка схемы: {base_url}/openapi.json (fallback: /openapi.yaml).
    - Динамические вызовы: .call(operation_id, ...) и магия __getattr__.

    Параметры инициализации:
        token: str        — токен авторизации (из задания).
        base_url: str     — базовый URL API (по умолчанию прод-адрес).
        timeout: int      — таймаут одного запроса, сек.
        retries: int      — число ретраев на 5xx/сетевых ошибках.
        backoff: float    — базовая задержка между ретраями.

    Вызовы:
        - Параметры пути:      path_params={"id": 123}
        - Query-параметры:     query={"inn": "7707...", "limit": 100}
        - Тело запроса JSON:   body={...}
        - Файлы:               files={"file": open("doc.pdf","rb")}

    Возврат:
        - Если ответ JSON — возвращаем dict/list.
        - Иначе — bytes (например, для файлов).

    ЕФРСБ:
        - efrsb_search(...)
        - efrsb_get_debtor(...)
        - efrsb_get_case(...)
        - efrsb_list_notices(...)
      Эти методы подбирают подходящие операции из схемы по ключевым словам.
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://legal-api.sirotinsky.com",
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, */*",
            "User-Agent": "LegalAPI-Client/1.0",
        })

        # Загружаем/разбираем OpenAPI-схему и строим карту операций
        self._schema = self._load_openapi_schema()
        self._operations = self._build_operations_index(self._schema)

    # ---------- Публичные утилиты ----------

    def list_endpoints(self) -> t.List[str]:
        """Список всех известных operationId из OpenAPI."""
        return sorted(self._operations.keys())

    def list_efrsb_methods(self) -> t.List[Operation]:
        """
        Вернёт операции из схемы, которые выглядят как ЕФРСБ (по ключевым словам
        в operationId или пути). Удобно для диагностики.
        """
        out: t.List[Operation] = []
        for op in self._operations.values():
            key = f"{op.operation_id} {op.path}".lower()
            if any(k in key for k in ("efrsb", "bankrupt", "bankruptcy", "debtor", "notice", "case", "insolv")):
                out.append(op)
        return out

    # ---------- Универсальные вызовы ----------

    def call(
        self,
        operation_id: str,
        *,
        path_params: t.Optional[dict] = None,
        query: t.Optional[dict] = None,
        body: t.Optional[t.Union[dict, list]] = None,
        files: t.Optional[dict] = None,
        headers: t.Optional[dict] = None,
    ) -> t.Any:
        """
        Вызов операции по её operationId.

        Пример:
            api.call("searchEFRSBNotices", query={"inn": "7707083893"})
        """
        op = self._operations.get(operation_id)
        if not op:
            raise LegalAPIError(f"Unknown operationId: {operation_id}")

        url = self._build_url(op.path, path_params or {})
        return self._request(op.method, url, query=query, body=body, files=files, headers=headers)

    def __getattr__(self, name: str):
        """
        Магия: попытка вызвать client.someOperationId(...), где someOperationId —
        это operationId из схемы. Работает как sugar над .call().
        """
        if name in self._operations:
            def _caller(*, path_params=None, query=None, body=None, files=None, headers=None):
                return self.call(name, path_params=path_params, query=query, body=body, files=files, headers=headers)
            return _caller
        raise AttributeError(name)

    # ---------- ЕФРСБ: удобные публичные методы (с docstring) ----------

    def efrsb_search(self, *, query: dict) -> t.Any:
        """
        Поиск по данным ЕФРСБ.

        Этот метод автоматически подбирает операцию из OpenAPI-схемы, которая
        по названию (operationId/path) похожа на «поиск» по ЕФРСБ. Типичные
        параметры: ИНН/ОГРН/ФИО/№ дела/период и т.п. Смотрите список доступных
        полей в документации API (или изучите api.list_efrsb_methods()).

        Пример:
            api.efrsb_search(query={"inn": "7707083893", "limit": 50})
        """
        op = self._find_op(keywords=("efrsb", "search", "find", "query", "lookup"))
        return self.call(op.operation_id, query=query)

    def efrsb_get_debtor(self, *, query: dict = None, path_params: dict = None) -> t.Any:
        """
        Получение информации о должнике в ЕФРСБ (by id/ИНН и т.п.).

        Передавайте либо path_params (если путь типа /efrsb/debtors/{id}),
        либо query (если идентификатор передаётся в строке запроса).

        Пример:
            api.efrsb_get_debtor(query={"inn": "7707083893"})
            api.efrsb_get_debtor(path_params={"id": "12345"})
        """
        op = self._find_op(keywords=("efrsb", "debtor", "subject", "person"))
        return self.call(op.operation_id, query=query, path_params=path_params)

    def efrsb_get_case(self, *, query: dict = None, path_params: dict = None) -> t.Any:
        """
        Получение карточки дела из ЕФРСБ.

        Передавайте идентификаторы дела либо через path_params,
        либо через query — зависит от конкретного описания операции в схеме.

        Пример:
            api.efrsb_get_case(query={"caseNumber": "А40-12345/2024"})
        """
        op = self._find_op(keywords=("efrsb", "case", "proceeding", "bankruptcycase"))
        return self.call(op.operation_id, query=query, path_params=path_params)

    def efrsb_list_notices(self, *, query: dict) -> t.Any:
        """
        Получение списка публикаций/сообщений (notices) из ЕФРСБ.

        Типичные фильтры: ИНН должника, дата публикации, тип сообщения, пагинация.

        Пример:
            api.efrsb_list_notices(query={"inn": "7707083893", "limit": 100, "offset": 0})
        """
        op = self._find_op(keywords=("efrsb", "notice", "notices", "messages", "publications"))
        return self.call(op.operation_id, query=query)

    # ---------- Внутренние методы ----------

    def _find_op(self, keywords: t.Tuple[str, ...]) -> Operation:
        """
        Находит первую подходящую операцию по набору ключевых слов
        в operationId/пути. Если ничего не нашли — подсказывает, что есть.
        """
        candidates: t.List[Operation] = []
        for op in self._operations.values():
            hay = f"{op.operation_id} {op.path}".lower()
            if all(k.lower() in hay for k in keywords if k):
                candidates.append(op)

        if candidates:
            # отдаём наиболее «короткий» operationId как более специфичный
            candidates.sort(key=lambda o: (len(o.operation_id), o.operation_id))
            return candidates[0]

        # Если «жёсткий» AND ничего не дал — пробуем мягкий OR
        for op in self._operations.values():
            hay = f"{op.operation_id} {op.path}".lower()
            if any(k.lower() in hay for k in keywords if k):
                return op

        # Совсем не нашли — соберём подсказку
        tips = "\n".join(f"- {op.operation_id}  [{op.method} {op.path}]" for op in self.list_efrsb_methods())
        msg = "Не нашёл подходящий метод ЕФРСБ по ключевым словам: " + ", ".join(keywords)
        if tips:
            msg += "\nДоступные в схеме EFRSB-подобные операции:\n" + tips
        else:
            msg += "\nВ схеме не нашлось операций, похожих на ЕФРСБ. Проверьте /docs."
        raise LegalAPIError(msg)

    def _build_url(self, path_tpl: str, path_params: dict) -> str:
        """Подставляем параметры пути вида /resource/{id} -> /resource/123."""
        url = self.base_url + path_tpl
        for k, v in (path_params or {}).items():
            url = url.replace("{" + str(k) + "}", requests.utils.quote(str(v), safe=""))
        return url

    def _request(
        self,
        method: str,
        url: str,
        *,
        query: t.Optional[dict],
        body: t.Optional[t.Union[dict, list]],
        files: t.Optional[dict],
        headers: t.Optional[dict],
    ) -> t.Any:
        """
        Универсальный низкоуровневый запрос с ретраями на 5xx/сетевые ошибки.
        """
        hdrs = dict(self._session.headers)
        if headers:
            hdrs.update(headers)

        # Если файлы — не отправляем JSON-заголовок принудительно
        send_json = (body is not None) and not files

        last_err = None
        for attempt in range(1, self.retries + 2):
            try:
                resp = self._session.request(
                    method=method.upper(),
                    url=url if not query else f"{url}?{urlencode(query, doseq=True)}",
                    timeout=self.timeout,
                    json=body if send_json else None,
                    data=None if send_json else (body if body is not None else None),
                    files=files,
                    headers=hdrs,
                )
                if 200 <= resp.status_code < 300:
                    # Пытаемся распарсить JSON, иначе – отдаём bytes
                    ctype = resp.headers.get("Content-Type", "")
                    if "application/json" in ctype:
                        return resp.json()
                    return resp.content

                # Ошибки клиента/сервера
                msg = f"HTTP {resp.status_code} at {url}: {resp.text[:500]}"
                if 500 <= resp.status_code < 600 and attempt <= self.retries:
                    time.sleep(self.backoff * attempt)
                    continue
                raise LegalAPIError(msg, status=resp.status_code, payload=self._safe_json(resp))
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                if attempt <= self.retries:
                    time.sleep(self.backoff * attempt)
                    continue
                raise LegalAPIError(f"Network error at {url}: {e}")

        # Если мы здесь — все ретраи исчерпаны
        raise LegalAPIError(f"Request failed after retries: {last_err}")

    def _load_openapi_schema(self) -> dict:
        """Тянем {base_url}/openapi.json (fallback: /openapi.yaml)."""
        json_url = f"{self.base_url}/openapi.json"
        yaml_url = f"{self.base_url}/openapi.yaml"

        # Сначала пробуем JSON
        try:
            r = self._session.get(json_url, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass

        # Затем YAML (в очень простом виде, если сервер отдаёт JSON-совместимый YAML)
        try:
            r = self._session.get(yaml_url, timeout=self.timeout, headers={"Accept": "application/yaml, */*"})
            if r.status_code == 200:
                # Пытаемся распарсить YAML без внешних зависимостей:
                # многие FastAPI отдают YAML, который также JSON-совместим.
                try:
                    return json.loads(r.text)
                except json.JSONDecodeError:
                    # Если нужен полноценный YAML — можно добавить pyyaml.
                    raise LegalAPIError("OpenAPI schema is YAML; install PyYAML or use JSON schema endpoint.")
        except Exception:
            pass

        raise LegalAPIError(
            f"Не удалось загрузить OpenAPI-схему по {json_url} или {yaml_url}. "
            "Проверьте доступность API/документации."
        )

    def _build_operations_index(self, schema: dict) -> dict:
        """Строим карту operationId -> Operation из OpenAPI схемы."""
        paths = schema.get("paths") or {}
        ops: dict[str, Operation] = {}
        for path, methods in paths.items():
            for method, spec in (methods or {}).items():
                if not isinstance(spec, dict):
                    continue
                op_id = spec.get("operationId")
                if not op_id:
                    # Синтетический operationId: METHOD_path
                    op_id = f"{method.lower()}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '')}"
                ops[op_id] = Operation(method=method.upper(), path=path, operation_id=op_id)
        if not ops:
            raise LegalAPIError("OpenAPI schema parsed, but no operations found.")
        return ops

    @staticmethod
    def _safe_json(resp: requests.Response) -> t.Any:
        try:
            return resp.json()
        except Exception:
            return {"text": resp.text}
