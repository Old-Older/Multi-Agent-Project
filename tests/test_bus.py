"""InMemoryBus behaviour (design §3)."""
from __future__ import annotations

import asyncio
import unittest

from mas.core.bus import InMemoryBus
from mas.core.message import GROUP_MAIN, Message, MsgType, dm_channel


def chat(sender="human", channel=GROUP_MAIN, content="hi", **kw) -> Message:
    return Message(MsgType.CHAT, sender=sender, channel=channel, content=content, **kw)


class BusTest(unittest.IsolatedAsyncioTestCase):
    async def test_group_delivery_to_all_members(self):
        bus = InMemoryBus()
        for a in ("human", "coder", "writer"):
            bus.join(a, GROUP_MAIN)
        await bus.publish(chat())
        for a in ("human", "coder", "writer"):
            self.assertEqual((await bus.subscribe(a).get()).content, "hi")

    async def test_non_members_do_not_receive(self):
        bus = InMemoryBus()
        bus.join("coder", GROUP_MAIN)
        bus.subscribe("writer")
        await bus.publish(chat())
        self.assertTrue(bus.subscribe("writer").empty())

    async def test_message_before_subscribe_is_kept(self):
        bus = InMemoryBus()
        bus.join("coder", GROUP_MAIN)
        await bus.publish(chat())
        self.assertFalse(bus.subscribe("coder").empty())

    async def test_dm_auto_joins_both_and_stays_private(self):
        bus = InMemoryBus()
        bus.join("writer", GROUP_MAIN)
        ch = dm_channel("human", "coder")
        await bus.publish(chat(channel=ch))
        self.assertEqual(sorted(bus.members(ch)), ["coder", "human"])
        self.assertFalse(bus.subscribe("coder").empty())
        self.assertTrue(bus.subscribe("writer").empty())

    async def test_join_is_idempotent_and_members_is_a_copy(self):
        bus = InMemoryBus()
        bus.join("a", GROUP_MAIN)
        bus.join("a", GROUP_MAIN)
        m = bus.members(GROUP_MAIN)
        m.append("x")
        self.assertEqual(bus.members(GROUP_MAIN), ["a"])
        self.assertEqual(bus.members("group:none"), [])

    async def test_history_order_and_limit(self):
        bus = InMemoryBus()
        bus.join("a", GROUP_MAIN)
        for i in range(5):
            await bus.publish(chat(content=str(i)))
        self.assertEqual([m.content for m in bus.history(GROUP_MAIN, 3)], ["2", "3", "4"])
        self.assertEqual(len(bus.history(GROUP_MAIN)), 5)
        self.assertEqual(bus.history(GROUP_MAIN, 0), [])
        self.assertEqual(bus.history("group:none"), [])

    async def test_observer_sees_every_channel_before_delivery(self):
        bus = InMemoryBus()
        bus.join("a", GROUP_MAIN)
        seen: list[tuple[str, bool]] = []
        bus.add_observer(lambda m: seen.append((m.channel, bus.subscribe("a").empty())))
        await bus.publish(chat())
        await bus.publish(chat(channel=dm_channel("a", "b")))
        self.assertEqual(seen[0], (GROUP_MAIN, True))    # delivery happens after observers
        self.assertEqual(seen[1][0], dm_channel("a", "b"))

    async def test_failing_observer_does_not_block_delivery(self):
        bus = InMemoryBus()
        bus.join("a", GROUP_MAIN)
        got = []
        bus.add_observer(lambda m: 1 / 0)
        bus.add_observer(got.append)
        with self.assertLogs("mas.core.bus", level="ERROR"):
            await bus.publish(chat())
        self.assertEqual(len(got), 1)
        self.assertFalse(bus.subscribe("a").empty())

    async def test_consumer_wakes_up_on_publish(self):
        bus = InMemoryBus()
        bus.join("a", GROUP_MAIN)
        task = asyncio.create_task(bus.subscribe("a").get())
        await asyncio.sleep(0)
        await bus.publish(chat(content="x"))
        self.assertEqual((await asyncio.wait_for(task, 1)).content, "x")


if __name__ == "__main__":
    unittest.main()
