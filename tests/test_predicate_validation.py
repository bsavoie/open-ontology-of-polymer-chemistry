"""Exact pinned relation validation never invents scientific associations."""
import copy
import tempfile
import unittest
from pathlib import Path

from oopc.graph import Graph, validate_predicate
from oopc.mcp import MCP
from oopc.release import build_release
from oopc.trace import TraceStore, import_replay
from oopc.vocabulary import get_ontology
from fixtures.access_replay import fixture_records


class PredicateValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.release = build_release(self.root / 'release', fixture_records(), get_ontology(), {})
        self.store = TraceStore(self.root)
        self.run = self.store.create(self.release)
        self.graph = Graph(self.release, self.run)

    def test_unknown_filters_fail_once_without_returned_or_traversed_records(self):
        for predicate in ('hasSynthesisRoute', 'Related', 'PolymerConcept', 'all'):
            for operation in (lambda p: self.graph.traverse('wop-000001', predicate=p),
                              lambda p: self.graph.search(predicate=p),
                              lambda p: self.graph.claims(predicate=p)):
                with self.subTest(predicate=predicate, operation=operation):
                    count = len(self.run.events()['events'])
                    with self.assertRaisesRegex(ValueError, 'describe_vocabulary'):
                        operation(predicate)
                    events = self.run.events()['events']
                    self.assertEqual(len(events), count + 1)
                    event = events[-1]
                    self.assertEqual(event['status'], 'error')
                    for key in ('result_ids', 'traversed_edges', 'paths'):
                        self.assertEqual(event[key], [])
                    self.assertIn(repr(predicate), self.run.payload(event['payload_hash'])['error'])

    def test_known_empty_and_unspecified_filters_remain_successful(self):
        result = self.graph.traverse('wop-000001', predicate='hasProcess')
        self.assertEqual(result['paths'], [])
        self.assertEqual(result['edges'], [])
        self.assertEqual([r['@id'] for r in result['nodes']], ['wop-000001'])
        self.assertEqual(self.graph.search(predicate='hasProcess')['total'], 0)
        self.assertEqual(self.graph.claims(predicate='hasProcess')['total'], 0)
        for predicate in (None, '', 'related'):
            result = self.graph.traverse('wop-000001', predicate=predicate)
            self.assertEqual([e['@id'] for e in result['edges']], ['claim:ab'])
        self.assertTrue(all(e['status'] == 'ok' for e in self.run.events()['events']))

    def test_relation_declarations_come_from_the_pinned_release(self):
        ontology = get_ontology()
        term = copy.deepcopy(next(t for t in ontology['predicates'] if t['id'] == 'related'))
        term.update(id='customRelated', **{'@id':'customRelated', 'label':'Custom relation'})
        ontology['predicates'].append(term)
        ontology['terms'].append(copy.deepcopy(term))
        records = fixture_records()
        records[-1]['predicate'] = 'customRelated'
        release = build_release(self.root / 'custom-release', records, ontology, {})
        self.assertEqual(Graph(release).traverse('wop-000001', predicate='customRelated')['edges'], [records[-1]])
        with self.assertRaisesRegex(ValueError, 'Unknown relationship'):
            self.graph.traverse('wop-000001', predicate='customRelated')
        # Historical ontology shapes are accepted; classes and labels are not relation IDs.
        older = {'terms':[{'@id':'custom:id', 'kind':'relation', 'label':'Custom label'},
                          {'@id':'CustomClass', 'kind':'class'}]}
        validate_predicate(older, 'custom:id')
        for predicate in ('Custom label', 'CustomClass', 'related'):
            with self.assertRaises(ValueError):
                validate_predicate(older, predicate)

    def test_inspector_rejects_unknown_names_without_polluting_task_trace(self):
        for offset in (None, 0):
            with self.assertRaisesRegex(ValueError, 'describe_vocabulary'):
                self.graph.neighborhood('wop-000001', offset=offset, predicate='hasSynthesisRoute')
            empty = self.graph.neighborhood('wop-000001', offset=offset, predicate='hasProcess')
            self.assertEqual(empty['edges'], [])
        self.assertEqual(self.run.events()['events'], [])

    def test_mcp_error_guidance_and_exact_offline_replay(self):
        service = MCP(self.root, self.release, self.run.path.name)
        tools = {t['name']:t for t in service.tools()['tools']}
        for name in ('search', 'get_claims', 'traverse'):
            self.assertIn('describe_vocabulary', tools[name]['description'])
        response = service.handle({'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
            'params':{'name':'traverse', 'arguments':{'start':'wop-000001', 'predicate':'hasSynthesisRoute'}}})
        self.assertTrue(response['result']['isError'])
        self.assertIn('describe_vocabulary', response['result']['content'][0]['text'])
        self.assertEqual(len(self.run.events()['events']), 1)
        vocabulary = service.call('describe_vocabulary', {'term':'hasProcess'})
        self.assertEqual([t['id'] for t in vocabulary['terms']], ['hasProcess'])
        self.assertEqual(service.call('traverse', {'start':'wop-000001', 'predicate':'hasProcess'})['paths'], [])
        bundle = self.root / 'replay.zip'
        self.run.export(bundle)
        store = TraceStore(self.root / 'offline')
        replay = store.run(import_replay(bundle, store)['run_id'])
        self.assertEqual(replay.events(), self.run.events())
        self.assertEqual(replay.graph(), self.run.graph())
        for event in self.run.events()['events']:
            self.assertEqual(replay.payload(event['payload_hash']), self.run.payload(event['payload_hash']))
