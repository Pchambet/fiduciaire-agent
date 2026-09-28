import pytest

from fiduciaire_agent import books, demo


@pytest.fixture
def world(tmp_path):
    """The demo month, written to disk and ingested: (folder, database)."""
    folder = demo.write(tmp_path / "demo")
    db = books.connect(tmp_path / "livres.db")
    books.ingest(db, folder)
    yield folder, db
    db.close()


@pytest.fixture
def db(world):
    return world[1]
