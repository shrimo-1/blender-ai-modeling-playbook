#!/usr/bin/env python3
from __future__ import annotations
import contextlib, io, json, shutil, sys, tempfile
from pathlib import Path
from contextlib import contextmanager

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import silhouette_diff as sd
import stage_guard as sg
import unit_roundtrip_check as urc

CHECKS = 0
@contextmanager
def scratch_dir():
    root = Path(tempfile.mkdtemp(prefix=".selftest_tmp_", dir=REPO))
    try: yield root
    finally: shutil.rmtree(root, ignore_errors=True)

def expect(label, actual, wanted):
    global CHECKS; CHECKS += 1
    if actual != wanted: raise AssertionError(f"{label}: 期望 {wanted!r}，实得 {actual!r}")
    print(f"  [ok] {label}: {actual!r}")

def test_roundtrip():
    print("== unit_roundtrip_check ==")
    good = REPO/'examples'/'roundtrip.spec.json'; bad = REPO/'examples'/'roundtrip_bad.spec.json'
    r = urc.build_report(urc.load_spec(good), None)
    expect("自洽口径", r['verdict'], 'PASS'); expect("7 anchors", len(r['anchors']), 7)
    expect("错误口径", urc.build_report(urc.load_spec(bad), None)['verdict'], 'FAIL')
    spec = urc.load_spec(good); spec['anchors'] = spec['anchors'][:3]
    expect("不足 5 anchors", urc.build_report(spec, None)['verdict'], 'UNKNOWN')

    with scratch_dir() as tmp:
        base = json.loads(good.read_text(encoding='utf-8'))
        cases = [
            ("bad number", ("geometry","mm_per_px"), "abc"),
            ("zero width", ("camera","resolution"), [0,804]),
            ("negative tol", ("tol_px",), -0.1),
            ("unsupported fit", ("camera","sensor_fit"), "VERTICAL"),
            ("non-square pixels", ("camera","pixel_aspect"), [1,2]),
            ("nonzero shift", ("camera","shift"), [0.1,0]),
        ]
        for label, path, value in cases:
            data = json.loads(json.dumps(base))
            cursor = data
            for key in path[:-1]: cursor = cursor[key]
            cursor[path[-1]] = value
            p = tmp/f"{label}.json"; p.write_text(json.dumps(data), encoding='utf-8')
            try: urc.load_spec(p)
            except urc.SpecError: got = 'SpecError'
            else: got = 'accepted'
            expect(label, got, 'SpecError')

def test_silhouette():
    print("== silhouette_diff ==")
    base = {"name":"a","width":296,"rows":[[10,100],[12,102],[15,105],None,[20,120]]}
    def run(rows, width=296, rr=None, tol=1, thin=6):
        a = {"name":"a","width":296,"rows":[tuple(r) if r else None for r in base['rows']]}
        b = {"name":"b","width":width,"rows":[tuple(r) if r else None for r in rows]}
        return sd.diff_rows(a,b,tol,thin,rr)
    expect("same", run(base['rows'])['verdict'], 'PASS')
    expect("fail", run([[10,100],[12,102],[15,105],None,[25,120]])['verdict'], 'FAIL')
    expect("thin unknown", run([[10,100],[12,102],[15,105],None,[40,43]])['verdict'], 'UNKNOWN')
    expect("presence fail", run([[10,100],[12,102],[15,105],None,None])['verdict'], 'FAIL')
    empty = {"name":"e","width":296,"rows":[]}
    expect("0 rows -> UNKNOWN", sd.diff_rows(empty,empty,1,6,None)['verdict'], 'UNKNOWN')
    try: run(base['rows'], width=300)
    except sd.InputError: got='InputError'
    else: got='accepted'
    expect("width mismatch", got, 'InputError')
    for rr in [(4,3),(99,100),(-1,2)]:
        try: run(base['rows'], rr=rr)
        except sd.InputError: got='InputError'
        else: got='accepted'
        expect(f"bad range {rr}", got, 'InputError')
    for tol,thin in [(-1,6),(1,-1)]:
        try: run(base['rows'], tol=tol, thin=thin)
        except sd.InputError: got='InputError'
        else: got='accepted'
        expect(f"bad thresholds {tol}/{thin}", got, 'InputError')

def test_stage_guard():
    print("== stage_guard ==")
    with scratch_dir() as tmp:
        r=sg.guard('stage2',tmp); expect("new target", r['action'], 'write')
        target=tmp/'stage2.blend'; target.write_text('old',encoding='utf-8')
        expect("block", sg.guard('stage2',tmp)['action'], 'blocked')
        r=sg.guard('stage2',tmp,allow_overwrite=True)
        expect("backup name", Path(r['backup']).name, 'stage2_dev1.blend')
        expect("backup content", Path(r['backup']).read_text(), 'old')
        expect("main preserved before save", target.read_text(), 'old')
        target.write_text('v2'); r=sg.guard('stage2',tmp,allow_overwrite=True)
        expect("second backup", Path(r['backup']).name, 'stage2_dev2.blend')
        expect("main still v2", target.read_text(), 'v2')
        bad=tmp/'bad.blend'; bad.mkdir()
        try: sg.guard('bad',tmp,allow_overwrite=True)
        except ValueError: got='ValueError'
        else: got='accepted'
        expect("directory target rejected",got,'ValueError')

def test_cli():
    print("== CLI ==")
    q=contextlib.redirect_stdout(io.StringIO()); e=contextlib.redirect_stderr(io.StringIO())
    good=REPO/'examples'/'roundtrip.spec.json'; bad=REPO/'examples'/'roundtrip_bad.spec.json'
    with q: expect("roundtrip PASS exit", urc.main(['--spec',str(good)]), 0)
    with q: expect("roundtrip FAIL exit", urc.main(['--spec',str(bad)]), 1)
    with scratch_dir() as tmp:
        a=tmp/'a.json'; b=tmp/'b.json'
        a.write_text(json.dumps({'width':10,'rows':[]}),encoding='utf-8'); b.write_text(json.dumps({'width':10,'rows':[]}),encoding='utf-8')
        with q: expect("empty silhouette exit", sd.main(['--a',str(a),'--b',str(b)]), 1)
        with q,e: expect("reversed range exit", sd.main(['--a',str(a),'--b',str(b),'--rows','2:1']), 2)

def main():
    test_roundtrip(); test_silhouette(); test_stage_guard(); test_cli()
    print(f"\n全部 {CHECKS} 项断言通过。")
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except AssertionError as exc:
        print(f"\n断言失败: {exc}", file=sys.stderr); sys.exit(1)
