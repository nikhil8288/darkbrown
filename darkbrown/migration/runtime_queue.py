"""Fail-closed live, read-only queue gate for an already quiesced site."""

def verify_idle_site(frappe):
    from frappe.utils.background_jobs import get_queues, get_redis_conn, is_queue_accessible
    from rq.job import Job
    from rq import Worker
    from rq.registry import StartedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry, FailedJobRegistry
    if not frappe.conf.get('maintenance_mode') or not frappe.conf.get('pause_scheduler'):
        raise ValueError('Pause site writes and scheduling before checking queues')
    connection=get_redis_conn(); site=str(frappe.local.site)
    def belongs(job):
        owner=job.kwargs.get('site')
        if owner is None:
            # Unknown provenance cannot be silently classified as another site.
            raise ValueError('Queue job has no verified site ownership')
        return owner==site
    checked=0
    for queue in get_queues(connection):
        ids=set(queue.get_job_ids())
        for registry in [StartedJobRegistry,DeferredJobRegistry,ScheduledJobRegistry,FailedJobRegistry]:
            # cleanup=False avoids mutating RQ state during inspection.
            ids.update(registry(name=queue.name,connection=connection).get_job_ids(cleanup=False))
        for job_id in ids:
            job=Job.fetch(job_id,connection=connection)
            checked+=1
            if belongs(job):raise ValueError('Site has unfinished/retryable queue work')
    for worker in Worker.all(connection=connection):
        if not any(is_queue_accessible(q) for q in worker.queues):continue
        job=worker.get_current_job()
        if job and belongs(job):raise ValueError('Worker is executing a site job')
    return {'site':site,'idle':True,'pending_jobs_checked':checked}
