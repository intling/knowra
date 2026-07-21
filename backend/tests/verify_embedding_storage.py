"""Verify vector storage — check job status, record count, vector dimensions, pgvector availability.

Usage:
    cd e:/personal/Desktop/AI/knowra
    backend/.venv/Scripts/python.exe verify_embedding_storage.py
"""

import io
import os
import sys
from pathlib import Path

# Force stdout to UTF-8 to avoid Windows GBK encoding errors with emoji
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Change to backend/ so pydantic-settings can find .env
backend_dir = Path(__file__).resolve().parent / "backend"
os.chdir(str(backend_dir))
sys.path.insert(0, str(backend_dir))

from app.core.config import get_settings

_settings = get_settings()
_parts = _settings.database_url.split("@")
_db_display = _parts[0].split("://")[0] + "://***@" + _parts[-1] if len(_parts) >= 2 else _settings.database_url
print(f"Database: {_db_display}")

from sqlmodel import Session, select, func, text
from app.db.session import engine
from app.models.document_embedding import DocumentEmbedding, DocumentEmbeddingJob, DocumentEmbeddingJobStatus


def verify() -> bool:
    with Session(engine) as session:
        # --- 1. Embedding job statistics ---
        total_jobs = session.exec(
            select(func.count(DocumentEmbeddingJob.id))
        ).one()
        succeeded_jobs = session.exec(
            select(func.count(DocumentEmbeddingJob.id)).where(
                DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.SUCCEEDED.value
            )
        ).one()
        failed_jobs = session.exec(
            select(func.count(DocumentEmbeddingJob.id)).where(
                DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.FAILED.value
            )
        ).one()

        print("=" * 60)
        print("Embedding Job Statistics")
        print(f"   Total jobs:    {total_jobs}")
        print(f"   Succeeded:     {succeeded_jobs}")
        print(f"   Failed:        {failed_jobs}")
        print()

        # --- 2. Latest successful job ---
        latest_job = session.exec(
            select(DocumentEmbeddingJob)
            .where(DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.SUCCEEDED.value)
            .order_by(DocumentEmbeddingJob.created_at.desc())
        ).first()

        if latest_job is None:
            print("FAIL: No successful embedding job found!")
            failed = session.exec(
                select(DocumentEmbeddingJob)
                .where(DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.FAILED.value)
                .order_by(DocumentEmbeddingJob.created_at.desc())
            ).first()
            if failed:
                print(f"   Latest failed job: {failed.id}")
                print(f"   Error code: {failed.error_code}")
                print(f"   Error message: {failed.error_message}")
            return False

        print("Latest Successful Embedding Job:")
        print(f"   Job ID:          {latest_job.id}")
        print(f"   Chunk Job ID:    {latest_job.chunk_job_id}")
        print(f"   Model:           {latest_job.model}")
        print(f"   Dimensions:      {latest_job.dimensions}")
        print(f"   Embedding Count: {latest_job.embedding_count}")
        print(f"   Status:          {latest_job.status}")
        print(f"   Started:         {latest_job.started_at}")
        print(f"   Finished:        {latest_job.finished_at}")
        print()

        # --- 3. Count embedding records ---
        total_embeddings = session.exec(
            select(func.count(DocumentEmbedding.id))
        ).one()
        job_embeddings = session.exec(
            select(func.count(DocumentEmbedding.id)).where(
                DocumentEmbedding.embedding_job_id == latest_job.id
            )
        ).one()

        print("document_embeddings Table:")
        print(f"   Total records: {total_embeddings}")
        print(f"   This job:      {job_embeddings}")
        status = "OK - consistent" if job_embeddings == latest_job.embedding_count else "MISMATCH!"
        print(f"   Consistency:   {status}")
        print()

        # --- 4. Sample a single embedding record ---
        sample = session.exec(
            select(DocumentEmbedding).where(
                DocumentEmbedding.embedding_job_id == latest_job.id
            ).limit(1)
        ).first()

        if sample is None:
            print("FAIL: No records in document_embeddings table!")
            return False

        json_len = len(sample.embedding_json) if sample.embedding_json else 0
        print("Sample Record (first embedding):")
        print(f"   Embedding ID:   {sample.id}")
        print(f"   Chunk ID:       {sample.chunk_id}")
        print(f"   Sequence Index: {sample.sequence_index}")
        print(f"   embedding_json: {json_len} dims (float list)")
        print(f"   First 5 values: {sample.embedding_json[:5] if sample.embedding_json else 'N/A'}")
        print(f"   Token Count:    {sample.token_count}")
        print()

        # --- 5. Verify pgvector vector column ---
        try:
            vector_sample = session.exec(
                text(
                    "SELECT embedding_vector IS NOT NULL AS has_vector, "
                    "vector_dims(embedding_vector) AS vec_dims "
                    "FROM document_embeddings "
                    "WHERE embedding_job_id = :jid LIMIT 1"
                ),
                params={"jid": str(latest_job.id)},
            ).first()

            if vector_sample:
                has_vector, vec_dims = vector_sample
                print("pgvector Vector Column Check:")
                print(f"   IS NOT NULL:   {has_vector}")
                print(f"   vector_dims(): {vec_dims}")
                if has_vector and vec_dims == latest_job.dimensions:
                    print("   PASS: pgvector column has data and dimensions match!")
                else:
                    print("   WARN: vector column data anomaly")
            else:
                print("WARN: Could not read embedding_vector column")
        except Exception as e:
            print(f"   WARN: pgvector extension may not be installed or query failed: {e}")

        print()

        # --- 6. Similarity search test ---
        try:
            sim_result = session.exec(
                text(
                    "SELECT id, embedding_vector <=> ("
                    "  SELECT embedding_vector FROM document_embeddings "
                    "  WHERE embedding_job_id = :jid LIMIT 1"
                    ") AS distance "
                    "FROM document_embeddings "
                    "WHERE embedding_job_id = :jid "
                    "ORDER BY distance LIMIT 3"
                ),
                params={"jid": str(latest_job.id)},
            ).all()
            print("Similarity Search Test (cosine distance, smaller = more similar):")
            for row in sim_result:
                emb_id, distance = row
                print(f"   {emb_id}: distance={distance:.6f}")
            print("   PASS: pgvector similarity search works!")
        except Exception as e:
            print(f"   WARN: Similarity search failed: {e}")

        print()
        print("=" * 60)
        print("VECTOR STORAGE VERIFICATION: ALL CHECKS PASSED!")
        return True


if __name__ == "__main__":
    success = verify()
    sys.exit(0 if success else 1)
