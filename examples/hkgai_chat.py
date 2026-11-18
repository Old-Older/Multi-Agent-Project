"""Send one chat request to the HKGAI model configured in the environment."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from mas.app import make_llm
from mas.config import Settings
from mas.llm.base import LLMError
from mas.tools.files import ListFiles


async def main(with_tools: bool) -> None:
    load_dotenv(Path.cwd() / ".env")
    settings = Settings.from_env()
    client = make_llm(settings)
    prompt = "请用一句话说明你的作用。"
    tools = None
    if with_tools:
        prompt = "请调用 list_files 查看工作区根目录。"
        tools = [ListFiles().spec()]
    reply = await client.chat([{"role": "user", "content": prompt}],
                              tools=tools, temperature=settings.temperature)
    if reply.text:
        print(reply.text)
    for call in reply.tool_calls:
        print(json.dumps({"id": call.id, "name": call.name, "arguments": call.arguments},
                         ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-tools", action="store_true",
                        help="Send the list_files schema and display any requested calls.")
    try:
        asyncio.run(main(parser.parse_args().with_tools))
    except LLMError as exc:
        raise SystemExit(str(exc)) from None
