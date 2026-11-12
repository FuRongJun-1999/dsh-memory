"""Source-level in-memory mutations; expected assertion failures only."""
import argparse,io,json,types,unittest
from pathlib import Path
from . import test_csre_correctness as guards

MUTATIONS=[
 ('M0_negative_gate','if neg_gate > 0 and self.negative_hit(', 'if False and self.negative_hit(', 'test_negative_gate_filters_before_top_k_and_backfills'),
 ('M1_warm_freshness','if self.matrix is not None and self._source_metadata == current:', 'if self.matrix is not None:', 'test_changed_content_invalidates_new_and_already_loaded_engines'),
 ('M2_source_identity','identity = ["sqlite", os.path.normcase(os.path.realpath(path))]', 'identity = ["sqlite", "shared-source"]', 'test_identical_rows_from_another_database_are_not_accepted'),
 ('M3_row_hash','"rows_hash": fingerprint(rows)', '"rows_hash": "ignored"', 'test_changed_content_invalidates_new_and_already_loaded_engines'),
 ('M4_readonly_source','sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)', 'sqlite3.connect(str(path))', 'test_missing_database_is_not_created'),
 ('M5_nonfinite_vectors','not np.isfinite(matrix).all()', 'False', 'test_invalid_shape_and_nonfinite_vectors_are_rejected'),
]
def run_mutations():
    path=Path(guards.WISDOM)/'csre.py';source=path.read_text(encoding='utf8');original=guards.Csre;records=[]
    for name,before,after,test in MUTATIONS:
        assert source.count(before)==1,(name,'mutation location must be unique')
        module=types.ModuleType('csre_memory_mutation');module.__file__=str(path)
        exec(compile(source.replace(before,after),str(path),'exec'),module.__dict__)
        try:
            guards.Csre=module.Csre
            result=unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite([guards.CsreTests(test)]))
            killed=len(result.failures)==1 and not result.errors and not result.skipped
            records.append({'mutation':name,'expected_assertion':test,'killed_by_expected_assertion':killed,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped)})
            assert killed,(name,records[-1])
        finally:guards.Csre=original
    assert path.read_text(encoding='utf8')==source,'Source file changed'
    return records
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
    baseline=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(guards.CsreTests));assert baseline.wasSuccessful()
    rows=run_mutations();value={'baseline_tests':baseline.testsRun,'mutations':rows,'killed':len(rows),'source_untouched':True}
    if a.output:a.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(value,ensure_ascii=False))
