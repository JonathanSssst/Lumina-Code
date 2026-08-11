from __future__ import annotations

from lumina.config import Settings
from lumina.tools.parallel import ParallelRunner
from lumina.types import LLMResponse, ToolCall


class _FakeResponse:
    def __init__(self, text: str, headers=None) -> None:
        self.text = text
        self.headers = headers or {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        pass


class _FakeHttp:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.last_url = None

    async def get(self, url, params=None):
        self.last_url = url
        return self.response


async def test_web_search_parses_results(registry):
    html = (
        '<a rel="nofollow" class="result__a" href="https://x.com/a">Foo <b>Bar</b></a>'
        '<a class="result__snippet">snip one</a>'
        '<a rel="nofollow" class="result__a" href="https://x.com/b">Second</a>'
        '<a class="result__snippet">snip two</a>'
    )
    fake = _FakeHttp(_FakeResponse(html))
    registry.web_tools._get_client = lambda: fake

    result = await registry.handler("web_search")(query="pytest", max_results=10)
    assert not result.is_error
    assert "Foo Bar" in result.content
    assert "https://x.com/a" in result.content
    assert "snip one" in result.content
    assert "2." in result.content
    assert fake.last_url == "https://html.duckduckgo.com/html/"


async def test_web_search_http_error(registry):
    import httpx

    class _Err:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "502 bad gateway",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(502, request=httpx.Request("GET", "http://x")),
            )

    fake = _FakeHttp(_Err())
    registry.web_tools._get_client = lambda: fake
    result = await registry.handler("web_search")(query="x")
    assert result.is_error
    assert "web_search failed" in result.content


async def test_web_fetch_html_strips_scripts(registry):
    page = "<html><head><title>T</title></head><body><script>var x=1</script>Hello <b>world</b></body></html>"
    registry.web_tools._get_client = lambda: _FakeHttp(_FakeResponse(page))

    result = await registry.handler("web_fetch")(url="https://example.com/", max_chars=1000)
    assert not result.is_error
    assert "Title: T" in result.content
    assert "Hello world" in result.content
    assert "var x=1" not in result.content


async def test_web_fetch_rejects_non_http(registry):
    result = await registry.handler("web_fetch")(url="ftp://x")
    assert result.is_error


async def test_web_fetch_non_html_returns_raw(registry):
    registry.web_tools._get_client = lambda: _FakeHttp(
        _FakeResponse("RAW-BODY", headers={"content-type": "text/plain"})
    )
    result = await registry.handler("web_fetch")(url="https://example.com/data")
    assert not result.is_error
    assert result.content == "RAW-BODY"


class _FakeLLM:
    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, **kwargs):
        assert self.calls < len(self.script), "no more scripted responses"
        resp = self.script[self.calls]
        self.calls += 1
        return resp


def _sub_runner(registry, llm):
    return ParallelRunner(registry, llm, Settings(DEEPSEEK_API_KEY="k"))


async def test_parallel_returns_reports(registry):
    llm = _FakeLLM(
        [LLMResponse(content="report A"), LLMResponse(content="report B")]
    )
    runner = _sub_runner(registry, llm)
    out = await runner._run([{"id": "a", "goal": "goal A"}, {"id": "b", "goal": "goal B"}])
    assert "[a]" in out and "report A" in out
    assert "[b]" in out and "report B" in out
    assert llm.calls == 2


async def test_parallel_handles_exception(registry):
    class _Boom:
        async def chat(self, messages, **kwargs):
            raise RuntimeError("llm down")

    runner = _sub_runner(registry, _Boom())
    out = await runner._run([{"id": "a", "goal": "g"}])
    assert "ERROR" in out
    assert "llm down" in out


async def test_parallel_empty_goal(registry):
    llm = _FakeLLM([])
    runner = _sub_runner(registry, llm)
    out = await runner._run([{"id": "a", "goal": "  "}])
    assert out.strip() == "[a]\n(empty goal)"
    assert llm.calls == 0


async def test_sub_agent_executes_readonly_tools(registry):
    llm = _FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "src/calc.py"})]),
            LLMResponse(content="the file says add"),
        ]
    )
    runner = _sub_runner(registry, llm)
    out = await runner._sub_agent({"id": "x", "goal": "read calc"})
    assert out == "the file says add"
    assert llm.calls == 2


async def test_exec_tool_disallowed_name(registry):
    runner = _sub_runner(registry, _FakeLLM([]))
    msg = await runner._exec_tool(
        ToolCall(id="c1", name="write_file", arguments={"path": "x", "content": "y"}), tools=[]
    )
    assert msg.role == "tool"
    assert "not allowed" in msg.content
