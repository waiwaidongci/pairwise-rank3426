import json
from pathlib import Path
from sqlalchemy import select,func,update
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL,ARTIFACTS_DIR
from src.models import RankingRun
from src.services.study_service import get_study
from src.services.concept_service import list_concepts
from src.services.pair_service import list_pairs
from src.services.rank_bootstrap import analyze_ranking
from src.constants.enums import RunStatus
redis=Redis.from_url(REDIS_URL)
def list_runs(db):return db.scalars(select(RankingRun).order_by(RankingRun.id.desc())).all()
def get_run(db,id):
    item=db.get(RankingRun,id)
    if not item:raise HTTPException(404,'拟合任务不存在')
    return item

def create_run(db,data):
    study=get_study(db,data.study_id)
    if db.scalar(select(RankingRun).where(RankingRun.name==data.name)):raise HTTPException(409,'任务名称已存在')
    if db.scalar(select(func.count()).select_from(RankingRun).where(RankingRun.status.in_(['queued','running'])))>=3:raise HTTPException(429,'已有3项活动任务，请等待完成')
    concepts=[{k:getattr(c,k) for k in ('id','code','title','medium')} for c in list_concepts(db,study.id)]
    # 撤回确认后的新请求只能拿到仍可用的票数；隔离行不进入快照，也就不成为旧依据。
    active_pairs=[p for p in list_pairs(db,study.id) if not p.quarantined]
    if not active_pairs:raise HTTPException(422,'该研究的票数已全部随来源撤回隔离，没有可用于冻结的有效票数')
    pairs=[{k:getattr(c,k) for k in ('id','left_id','right_id','left_wins','right_wins','source','quarantined')} for c in active_pairs]
    snapshot={'study':{'id':study.id,'code':study.code,'name':study.name,'source_file':study.source_file},'concepts':concepts,'pairs':pairs}
    item=RankingRun(**data.model_dump(),snapshot=snapshot,status=RunStatus.QUEUED);db.add(item);db.commit()
    # Database is authoritative; worker scans queued tasks even if Redis notification fails.
    try:redis.lpush('pairwise:runs',str(item.id))
    except Exception:pass
    return item

def execute_run(db,id):
    item=get_run(db,id)
    if item.status not in ('queued','running'):return
    # 并发窗口一：排队后、开工前来源已撤回，则不再计算。
    if item.status==RunStatus.INVALIDATED:return
    item.status=RunStatus.RUNNING;db.commit()
    try:
        result=analyze_ranking(item.snapshot,item.ridge,item.repeats,item.seed,lambda:Path('/tmp/heartbeat').touch())
        # 并发窗口二：计算期间来源撤回。先复查一次。
        db.refresh(item)
        if item.status==RunStatus.INVALIDATED:return
        Path(ARTIFACTS_DIR).mkdir(exist_ok=True)
        artifact=Path(f'{ARTIFACTS_DIR}/run-{id}.json')
        artifact.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
        # 并发窗口三：复查之后、提交之前撤回仍可能到达。
        # 条件 UPDATE 保证只有仍处于 running 的任务才能写回 completed；
        # 撤回抢先把状态翻成 invalidated 时 rowcount=0，丢弃结果并删除产物。
        updated=db.execute(
            update(RankingRun)
            .where(RankingRun.id==id,RankingRun.status==RunStatus.RUNNING)
            .values(status=RunStatus.COMPLETED,result=result,error='')
        ).rowcount
        db.commit()
        if not updated:
            artifact.unlink(missing_ok=True)
    except Exception as exc:
        db.rollback()
        # 失败回写同样用条件 UPDATE，避免覆盖并发撤回留下的 invalidated。
        db.execute(
            update(RankingRun)
            .where(RankingRun.id==id,RankingRun.status==RunStatus.RUNNING)
            .values(status=RunStatus.FAILED,error=str(exc)[:600])
        );db.commit()
