import json
import unittest

from fastapi import HTTPException

from app.analysis_drawings import drawing_proposals, fibonacci_for_frame


def row(i, close, volume=10):
    return [1700000000+i*60, close, close+1, close-1, close, volume]


def context(rows):
    return {'primary':'1m', 'frames':[{'bars':rows, 'stale':False}]}


def select_all(prompt, payload):
    return json.dumps({'ids':[c['id'] for c in payload['candidates']]})


class DrawingProposalsTests(unittest.TestCase):
    def test_fibonacci_matches_native_chart_in_both_directions(self):
        for direction in (1,-1):
            closes = [108,106,101,104,108,112,116,119,117,115,111]
            rows = [row(i,110+direction*(p-110)) for i,p in enumerate(closes)]
            # The last candle can still change. It cannot set either anchor.
            rows[-1] = row(len(rows)-1,10000)
            frame = context(rows)['frames'][0]
            fib = fibonacci_for_frame(frame)
            start,end = (100,120) if direction==1 else (120,100)
            self.assertEqual(fib['points'],[{'time':rows[2][0],'price':start},{'time':rows[7][0],'price':end}])
            self.assertEqual([level['ratio'] for level in fib['levels']],[0,.236,.382,.5,.618,.786,1])
            self.assertAlmostEqual(fib['levels'][4]['price'],107.64 if direction==1 else 112.36)
            self.assertEqual([fib['levels'][i]['price'] for i in (0,3,-1)],[end,110,start])
            proposal = drawing_proposals(context(rows),'fibonacci',lambda *_:self.fail('deterministic grid'))['proposals'][0]
            self.assertEqual(proposal['fibonacci'],fib)
            self.assertEqual(proposal['lines'][0]['kind'],'fib')
            self.assertEqual(proposal['lines'][0]['points'],fib['points'])
            self.assertIsNone(fibonacci_for_frame(context(rows[:-1])['frames'][0]))

    def test_turns_and_strokes_are_confirmed_and_anchored(self):
        rows=[row(i,p) for i,p in enumerate([10,11,12,15,14,13,12,11,8,9,10,11,12,16,12,11,10,9,55])]
        result=drawing_proposals(context(rows),'levels',select_all)
        self.assertEqual([p['id'] for p in result['proposals']], ['swing-high','swing-low'])
        self.assertEqual(result['trace'][-1][0],rows[-2][0])
        lines=[p['lines'][0] for p in result['proposals']]
        self.assertEqual([l['points'][0]['price'] for l in lines],[17,7])
        strokes=drawing_proposals(context(rows),'strokes',select_all)['proposals'][0]['lines']
        self.assertEqual(len(strokes),2)
        self.assertEqual(strokes[0]['points'][1],strokes[1]['points'][0])
        self.assertGreaterEqual(strokes[0]['points'][1]['time']-strokes[0]['points'][0]['time'],4*60)
        self.assertEqual(strokes,drawing_proposals(context(rows),'strokes',select_all)['proposals'][0]['lines'])

    def test_out_of_set_or_malformed_reply_cannot_inject_drawings(self):
        rows=[row(i,p) for i,p in enumerate([10,11,13,16,15,10,9,11,12])]
        for reply in ('{"ids":["swing-high","custom"]}','{"ids":"swing-high"}','bad'):
            with self.assertRaises(HTTPException):
                drawing_proposals(context(rows),'levels',lambda *_:reply)
        self.assertEqual(drawing_proposals(context(rows),'levels',lambda *_:'{"ids":[]}')['proposals'],[])

    def test_volume_band_and_consolidation_use_observed_prices(self):
        rows=[row(i,100.1+(i%3)*.04,100) for i in range(32)]
        rows[0]=row(0,98,1)
        rows[1]=row(1,108,1)
        r=drawing_proposals(context(rows),'range',select_all)
        groups={g['id']:g for g in r['proposals']}
        self.assertEqual(set(groups),{'volume-band','consolidation'})
        closes={bar[4] for bar in rows}
        self.assertTrue(all(line['points'][0]['price'] in closes for line in groups['volume-band']['lines']))

    def test_short_flat_samples_do_not_call_agent(self):
        for focus in ('levels','range','strokes','fibonacci'):
            resp=drawing_proposals(context([row(1,100),row(2,100)]),focus,lambda *_:self.fail('no candidates'))
            self.assertEqual(resp['proposals'],[])
            self.assertEqual(resp['evaluated'],0)
