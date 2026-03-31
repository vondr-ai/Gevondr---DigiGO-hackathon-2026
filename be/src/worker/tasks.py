from __future__ import annotations

from datetime import UTC
from datetime import datetime
from uuid import UUID

from arq.connections import RedisSettings

from src.database.keydb.arq_config import get_arq_redis_settings
from src.database.models import DatasourceORM
from src.database.models import IndexingJobORM
from src.database.models import ProjectORM
from src.database.session_manager import get_session_manager
from src.services.audit_service import purge_expired_events
from src.services.audit_service import record_event
from src.services.audit_service import record_many
from src.services.indexing_service import run_indexing_job as run_indexing_job_service
from src.services.staging_service import sync_datasource_staging


async def discover_datasource_tree(
    ctx,
    datasource_id: str,
    root_path: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    _ = ctx
    session_manager = get_session_manager()
    with session_manager.get_pg_session() as session:
        datasource = session.get(DatasourceORM, UUID(datasource_id))
        if datasource is None:
            raise ValueError("Datasource not found")
        project = session.get(ProjectORM, datasource.project_id)
        if project is None:
            raise ValueError("Project not found")
        result = sync_datasource_staging(
            session,
            datasource=datasource,
            root_path=root_path,
        )
        datasource.status = "synced"
        actor = (audit_context or {}).get("actor")
        correlation_id = (audit_context or {}).get("correlationId")
        events: list[dict] = []
        for document in result.created_documents:
            events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "datasource_id": datasource.id,
                    "event_domain": "document",
                    "event_action": "create",
                    "summary": f"Document {document['fileName']} ontdekt tijdens sync.",
                    "actor": actor,
                    "resource_type": "document",
                    "resource_id": document["documentId"],
                    "resource_path": document["path"],
                    "source": "worker",
                    "payload": {"correlationId": correlation_id},
                }
            )
        for document in result.updated_documents:
            events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "datasource_id": datasource.id,
                    "event_domain": "document",
                    "event_action": "update",
                    "summary": f"Document {document['fileName']} bijgewerkt tijdens sync.",
                    "actor": actor,
                    "resource_type": "document",
                    "resource_id": document["documentId"],
                    "resource_path": document["path"],
                    "source": "worker",
                    "payload": {"correlationId": correlation_id},
                }
            )
        for document in result.deleted_documents:
            events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "datasource_id": datasource.id,
                    "event_domain": "document",
                    "event_action": "delete",
                    "summary": f"Document {document['fileName']} verwijderd tijdens sync.",
                    "actor": actor,
                    "resource_type": "document",
                    "resource_id": document["documentId"],
                    "resource_path": document["path"],
                    "source": "worker",
                    "payload": {"correlationId": correlation_id},
                }
            )
        record_many(session, events=events)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            datasource_id=datasource.id,
            event_domain="datasource",
            event_action="sync_completed",
            summary=f"Datasource {datasource.display_name} gesynchroniseerd.",
            actor=actor,
            resource_type="datasource",
            resource_id=str(datasource.id),
            source="worker",
            payload={
                "folders": result.folders,
                "documents": result.documents,
                "createdDocuments": result.created_documents,
                "updatedDocuments": result.updated_documents,
                "deletedDocuments": result.deleted_documents,
                "correlationId": correlation_id,
                "rootPath": root_path,
            },
        )
        return {"folders": result.folders, "documents": result.documents}


async def sync_staging_documents(
    ctx,
    datasource_id: str,
    root_path: str | None = None,
    audit_context: dict | None = None,
) -> dict:
    return await discover_datasource_tree(ctx, datasource_id, root_path, audit_context)


async def run_indexing_job(ctx, job_id: str, audit_context: dict | None = None) -> dict:
    _ = ctx
    session_manager = get_session_manager()
    with session_manager.get_pg_session() as session:
        job = session.get(IndexingJobORM, UUID(job_id))
        if job is None:
            raise ValueError("Indexing job not found")
        project = session.get(ProjectORM, job.project_id)
        if project is None:
            raise ValueError("Project not found")
        actor = (audit_context or {}).get("actor")
        correlation_id = (audit_context or {}).get("correlationId")
        try:
            result = await run_indexing_job_service(session, UUID(job_id))
            record_event(
                session,
                owner_party_id=project.owner_party_id,
                project_id=project.id,
                datasource_id=job.datasource_id,
                job_id=job.id,
                event_domain="indexing",
                event_action="completed",
                summary=f"Indexing job {job.id} voltooid.",
                actor=actor,
                resource_type="indexing_job",
                resource_id=str(job.id),
                source="worker",
                payload={
                    "processed": result.processed,
                    "failed": result.failed,
                    "correlationId": correlation_id,
                },
            )
            return {"processed": result.processed, "failed": result.failed}
        except Exception as exc:
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.finished_at = datetime.now(UTC).replace(tzinfo=None)
                record_event(
                    session,
                    owner_party_id=project.owner_party_id,
                    project_id=project.id,
                    datasource_id=job.datasource_id,
                    job_id=job.id,
                    event_domain="indexing",
                    event_action="failed",
                    summary=f"Indexing job {job.id} mislukt.",
                    actor=actor,
                    resource_type="indexing_job",
                    resource_id=str(job.id),
                    source="worker",
                    outcome="error",
                    payload={"error": str(exc), "correlationId": correlation_id},
                )
                session.commit()
            raise


async def activate_index_revision(ctx, job_id: str) -> dict:
    _ = ctx
    session_manager = get_session_manager()
    with session_manager.get_pg_session() as session:
        job = session.get(IndexingJobORM, UUID(job_id))
        if job is None or job.index_revision_id is None:
            raise ValueError("Indexing job not found")
        job.status = "completed"
        return {"jobId": job_id, "status": job.status}


async def cleanup_old_vector_revision(ctx, project_id: str) -> dict:
    _ = ctx
    _ = project_id
    return {"status": "noop"}


async def cleanup_audit_logs(ctx) -> dict:
    _ = ctx
    session_manager = get_session_manager()
    with session_manager.get_pg_session() as session:
        deleted = purge_expired_events(session)
        return {"deleted": deleted}


class WorkerSettings:
    functions = [
        discover_datasource_tree,
        sync_staging_documents,
        run_indexing_job,
        activate_index_revision,
        cleanup_old_vector_revision,
        cleanup_audit_logs,
    ]
    redis_settings: RedisSettings = get_arq_redis_settings()
