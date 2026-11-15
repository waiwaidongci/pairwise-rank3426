import {useEffect,useState} from 'react';
import {studyStore,loadStudies} from '../stores/studies';
import {inputStore,loadInputs,addConcept,savePair} from '../stores/inputs';
import {withdrawalStore,loadWithdrawals} from '../stores/withdrawals';
import {researchStore,loadRuns,loadProposals} from '../stores/research';
import * as withdrawalsApi from '../api/withdrawals';
import {authStore,canEdit} from '../stores/auth';
import {useTask} from '../hooks/useTask';
import PageHeading from '../components/common/PageHeading';
import ErrorNotice from '../components/common/ErrorNotice';
import StudySelect from '../components/StudySelect';
import type {Pair} from '../types/domain';

export default function Sources(){
  const {selected}=studyStore.use();
  const {concepts,pairs}=inputStore.use();
  const {sources,impact}=withdrawalStore.use();
  const {runs,proposals}=researchStore.use();
  const {user}=authStore.use();
  const {error,busy,perform}=useTask();
  const [edit,setEdit]=useState<Pair|null>(null);
  const [success,setSuccess]=useState('');

  useEffect(()=>{perform(loadStudies);perform(loadRuns);perform(loadProposals)},[]);
  useEffect(()=>{
    if(selected){
      setEdit(null);setSuccess('');
      perform(()=>loadInputs(selected));
      perform(()=>loadWithdrawals(selected));
    }
  },[selected]);

  const title=(id:number)=>{const c=concepts.find(c=>c.id===id);return c?c.code+' '+c.title:String(id)};
  const studySources=sources.filter(s=>s.study_id===selected);
  const withdrawnSet=new Set(studySources.filter(s=>s.withdrawn).map(s=>s.source));
  const activePairs=pairs.filter(p=>!p.quarantined);
  const quarantinedPairs=pairs.filter(p=>p.quarantined);
  const studyRuns=runs.filter(r=>r.study_id===selected);
  const affectedRuns=(impact?.invalidated_runs||[]).filter(r=>r.study_id===selected);
  const affectedProposals=(impact?.halted_proposals||[]).filter(p=>studyRuns.some(r=>r.id===p.run_id));
  const activeVotes=activePairs.reduce((n,p)=>n+p.left_wins+p.right_wins,0);

  const doWithdraw=(form:HTMLFormElement)=>{
    const d=new FormData(form);
    const source=String(d.get('source')||'').trim();
    if(!source)return;
    perform(async()=>{
      const res=await withdrawalsApi.withdraw({study_id:selected,source,reason:String(d.get('reason')||'')});
      form.reset();
      await Promise.all([loadInputs(selected),loadWithdrawals(selected),loadRuns(),loadProposals()]);
      setSuccess(res.repeated
        ? `来源「${source}」此前已撤回，未重复扣票；隔离票、失效研究与停发提案保持原状态。`
        : `来源「${source}」已撤回：隔离${res.quarantined_pairs}条比较、${res.quarantined_votes}票；失效研究${res.invalidated_run_ids.length}项；停发提案${res.halted_proposal_ids.length}份。混合旧票已整行隔离，未做分摊猜测。`);
    });
  };

  return <>
  <PageHeading no="02" title="票数核对" sub="一次独立成对选择计为一票；按来源留明细，来源撤回只扣除该来源贡献。"/>
  <StudySelect/>
  <ErrorNotice error={error}/>{success&&<p role="status" className="success">{success}</p>}
  <section className="input-spread">
  <div>
  <h2 className="ruled-title">匿名作品名录 <small>{concepts.length}项</small></h2>
  <div className="concept-index">{concepts.map(c=>
  <div key={c.id}>
  <b>{c.code}</b>
  <span>{c.title}<small>{c.medium}</small></span>
  </div>)}</div>{!concepts.length&&<p className="empty">请先登记至少两项作品，再录入比较票数。</p>}{canEdit(user)&&<details className="edit-fold">
  <summary>＋ 登记作品方案</summary>
  <form onSubmit={e=>{e.preventDefault();const f=e.currentTarget,d=new FormData(f);perform(async()=>{await addConcept({...Object.fromEntries(d),study_id:selected},selected);f.reset();setSuccess('作品已登记，可录入新的成对票数。')})}}>
  <label>作品编号<input name="code" minLength={2} required/></label>
  <label>匿名标题<input name="title" minLength={2} required/></label>
  <label>媒介<input name="medium"/></label>
  <button disabled={busy}>登记作品</button>
  </form>
  </details>}<aside className="margin-note">
  <b>核对边界</b>
  <p>自比、负票、非整数、空票边和重复无向边会被拒绝。零胜票可以存在，只要该对总票数为正。</p>
  <p>新票按来源逐条登记；某来源撤回时只隔离该来源的票数行，其他来源保留。已混合且无法拆分的旧票整行隔离，不猜测分摊。</p>
  </aside>
  </div>
  <div>
  <h2 className="ruled-title">比较票数台账 <small>{activePairs.length}对可用 / {quarantinedPairs.length}对隔离 · {activeVotes.toLocaleString()}票可用</small></h2>
  {canEdit(user)&&<details className="edit-fold" open={!!edit}>
  <summary>{edit?'编辑比较 #'+edit.id:'＋ 录入一组成对票数'}</summary>
  <form key={edit?.id||'new'} className="form-grid" onSubmit={e=>{e.preventDefault();const d=new FormData(e.currentTarget);perform(async()=>{await savePair({study_id:selected,left_id:Number(d.get('left_id')),right_id:Number(d.get('right_id')),left_wins:Number(d.get('left_wins')),right_wins:Number(d.get('right_wins')),source:d.get('source')},selected,edit?.id);setEdit(null);setSuccess('票数已保存；已有研究快照不会被改写。')})}}>
  <label>左侧作品<select name="left_id" defaultValue={edit?.left_id||concepts[0]?.id}>{concepts.map(c=>
  <option key={c.id} value={c.id}>{c.code} {c.title}</option>)}</select></label>
  <label>右侧作品<select name="right_id" defaultValue={edit?.right_id||concepts[1]?.id}>{concepts.map(c=>
  <option key={c.id} value={c.id}>{c.code} {c.title}</option>)}</select></label>
  <label>选择左侧的票数<input name="left_wins" type="number" min="0" max="1000" step="1" defaultValue={edit?.left_wins||0} required/></label>
  <label>选择右侧的票数<input name="right_wins" type="number" min="0" max="1000" step="1" defaultValue={edit?.right_wins||0} required/></label>
  <label className="full">票数来源<input name="source" required placeholder="例如：滨河匿名成对票数_20261112.csv；新票须标注来源以便撤回时精确扣除" defaultValue={edit?.source||''}/></label>
  <div className="button-row">
  <button className="primary" disabled={busy}>保存票数</button>{edit&&<button type="button" onClick={()=>setEdit(null)}>取消编辑</button>}</div>
  </form>
  </details>}

  {canEdit(user)&&<details className="edit-fold withdrawal-fold">
  <summary>⊘ 撤回某个票数来源（只扣该来源，其他来源保留）</summary>
  <form className="form-grid" onSubmit={e=>{e.preventDefault();doWithdraw(e.currentTarget)}}>
  <label>撤回来源<input name="source" list="source-list" required placeholder="选择或输入要撤回的来源标识"/>
  <datalist id="source-list">{studySources.map(s=><option key={s.source} value={s.source}/>)}</datalist></label>
  <label>撤回说明（可选）<input name="reason" maxLength={600} placeholder="留档说明，例如：上游通知该批次作废"/></label>
  <div className="button-row"><button className="primary danger-button" disabled={busy}>确认撤回并贯穿处理</button></div>
  <p className="muted">撤回将隔离该来源全部票数行；排队、运行中及已完成的受影响研究立即失效，已批准提案停止分发。重复撤回同一来源不会重复扣票。</p>
  </form>
  </details>}

  <div className="table-scroll">
  <table>
  <thead>
  <tr>
  <th>作品对</th>
  <th>左票</th>
  <th>右票</th>
  <th>总票</th>
  <th>来源</th>
  <th>状态</th>{canEdit(user)&&<th/>}</tr>
  </thead>
  <tbody>{pairs.map(p=>
  <tr key={p.id} className={p.quarantined?'quarantined-row':''}>
  <td>
  <b>{title(p.left_id)}</b>
  <small>对 {title(p.right_id)}</small>
  </td>
  <td>{p.left_wins}</td>
  <td>{p.right_wins}</td>
  <td>{p.left_wins+p.right_wins}</td>
  <td className="source-cell">{p.source||<i>未标注</i>}{withdrawnSet.has(p.source)&&!p.quarantined&&<small className="warn-text">来源已撤回</small>}</td>
  <td>{p.quarantined?<span className="status quarantined">已隔离 · 不猜分摊</span>:<span className="status active-pair">可用</span>}</td>
  {canEdit(user)&&<td>{!p.quarantined&&<button className="small-button" onClick={()=>setEdit(p)}>编辑</button>}</td>}</tr>)}</tbody>
  </table>
  </div>{!pairs.length&&<p className="empty">还没有票数。录入一对作品的两侧计数，逐步连通比较网络。</p>}

  {quarantinedPairs.length>0&&<div className="withdrawal-panel">
  <h3>隔离票（{quarantinedPairs.length}对 / {quarantinedPairs.reduce((n,p)=>n+p.left_wins+p.right_wins,0)}票）</h3>
  <p className="muted">这些比较随撤回来源整行隔离；若一行混合了多个来源且无法拆分，整票保留在台账中但不进入任何新快照，也不参与可用票数统计。</p>
  </div>}
  {(affectedRuns.length>0||affectedProposals.length>0)&&<div className="withdrawal-panel">
  <h3>撤回影响范围</h3>
  {affectedRuns.length>0&&<>
  <p className="eyebrow">受影响研究（{affectedRuns.length}项 · 排队/运行中/已完成均已失效）</p>
  <ul className="impact-list">{affectedRuns.map(r=><li key={r.id}><b>#{r.id} {r.name}</b><span>{r.invalidated_reason}</span></li>)}</ul></>}
  {affectedProposals.length>0&&<>
  <p className="eyebrow">受影响提案（{affectedProposals.length}份 · 已停止分发）</p>
  <ul className="impact-list">{affectedProposals.map(p=><li key={p.id}><b>#{p.id} {p.name}</b><span>{p.halt_reason}</span></li>)}</ul></>}
  </div>}
  </div>
  </section>
  </>}
