"""抓取器基类"""
import asyncio

import httpx
from abc import ABC, abstractmethod


class BaseScraper(ABC):
    """所有抓取器的基类，提供 HTTP 客户端和请求限速。"""

    def __init__(self, delay: float = 3.0):
        self.delay = delay
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=self.get_headers(),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

    def get_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    async def fetch(self, url: str, **kwargs) -> httpx.Response:
        """发起 GET 请求，自动限速。"""
        await asyncio.sleep(self.delay)
        return await self.client.get(url, **kwargs)

    @abstractmethod
    async def get_price(self, market_hash_name: str) -> dict | None:
        ...

    @abstractmethod
    async def search_items(self, keyword: str = "", limit: int = 50) -> list:
        ...
