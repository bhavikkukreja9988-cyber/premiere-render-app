from src.core.workflow import Workflow, WorkflowState
from src.network.session import NetworkSession
from src.transfer.chunk_manager import ChunkManager
from src.transfer.transfer_engine import TransferEngine


def test_chunk_manager_roundtrip():
    data = b"abcdef" * 100
    chunks = ChunkManager().split(data, 17)
    assert b"".join(chunks) == data


def test_workflow_snapshot():
    workflow = Workflow()
    got = workflow.update(WorkflowState.TRANSFERRING, "Sending", 42)
    assert got.state is WorkflowState.TRANSFERRING
    assert got.progress == 42
    assert workflow.get().message == "Sending"


def test_transfer_engine():
    engine = TransferEngine()
    engine.start(100)
    engine.update(50, 50)
    assert engine.progress == 50
    assert engine.status == "Transferring"
    engine.complete()
    assert engine.status == "Completed"


def test_network_session_not_connected():
    session = NetworkSession()
    try:
        session.send_json({"x": 1})
    except ConnectionError:
        pass
    else:
        raise AssertionError("Expected ConnectionError")