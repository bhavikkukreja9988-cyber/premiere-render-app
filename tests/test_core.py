"""Core-module tests, carried over from the MVP but pointed at the real
implementations that replaced the prototype stubs."""

import unittest

from src.core.workflow import Workflow, WorkflowState
from src.network.session import NetworkSession, Peer
from src.transfer.chunk_manager import ChunkManager
from src.transfer.transfer_engine import TransferEngine


class TestChunkManager(unittest.TestCase):
    def test_split_roundtrips(self):
        data = b"abcdef" * 100
        chunks = ChunkManager().split(data, 17)
        self.assertEqual(b"".join(chunks), data)
        self.assertTrue(all(len(c) <= 17 for c in chunks))

    def test_split_rejects_bad_size(self):
        with self.assertRaises(ValueError):
            ChunkManager().split(b"x", 0)


class TestWorkflow(unittest.TestCase):
    def test_snapshot_updates(self):
        workflow = Workflow()
        got = workflow.update(WorkflowState.TRANSFERRING, "Sending", 42)
        self.assertIs(got.state, WorkflowState.TRANSFERRING)
        self.assertEqual(got.progress, 42)
        self.assertEqual(workflow.get().message, "Sending")

    def test_progress_is_clamped(self):
        workflow = Workflow()
        self.assertEqual(workflow.update(WorkflowState.RENDERING, "", 500).progress, 100)
        self.assertEqual(workflow.update(WorkflowState.RENDERING, "", -5).progress, 0)

    def test_listeners_are_notified(self):
        workflow = Workflow()
        seen = []
        workflow.subscribe(lambda snap: seen.append(snap.state))
        workflow.update(WorkflowState.COMPLETE, "done", 100)
        self.assertEqual(seen[-1], WorkflowState.COMPLETE)


class TestTransferEngine(unittest.TestCase):
    def test_progress_tracking(self):
        engine = TransferEngine()
        engine.start(100)
        self.assertEqual(engine.status, "Transferring")
        engine.update(50, 100)
        self.assertEqual(engine.progress, 50)
        engine.complete()
        self.assertEqual(engine.status, "Completed")
        self.assertEqual(engine.progress, 100)


class TestNetworkSession(unittest.TestCase):
    def test_send_before_connect_raises(self):
        session = NetworkSession()
        self.assertFalse(session.connected)
        with self.assertRaises(ConnectionError):
            session.send_json({"x": 1})

    def test_peer_address(self):
        peer = Peer(host="192.168.1.5", port=49872, name="RENDER-01")
        self.assertEqual(peer.address, ("192.168.1.5", 49872))


if __name__ == "__main__":
    unittest.main()
