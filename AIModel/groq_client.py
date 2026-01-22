import requests


class GroqClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens

    def chat(self, messages: list[dict]) -> str:
        payload: dict = {
            "model": self._model,
            "messages": messages,
        }
        if self._temperature is not None:
            payload["temperature"] = float(self._temperature)
        if self._max_tokens:
            payload["max_tokens"] = int(self._max_tokens)
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        resp = requests.post(url, json=payload, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        return (content or "").strip()
