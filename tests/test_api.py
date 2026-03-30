"""
Integration tests for all API endpoints.
Uses the async test client with an in-memory SQLite DB.
"""
import pytest
import pytest_asyncio
from sqlmodel.ext.asyncio.session import AsyncSession

from platform.models.institution import Institution
from platform.models.data_file import DataFile, FileStatus
from platform.models.dataset import Dataset, DatasetStatus


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _add_institution(session: AsyncSession, slug: str = "bnb") -> Institution:
    inst = Institution(
        slug=slug,
        name=f"{slug.upper()} Test",
        base_url=f"https://{slug}.example.com",
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    return inst


async def _add_file(session: AsyncSession, institution_id: int) -> DataFile:
    f = DataFile(
        url="https://example.com/test.csv",
        filename="test.csv",
        institution_id=institution_id,
        status=FileStatus.DOWNLOADED,
        file_size=1024,
    )
    session.add(f)
    await session.commit()
    await session.refresh(f)
    return f


async def _add_dataset(session: AsyncSession, institution_id: int, file_id: int) -> Dataset:
    ds = Dataset(
        name="Test Dataset",
        data_file_id=file_id,
        institution_id=institution_id,
        row_count=100,
        column_count=5,
        status=DatasetStatus.READY,
        column_schema={"col_a": "Int64", "col_b": "Utf8"},
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


# ── Institution endpoints ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_institutions_empty(client):
    response = await client.get("/api/institutions")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_institutions(client, db_session):
    await _add_institution(db_session, "bnb")
    await _add_institution(db_session, "nsi")
    response = await client.get("/api/institutions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    slugs = {i["slug"] for i in data}
    assert "bnb" in slugs and "nsi" in slugs


@pytest.mark.asyncio
async def test_get_institution_404(client):
    response = await client.get("/api/institutions/9999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_institution(client, db_session):
    inst = await _add_institution(db_session)
    response = await client.get(f"/api/institutions/{inst.id}")
    assert response.status_code == 200
    assert response.json()["slug"] == "bnb"


# ── File endpoints ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_files_empty(client):
    response = await client.get("/api/files")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_files(client, db_session):
    inst = await _add_institution(db_session)
    await _add_file(db_session, inst.id)
    response = await client.get("/api/files")
    data = response.json()
    assert len(data) == 1
    assert data[0]["filename"] == "test.csv"


@pytest.mark.asyncio
async def test_get_file_404(client):
    response = await client.get("/api/files/9999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_files_filter_by_institution(client, db_session):
    inst1 = await _add_institution(db_session, "bnb")
    inst2 = await _add_institution(db_session, "nsi")
    await _add_file(db_session, inst1.id)
    await _add_file(db_session, inst2.id)

    response = await client.get(f"/api/files?institution_id={inst1.id}")
    data = response.json()
    assert len(data) == 1


# ── Dataset endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_datasets_empty(client):
    response = await client.get("/api/datasets")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_datasets(client, db_session):
    inst = await _add_institution(db_session)
    f = await _add_file(db_session, inst.id)
    await _add_dataset(db_session, inst.id, f.id)
    response = await client.get("/api/datasets")
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Dataset"


@pytest.mark.asyncio
async def test_get_dataset_404(client):
    response = await client.get("/api/datasets/9999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_dataset(client, db_session):
    inst = await _add_institution(db_session)
    f = await _add_file(db_session, inst.id)
    ds = await _add_dataset(db_session, inst.id, f.id)
    response = await client.get(f"/api/datasets/{ds.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 100
    assert body["column_count"] == 5


@pytest.mark.asyncio
async def test_dataset_data_no_parquet(client, db_session):
    inst = await _add_institution(db_session)
    f = await _add_file(db_session, inst.id)
    ds = await _add_dataset(db_session, inst.id, f.id)
    response = await client.get(f"/api/datasets/{ds.id}/data")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dataset_quality_not_yet_available(client, db_session):
    inst = await _add_institution(db_session)
    f = await _add_file(db_session, inst.id)
    ds = await _add_dataset(db_session, inst.id, f.id)
    response = await client.get(f"/api/datasets/{ds.id}/quality")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dataset_quality_returns_report(client, db_session):
    inst = await _add_institution(db_session)
    f = await _add_file(db_session, inst.id)
    ds = await _add_dataset(db_session, inst.id, f.id)

    # Inject a quality report
    ds.quality_report = {"quality_score": 88.5, "row_count": 100, "recommendations": []}
    db_session.add(ds)
    await db_session.commit()

    response = await client.get(f"/api/datasets/{ds.id}/quality")
    assert response.status_code == 200
    assert response.json()["quality_score"] == 88.5


# ── Scraper API ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_scrapers(client):
    response = await client.get("/api/scrapers")
    assert response.status_code == 200
    slugs = response.json()
    assert "bnb" in slugs
    assert "nsi" in slugs


@pytest.mark.asyncio
async def test_trigger_scraper_unknown_institution(client):
    response = await client.post("/api/scrapers/nonexistent/run")
    assert response.status_code == 404


# ── Dashboard HTML pages ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_page_returns_html(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"BG Data Platform" in response.content


@pytest.mark.asyncio
async def test_datasets_page_returns_html(client):
    response = await client.get("/datasets")
    assert response.status_code == 200
    assert b"Datasets" in response.content


@pytest.mark.asyncio
async def test_scrapers_page_returns_html(client):
    response = await client.get("/scrapers")
    assert response.status_code == 200
    assert b"Scraper" in response.content


@pytest.mark.asyncio
async def test_dataset_detail_404(client):
    response = await client.get("/datasets/9999")
    assert response.status_code == 404
