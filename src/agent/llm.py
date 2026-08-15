"""
LLM client — KITCOEK RAG Agent

Supports: groq | grok (xAI) | openai | anthropic | ollama
Set LLM_PROVIDER and LLM_MODEL in .env
"""

import os
import time
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama-3.1-8b-instant")


class LLMClient:
    def __init__(
        self,
        provider: str = LLM_PROVIDER,
        model: str    = LLM_MODEL,
    ) -> None:
        self.provider = provider
        self.model    = model
        self._client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        if self.provider == "groq":
            try:
                from groq import Groq
                self._client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            except ImportError:
                raise ImportError("Run: pip install groq")

        elif self.provider == "grok":
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=os.getenv("XAI_API_KEY"),
                    base_url="https://api.x.ai/v1",
                )
            except ImportError:
                raise ImportError("Run: pip install openai")

        elif self.provider == "openai":
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            except ImportError:
                raise ImportError("Run: pip install openai")

        elif self.provider == "anthropic":
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY")
                )
            except ImportError:
                raise ImportError("Run: pip install anthropic")

        elif self.provider == "ollama":
            self._client = None   # uses urllib directly

        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER='{self.provider}'. "
                "Choose: groq | grok | openai | anthropic | ollama"
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int    = 600,
    ) -> str:
        if self.provider in ("groq", "grok", "openai"):
            return self._chat_openai_compat(messages, temperature, max_tokens)
        elif self.provider == "anthropic":
            return self._chat_anthropic(messages, temperature, max_tokens)
        elif self.provider == "ollama":
            return self._chat_ollama(messages, temperature, max_tokens)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _chat_openai_compat(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Works for Groq, xAI Grok, and OpenAI — all share the same SDK interface."""
        last_err = None
        for attempt in range(3):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=40,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                last_err = e
                wait = 4 * (attempt + 1)
                print(f"[llm] Attempt {attempt + 1}/3 failed: {type(e).__name__}: {e}")
                if attempt < 2:
                    print(f"[llm] Retrying in {wait}s ...")
                    time.sleep(wait)
        raise last_err

    def _chat_anthropic(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        system_prompt = ""
        filtered = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                filtered.append(msg)
        response = self._client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=filtered,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content[0].text.strip()

    def _chat_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        import json
        import urllib.request
        payload = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
            "options":  {"temperature": temperature, "num_predict": max_tokens},
        }
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["message"]["content"].strip()
