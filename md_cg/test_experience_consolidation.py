"""Meaningful source/condition/history boundaries; no model or production data."""
import copy,json,tempfile
from pathlib import Path
from .mdcos import MdCGOS
from .memory_rsi import MemoryRSILab,create_sandbox,canonical,digest
from .experience_consolidation import VerifiedExperiences,context_verdict,RECEIPT_KIND,META
from .signer import HmacLocalSigner

def main():
    base=Path(tempfile.mkdtemp(prefix='experience_consolidation_'))
    graph=create_sandbox(base/'lab');cg=MdCGOS(str(graph));lab=MemoryRSILab(cg,base/'lab',enabled=True)
    signer=HmacLocalSigner(key=b'offline-unit-test-authority',key_file=str(base/'unused.key'))
    verifier=lambda e:signer.verify(canonical(e['payload']).encode('utf8'),e['signature'])
    adapter=VerifiedExperiences(cg,base/'lab',enabled=True,receipt_verifier=verifier)
    checks=[]
    def check(name,cond):
        checks.append({'name':name,'passed':bool(cond)});print(('PASS ' if cond else 'FAIL ')+name)
    def raises(name,fn):
        try:fn()
        except (ValueError,PermissionError):check(name,True)
        else:check(name,False)
    def experience(task,passed=True,context=None,claims=None,used=None):
        context=context if context is not None else {'language':'python','ownership':'isolated'}
        trace={'scope':'unit-copy-contract','conditions':['offline'], 'context':context,'task_id':task,
          'candidate_sha256':digest(['candidate',task]),'outcomes':{'passed':passed},
          'candidate_note':{'rule':'copy nested data without aliasing','negative_conditions':['shared ownership']},
          'events':[{'id':'e','kind':'error','text':'nested data aliases'},
             {'id':'a','kind':'action','text':'copy.deepcopy(template)','error_id':'e'},
             {'id':'c','kind':'check','text':'independent nested mutation check','source':'tool','passed':passed,'error_id':'e','action_id':'a'}]}
        tid=lab.record_experience(trace);raw=json.loads(cg.get(tid)['content'])
        p={'kind':RECEIPT_KIND,'trace_id':tid,'trace_hash':digest(raw),'scope':trace['scope'],
           'task_id':task,'candidate_sha256':trace['candidate_sha256'],'passed':passed,'context':context,
           'checked_claims':claims if claims is not None else {'ownership_effect':'independent nested snapshot'},
           'used_capsule_ids':used or []}
        e={'payload':p,'signature':signer.sign(canonical(p).encode('utf8'))}
        return tid,e
    raises('default_disabled',lambda:VerifiedExperiences(cg,base/'lab',receipt_verifier=verifier))
    raises('missing_trusted_verifier',lambda:VerifiedExperiences(cg,base/'lab',enabled=True,receipt_verifier=None))
    raises('cannot_bless_an_existing_non_sandbox_graph',lambda:VerifiedExperiences(cg,base,enabled=True,receipt_verifier=verifier))
    t1,e1=experience('A1');t2,e2=experience('A2')
    bad=copy.deepcopy(e1);bad['payload']['passed']=False
    raises('changed_receipt_rejected',lambda:adapter.attach_receipt(t1,bad))
    bad=copy.deepcopy(e1);bad['payload']['task_id']='different';bad['signature']=signer.sign(canonical(bad['payload']).encode())
    raises('even_signed_receipt_must_bind_task',lambda:adapter.attach_receipt(t1,bad))
    bad=copy.deepcopy(e1);bad['payload']['candidate_sha256']='0'*64;bad['signature']=signer.sign(canonical(bad['payload']).encode())
    raises('even_signed_receipt_must_bind_candidate',lambda:adapter.attach_receipt(t1,bad))
    r1=adapter.attach_receipt(t1,e1);r2=adapter.attach_receipt(t2,e2)
    check('receipt_idempotent',adapter.attach_receipt(t1,e1)==r1)
    check('one_source_insufficient',adapter.consolidate([t1])['reason']=='insufficient_distinct_source_tasks')
    check('duplicate_source_does_not_inflate_count',adapter.consolidate([t1,t1])['reason']=='insufficient_distinct_source_tasks')
    tmissing,_=experience('missing')
    check('missing_receipt_deferred',adapter.consolidate([t1,tmissing])['status']=='deferred')
    tf,ef=experience('failed',passed=False);adapter.attach_receipt(tf,ef)
    check('failed_action_not_consolidated',adapter.consolidate([t1,tf])['reason']=='failed_or_unbound_action')
    before={t:cg.get(t)['content'] for t in [t1,t2]}
    preview=adapter.consolidate([t1,t2]);check('preview_has_no_capsule_write',preview['status']=='candidate' and not adapter._nodes('capsule'))
    created=adapter.consolidate([t1,t2],apply=True);cid=created['node_id'];v1=cg.get(cid)
    check('two_sources_create_source_supported_candidate',created['status']=='source_supported_candidate')
    check('not_promoted_to_verified_generic_fact',v1['frontmatter']['verification_state']=='unverified' and not v1['frontmatter'][META]['knowledge_verified'])
    check('unverified_model_summary_not_copied_into_capsule','copy nested data without aliasing' not in v1['content'])
    check('source_ids_preserved',v1['frontmatter'][META]['source_experience_ids']==sorted([t1,t2]))
    check('raw_experiences_unchanged',all(cg.get(t)['content']==before[t] for t in before))
    check('repeat_consolidation_idempotent',adapter.consolidate([t1,t2],apply=True)['status']=='duplicate')
    t3,e3=experience('A3');adapter.attach_receipt(t3,e3)
    updated=adapter.consolidate([t2,t3],apply=True);cid2=updated['node_id'];v2=cg.get(cid2)
    check('new_support_appends_version',updated['version']==2 and cg.get(cid)['content']==v1['content'])
    check('new_support_retains_old_source',set(v2['frontmatter'][META]['source_experience_ids'])=={t1,t2,t3})
    tx,ex=experience('different-context',context={'language':'python','ownership':'shared'});adapter.attach_receipt(tx,ex)
    check('different_context_not_automatically_generalized',adapter.consolidate([t1,tx])['reason']=='different_scopes_are_not_automatically_generalized')
    tx,ex=experience('contradictory',claims={'ownership_effect':'shared live reference'});adapter.attach_receipt(tx,ex)
    check('contradictory_checked_claims_deferred',adapter.consolidate([t1,tx])['reason']=='contradictory_checked_claims')
    tx,ex=experience('unrelated-claim',claims={'different_unrepeated_property':True});adapter.attach_receipt(tx,ex)
    check('different_single_source_claims_not_presented_as_repeated_evidence',adapter.consolidate([t1,tx])['reason']=='no_explicit_checked_claims')
    te,ee=experience('expired-source');adapter.attach_receipt(te,ee);raw=cg.get(te)
    cg.add(te,raw['content'],layer='contextual',memory_rsi=raw['frontmatter']['memory_rsi'],effective_until='2000-01-01T00:00:00Z')
    check('expired_source_is_withheld_even_with_valid_signature',adapter.consolidate([t1,te])['status']=='deferred')
    check('all_conditions_required',context_verdict({'a':1,'b':2},{'a':1})['state']=='DEFER')
    check('False_does_not_match_zero',context_verdict({'a':False},{'a':0})['state']=='REJECT')
    good=adapter.recall('nested copy snapshot',{'language':'python','ownership':'isolated'})
    check('source_supported_candidate_recalled',cid2 in good['delivered_ids'])
    bad=adapter.recall('nested copy snapshot',{'language':'python','ownership':'shared'})
    check('known_out_of_scope_experience_withheld',not bad['delivered_ids'] and any(x.get('state')=='REJECT' for x in bad['rejected']))
    missing=adapter.recall('nested copy snapshot',{'language':'python'})
    check('unknown_condition_is_not_assumed_true',not missing['delivered_ids'] and any(x.get('state')=='DEFER' for x in missing['rejected']))
    from .mdcos import est_tokens
    check('whole_public_envelope_is_budgeted',est_tokens(json.dumps(good,ensure_ascii=False,separators=(',',':')))<=1000)
    tu,eu=experience('unrelated-feedback',passed=False);adapter.attach_receipt(tu,eu)
    raises('unassociated_feedback_rejected',lambda:adapter.feedback(cid2,tu))
    ts,es=experience('success-feedback',passed=True,used=[cid2]);adapter.attach_receipt(ts,es)
    check('success_does_not_automatically_generalize',adapter.feedback(cid2,ts)['status']=='unchanged')
    tb,eb=experience('failed-associated-B',passed=False,used=[cid2]);adapter.attach_receipt(tb,eb)
    disputed=adapter.feedback(cid2,tb);cid3=disputed['node_id']
    check('failed_associated_feedback_appends_disputed_version',disputed['status']=='disputed' and disputed['version']==3)
    check('feedback_retains_original_versions',cg.get(cid)['content']==v1['content'] and cg.get(cid2)['content']==v2['content'])
    check('old_version_cannot_bypass_failed_feedback',not adapter.recall('nested copy snapshot',{'language':'python','ownership':'isolated'})['delivered_ids'])
    check('old_support_cannot_silently_restore_after_failure',adapter.consolidate([t1,t2,t3],apply=True)['reason']=='prior_feedback_requires_independent_revalidation')
    rolled=adapter.rollback(cid3)
    check('rollback_is_append_only',rolled['status']=='rolled_back' and rolled['version']==4 and cg.get(cid3) is not None)
    # Use a separate scope to verify tampering independently of the rollback.
    raw=cg.get(t1);changed=json.loads(raw['content']);changed['candidate_note']['rule']='changed unsupported summary'
    cg.add(t1,canonical(changed),layer='contextual',memory_rsi=raw['frontmatter']['memory_rsi'])
    check('changed_source_prevents_new_consolidation',adapter.consolidate([t1,t2])['status']=='deferred')
    class Denied:
        def require_op(self,op):raise PermissionError('denied '+op)
    cg.principal=Denied()
    raises('read_permission_still_required',lambda:adapter.recall('copy',{}))
    raises('write_permission_still_required',lambda:adapter.attach_receipt(t2,e2))
    cg.principal=None;cg.close()
    failed=[r for r in checks if not r['passed']]
    print(json.dumps({'passed':not failed,'checks':len(checks),'failures':failed,'state':str(base),'LLM_calls':0}))
    return 1 if failed else 0
if __name__=='__main__':raise SystemExit(main())
