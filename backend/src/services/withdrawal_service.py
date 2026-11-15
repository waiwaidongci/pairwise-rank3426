"""来源撤回贯穿票数台账、冻结研究与补票分发。

口径：
- 新票按来源留明细，撤回只把该来源贡献的票数行整行隔离，其他来源行保留。
- 已混合且无法按来源拆分的旧票不猜分摊：隔离整张混合行，台账仍可见。
- 受影响的排队/运行中/已完成研究一律失效；已批准提案停止分发。
- 重复撤回不重复扣票：同一(研究, 来源)已隔离则直接返回既有结果。
"""
from sqlalchemy import select,func
from fastapi import HTTPException
from src.models import PairCount,RankingRun,ReviewProposal
from src.services.study_service import get_study
from src.constants.enums import RunStatus,ProposalStatus

ACTIVE_RUN_STATUSES=(RunStatus.QUEUED,RunStatus.RUNNING,RunStatus.COMPLETED)

def list_withdrawals(db):
    """汇总每个研究下每个来源的隔离状态，供页面列出受影响范围。"""
    rows=db.execute(
        select(PairCount.study_id,PairCount.source,
               func.count().label('pair_count'),
               func.coalesce(func.sum(PairCount.left_wins+PairCount.right_wins),0).label('votes'),
               func.max(PairCount.quarantined).label('any_quarantined'))
        .group_by(PairCount.study_id,PairCount.source)
        .order_by(PairCount.study_id,PairCount.source)
    ).all()
    return [{'study_id':r.study_id,'source':r.source,'pair_count':r.pair_count,
             'votes':int(r.votes),'withdrawn':bool(r.any_quarantined)} for r in rows]

def withdrawal_impact(db,study_id=None):
    """页面用：列出失效研究、停发提案、隔离票三组明细。"""
    q=select(PairCount).where(PairCount.quarantined.is_(True)).order_by(PairCount.study_id,PairCount.id)
    if study_id is not None:q=q.where(PairCount.study_id==study_id)
    quarantined=db.scalars(q).all()
    rq=select(RankingRun).where(RankingRun.status==RunStatus.INVALIDATED).order_by(RankingRun.id)
    pq=select(ReviewProposal).where(ReviewProposal.status==ProposalStatus.HALTED).order_by(ReviewProposal.id)
    if study_id is not None:
        rq=rq.where(RankingRun.study_id==study_id)
        halt_ids=select(ReviewProposal.id).join(RankingRun,RankingRun.id==ReviewProposal.run_id).where(RankingRun.study_id==study_id)
        pq=pq.where(ReviewProposal.id.in_(halt_ids))
    runs=db.scalars(rq).all()
    proposals=db.scalars(pq).all()
    return {'quarantined_pairs':quarantined,'invalidated_runs':runs,'halted_proposals':proposals}

def withdraw_source(db,study_id,source,reason=''):
    study=get_study(db,study_id)
    source=(source or '').strip()
    if not source:raise HTTPException(422,'请填写要撤回的票数来源标识')
    targets=db.scalars(select(PairCount).where(
        PairCount.study_id==study_id,PairCount.source==source,
        PairCount.quarantined.is_(False)).order_by(PairCount.id)).all()
    # 幂等：该来源已全部隔离（或从未出现）时不再扣票、不重复失效。
    existing=db.scalar(select(func.count()).select_from(PairCount).where(
        PairCount.study_id==study_id,PairCount.source==source)) or 0
    if not targets:
        return {'study_id':study_id,'source':source,'reason':reason,
                'repeated':existing>0,'quarantined_pair_ids':[],
                'quarantined_pairs':0,'quarantined_votes':0,
                'invalidated_run_ids':[],'halted_proposal_ids':[]}
    pair_ids=[]
    votes=0
    for p in targets:
        # 混合旧票无法按来源拆分：整行隔离，不猜测该来源在其中占多少票。
        p.quarantined=True
        pair_ids.append(p.id)
        votes+=p.left_wins+p.right_wins
    detail=f"来源「{source}」撤回，冻结快照引用该来源票数，依据不再可用"
    if reason:detail=f"{detail}；撤回说明：{reason}"
    run_rows=db.scalars(select(RankingRun).where(
        RankingRun.study_id==study_id,
        RankingRun.status.in_(tuple(s for s in ACTIVE_RUN_STATUSES))).order_by(RankingRun.id)).all()
    run_ids=[]
    for run in run_rows:
        # 只有快照确实引用该来源的研究才失效；未引用的研究不受影响。
        refs=run.snapshot.get('pairs',[]) if isinstance(run.snapshot,dict) else []
        if any((p.get('source')==source and not p.get('quarantined',False)) for p in refs):
            run.status=RunStatus.INVALIDATED
            run.invalidated_reason=detail[:600]
            run_ids.append(run.id)
    halt_text=f"依据研究因来源「{source}」撤回而失效，已批准提案停止分发"
    if reason:halt_text=f"{halt_text}；撤回说明：{reason}"
    proposal_rows=db.scalars(select(ReviewProposal).where(
        ReviewProposal.run_id.in_(run_ids),
        ReviewProposal.status.in_((ProposalStatus.DRAFT,ProposalStatus.APPROVED))).order_by(ReviewProposal.id)).all() if run_ids else []
    proposal_ids=[]
    for pr in proposal_rows:
        # 已退回的历史决定保持不变；草稿与已批准一律停发，防止再被批准或下载。
        pr.status=ProposalStatus.HALTED
        pr.halt_reason=halt_text[:600]
        proposal_ids.append(pr.id)
    db.commit()
    return {'study_id':study_id,'source':source,'reason':reason,'repeated':False,
            'quarantined_pair_ids':pair_ids,'quarantined_pairs':len(pair_ids),
            'quarantined_votes':votes,'invalidated_run_ids':run_ids,
            'halted_proposal_ids':proposal_ids}
