"""任务存储模块的单元测试。"""

from storage.task_store import TaskStore
from schemas.api import TaskStatus


def test_task_store_lifecycle(tmp_path):
    store = TaskStore(task_dir=str(tmp_path / "tasks"))
    rec = store.create()
    assert rec.status == TaskStatus.pending

    store.mark_running(rec.task_id)
    rec2 = store.get(rec.task_id)
    assert rec2 is not None
    assert rec2.status == TaskStatus.running

    store.mark_success(rec.task_id, {"ok": True})
    rec3 = store.get(rec.task_id)
    assert rec3 is not None
    assert rec3.status == TaskStatus.success
    assert rec3.result == {"ok": True}

