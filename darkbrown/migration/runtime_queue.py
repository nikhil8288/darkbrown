"""Fail-closed live, read-only queue gate for an already quiesced site."""

def verify_idle_site(frappe):
    from frappe.utils.background_jobs import get_queues, get_redis_conn, is_queue_accessible
    from rq.job import Job
    from rq import Worker, get_current_job
    from rq.registry import StartedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry, FailedJobRegistry
    if not frappe.conf.get('maintenance_mode') or not frappe.conf.get('pause_scheduler'):
        raise ValueError('Pause site writes and scheduling before checking queues')
    connection=get_redis_conn(); site=str(frappe.local.site)
    current = get_current_job()
    own_id = None
    if (current and frappe.session.user == 'Administrator'
            and current.kwargs.get('site') == site
            and current.kwargs.get('user') == 'Administrator'
            and current.kwargs.get('method') == 'darkbrown.migration.rehearsal.run'):
        own_id = current.id
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
            # The installed RQ registry API has no cleanup=False option. Read
            # its sorted set directly so inspection cannot clean/mutate jobs.
            registered = registry(name=queue.name, connection=connection)
            ids.update(value.decode('utf-8') if isinstance(value, bytes) else value
                       for value in connection.zrange(registered.key, 0, -1))
        for job_id in ids:
            if job_id == own_id:
                continue
            job=Job.fetch(job_id,connection=connection)
            checked+=1
            if belongs(job):raise ValueError('Site has unfinished/retryable queue work')
    for worker in Worker.all(connection=connection):
        if not any(is_queue_accessible(q) for q in worker.queues):continue
        job=worker.get_current_job()
        if job and job.id != own_id and belongs(job):raise ValueError('Worker is executing a site job')
    return {'site':site,'idle':True,'pending_jobs_checked':checked}
