import httpx
import pytest

from chimp.advisor import advise
from chimp.config import AdvisorConfig


@pytest.mark.asyncio
async def test_advisor_maps_class_reply(httpx_mock=None):
    advisor = AdvisorConfig(enabled=True, base_url="http://advisor.local", model="tiny", timeout_seconds=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "coder"}}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hint = await advise(client, advisor, {"messages": [{"role": "user", "content": "fix the bug"}]}, ["qwen-coder"])
    assert hint == "auto:coder"


@pytest.mark.asyncio
async def test_advisor_timeout_returns_none():
    advisor = AdvisorConfig(enabled=True, base_url="http://advisor.local", model="tiny", timeout_seconds=0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        hint = await advise(client, advisor, {"messages": [{"role": "user", "content": "hi"}]}, ["chat"])
    assert hint is None


@pytest.mark.asyncio
async def test_advisor_disabled():
    advisor = AdvisorConfig(enabled=False, base_url="http://advisor.local")
    async with httpx.AsyncClient() as client:
        assert await advise(client, advisor, {}, ["chat"]) is None
