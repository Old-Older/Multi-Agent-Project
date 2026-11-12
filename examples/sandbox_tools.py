"""Run from the repository root: python -m examples.sandbox_tools"""
from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

from mas.agents.roles import ROLES
from mas.app import build_tools
from mas.config import Settings
from mas.sandbox import LocalSandbox
from mas.tools import ReadFile, WriteFile


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        researcher = LocalSandbox("researcher", root / "researcher")
        coder = LocalSandbox("coder", root / "coder")

        written = await WriteFile().run(researcher, path="notes.md", content="中文研究笔记\n")
        assert written.ok, written.output
        print(written.ok, written.output, written.files_written)

        # Router is the trusted source selector in the real system.
        imported = coder.import_file(researcher.resolve(written.files_written[0]))
        assert imported == "inbox/notes.md"
        read = await ReadFile().run(coder, path=imported)
        assert read.ok and read.output == "中文研究笔记\n", read.output
        assert researcher.exists("notes.md")
        print(imported, read.output.strip())

        # Known pending run_python/git produce warnings and are skipped.
        tools = {tool.name: tool for tool in build_tools(ROLES["coder"], Settings())}
        result = await tools["write_file"].run(coder, path="result.txt", content=read.output)
        assert result.ok, result.output
        copied = await tools["read_file"].run(coder, path=result.files_written[0])
        assert copied.ok and copied.output == read.output
        print(list(tools), result.files_written)


if __name__ == "__main__":
    asyncio.run(main())
