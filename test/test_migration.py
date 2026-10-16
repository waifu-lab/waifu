import sqlite3

import pytest


@pytest.mark.unit
def test_title_status_column_added_and_backfilled(tmp_dir):
    from waifu.store.models import Conversation, Database, TitleStatus

    db_path = tmp_dir / "old.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE conversations (id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
    )
    con.execute("INSERT INTO conversations VALUES ('c1', 'c1', '2026-01-01', '2026-01-01')")
    con.execute("INSERT INTO conversations VALUES ('c2', '已命名', '2026-01-01', '2026-01-01')")
    con.commit()
    con.close()

    Database(db_path).init()
    assert Conversation.get_by_id("c1").title_status == TitleStatus.PENDING
    assert Conversation.get_by_id("c2").title_status == TitleStatus.SET
    Database(db_path).init()  # 再次初始化不會重複 migrate
