"""Synthetic queue-isolation checks for the installed RQ 1.15 registry shape."""
import sys
import types
import unittest
from unittest.mock import patch
from darkbrown.migration.runtime_queue import verify_idle_site


class QueueTests(unittest.TestCase):
    def run_gate(self, additional=None):
        own = types.SimpleNamespace(id='own', kwargs={'site': 'test.invalid', 'user': 'Administrator',
                          'method': 'darkbrown.migration.rehearsal.run'})
        jobs = {'own': own}
        if additional: jobs['other'] = types.SimpleNamespace(id='other', kwargs=additional)
        class Registry:
            def __init__(self, name, connection): self.key = 'registry:' + name
            def get_job_ids(self):
                raise AssertionError('Registry helper would mutate state by running cleanup')
        connection = types.SimpleNamespace(zrange=lambda *a: [k.encode() for k in jobs])
        queue = types.SimpleNamespace(name='bench:long', get_job_ids=lambda: [])
        background = types.ModuleType('frappe.utils.background_jobs')
        background.get_queues = lambda connection: [queue]
        background.get_redis_conn = lambda: connection
        background.is_queue_accessible = lambda queue: True
        rq = types.ModuleType('rq'); rq.get_current_job = lambda: own
        rq.Worker = types.SimpleNamespace(all=lambda **kw: [types.SimpleNamespace(
            queues=[queue], get_current_job=lambda: own)])
        job_module = types.ModuleType('rq.job')
        job_module.Job = types.SimpleNamespace(fetch=lambda name, **kw: jobs[name])
        registries = types.ModuleType('rq.registry')
        for name in ('StartedJobRegistry','DeferredJobRegistry','ScheduledJobRegistry','FailedJobRegistry'):
            setattr(registries, name, Registry)
        frappe = types.SimpleNamespace(conf={'maintenance_mode':1, 'pause_scheduler':1},
            local=types.SimpleNamespace(site='test.invalid'), session=types.SimpleNamespace(user='Administrator'))
        with patch.dict(sys.modules, {'frappe.utils.background_jobs': background, 'rq': rq,
                                     'rq.job': job_module, 'rq.registry': registries}):
            return verify_idle_site(frappe)

    def test_only_current_authorised_job_is_exempt(self):
        self.assertTrue(self.run_gate()['idle'])
        with self.assertRaises(ValueError): self.run_gate({'site': 'test.invalid'})

    def test_unknown_job_owner_blocks(self):
        with self.assertRaises(ValueError): self.run_gate({'method': 'unknown'})

    def test_other_verified_site_does_not_block(self):
        self.assertTrue(self.run_gate({'site': 'another.invalid'})['idle'])


if __name__ == '__main__': unittest.main()
