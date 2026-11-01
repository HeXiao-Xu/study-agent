"""S3-9 在线评测 HTTP 客户端；本文件不导入 app 业务模块。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import httpx


class OnlineEvalError(RuntimeError):
    """在线接口/鉴权/SSE 错误；CLI 统一退出 5。"""


def normalize_base_url(value: str) -> str:
    base = value.rstrip("/")
    return base if base.endswith("/api/v1") else f"{base}/api/v1"


def parse_sse_events(
    lines: Iterable[str],
) -> Iterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data_lines: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data_lines:
                try:
                    payload = json.loads("\n".join(data_lines))
                except json.JSONDecodeError as exc:
                    raise OnlineEvalError("SSE data 不是合法 JSON") from exc
                yield event, payload
            event = "message"
            data_lines = []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise OnlineEvalError("SSE data 不是合法 JSON") from exc
        yield event, payload


@dataclass(frozen=True)
class ApiCitation:
    chunk_id: int
    title: str | None
    heading_path: str | None
    snippet: str


@dataclass(frozen=True)
class RetrievalResponse:
    chunk_ids: list[int]
    latency_ms: int
    rerank: bool


@dataclass(frozen=True)
class AnswerResponse:
    text: str
    refused: bool
    refusal_reason: str | None
    citations: list[ApiCitation]
    tokens: int
    latency_ms: int
    cost_yuan: float
    conversation_id: str | None


class OnlineClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise OnlineEvalError("缺少访问 token")
        self._base = normalize_base_url(base_url)
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _data(response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnlineEvalError(
                f"HTTP {response.status_code}: 响应不是 JSON"
            ) from exc
        if response.status_code >= 400 or payload.get("code") != 0:
            message = payload.get("message") or payload.get("detail") or "接口失败"
            raise OnlineEvalError(f"HTTP {response.status_code}: {message}")
        return payload.get("data")

    def search(
        self, query: str, retrieval: str, *, top_k: int = 5
    ) -> RetrievalResponse:
        response = self._http.post(
            f"{self._base}/retrieval/search",
            json={"query": query, "top_k": top_k, "retrieval": retrieval},
        )
        data = self._data(response)
        return RetrievalResponse(
            chunk_ids=[int(hit["chunk_id"]) for hit in data["hits"]],
            latency_ms=int(data["elapsed_ms"]),
            rerank=bool(data["rerank"]),
        )

    def ask(self, question: str) -> AnswerResponse:
        citations: list[ApiCitation] = []
        text_parts: list[str] = []
        done: dict[str, Any] | None = None
        with self._http.stream(
            "POST", f"{self._base}/qa/ask", json={"question": question}
        ) as response:
            if response.status_code != 200:
                raise OnlineEvalError(f"HTTP {response.status_code}: 问答失败")
            for event, data in parse_sse_events(response.iter_lines()):
                if event == "meta":
                    citations = [
                        ApiCitation(
                            chunk_id=int(item["chunk_id"]),
                            title=item.get("title"),
                            heading_path=item.get("heading_path"),
                            snippet=str(item.get("snippet") or ""),
                        )
                        for item in data.get("citations", [])
                    ]
                elif event == "delta":
                    text_parts.append(str(data.get("text") or ""))
                elif event == "done":
                    done = data
                elif event == "error":
                    raise OnlineEvalError(
                        f"问答失败：{data.get('code')} {data.get('message')}"
                    )
        if done is None:
            raise OnlineEvalError("SSE 结束但没有 done 事件")
        return AnswerResponse(
            text="".join(text_parts),
            refused=bool(done.get("refused")),
            refusal_reason=done.get("refusal_reason"),
            citations=citations,
            tokens=int(done.get("tokens") or 0),
            latency_ms=int(done.get("latency_ms") or 0),
            cost_yuan=float(done.get("cost_yuan") or 0.0),
            conversation_id=done.get("conversation_id"),
        )

    def delete_conversation(self, conversation_id: str | None) -> bool:
        if not conversation_id:
            return False
        try:
            response = self._http.delete(
                f"{self._base}/qa/conversations/{conversation_id}"
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 204


def login(
    base_url: str,
    username: str,
    password: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    base = normalize_base_url(base_url)
    with httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0), transport=transport
    ) as http:
        response = http.post(
            f"{base}/auth/login",
            json={"username": username, "password": password},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OnlineEvalError(
                f"HTTP {response.status_code}: 登录响应不是 JSON"
            ) from exc
        if response.status_code >= 400 or payload.get("code") != 0:
            raise OnlineEvalError("登录失败（检查账号、密码与服务）")
        token = payload.get("data", {}).get("access_token")
        if not token:
            raise OnlineEvalError("登录响应缺少 access_token")
        return str(token)