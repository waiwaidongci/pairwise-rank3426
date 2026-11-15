"""来源撤回贯穿链路的端到端验证（SQLite 内存库 + fake redis，不依赖 docker）。"""
import os,sys,uuid
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['DATABASE_URL']='sqlite+pysqlite:///:memory:'
os.environ['REDIS_URL']='redis://localhost:6379/0'
os.environ['SEED_DEMO']='false'
os.environ['ARTIFACTS_DIR']='/tmp/pairwise-test-artifacts'

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 每次测试进程开始前清空产物目录，避免上一轮磁盘残留干扰断言
import shutil
shutil.rmtree(os.environ['ARTIFACTS_DIR'],ignore_errors=True)

# 静态连接的内存 SQLite，供 app 与测试共享同一库
engine=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False},
                     poolclass=StaticPool)
TestSession=sessionmaker(bind=engine,expire_on_commit=False)

import src.config.database as dbmod
dbmod.engine=engine
dbmod.Session=TestSession

# fake redis：队列与限流不触网
class FakeRedis:
    def __init__(self,*a,**k):pass
    @classmethod
    def from_url(cls,*a,**k):return cls()
    def lpush(self,*a):return 1
    def brpop(self,*a,**k):return None
    def ping(self):return True
    def incr(self,*a):return 1
    def expire(self,*a):return True
import redis as redis_pkg
redis_pkg.Redis=FakeRedis
import src.services.run_service as rs
rs.redis=FakeRedis()

from fastapi.testclient import TestClient
from src.main import app
from src.config.database import Base,get_db
Base.metadata.create_all(engine)
from src.utils.security import hash_password
from src.models import User
from src.constants.enums import RunStatus,ProposalStatus

def override_get_db():
    with TestSession() as db:yield db
app.dependency_overrides[get_db]=override_get_db

@pytest.fixture(scope='session',autouse=True)
def users():
    with TestSession() as db:
        db.add_all([
            User(email='admin@xianxu.local',name='管理员',role='admin',password_hash=hash_password('pw123456')),
            User(email='analyst@xianxu.local',name='分析员',role='analyst',password_hash=hash_password('pw123456')),
            User(email='viewer@xianxu.local',name='观察员',role='viewer',password_hash=hash_password('pw123456')),
        ])
        db.commit()

@pytest.fixture
def client():
    return TestClient(app)

def token(client,email):
    r=client.post('/auth/login',json={'email':email,'password':'pw123456'})
    assert r.status_code==200,r.text
    return r.headers and r.json()['token']

def auth(t):return {'Authorization':'Bearer '+t}

@pytest.fixture
def analyst(client):return token(client,'analyst@xianxu.local')
@pytest.fixture
def admin(client):return token(client,'admin@xianxu.local')
@pytest.fixture
def viewer(client):return token(client,'viewer@xianxu.local')

@pytest.fixture
def study_setup(client,analyst):
    import uuid
    suffix=uuid.uuid4().hex[:8]
    h=auth(analyst)
    s=client.post('/studies',headers=h,json={'code':f'T-WD-{suffix}','name':'撤回链路研究','source_file':'src-a.csv','context':''})
    assert s.status_code==201,s.text
    sid=s.json()['id']
    concepts=[]
    for i,code in enumerate([f'C{suffix[:4].upper()}{i}' for i in (1,2,3)]):
        r=client.post('/concepts',headers=h,json={'study_id':sid,'code':code,'title':'作品'+code,'medium':''})
        assert r.status_code==201,r.text
        concepts.append(r.json()['id'])
    def add_pair(left,right,lw,rw,source):
        r=client.post('/pairs',headers=h,json={'study_id':sid,'left_id':left,'right_id':right,
                                               'left_wins':lw,'right_wins':rw,'source':source})
        assert r.status_code==201,r.text
        return r.json()
    # 两条来源 A 的票 + 一条来源 B 的票，构成连通三角
    pa1=add_pair(concepts[0],concepts[1],12,8,'source-A.csv')
    pa2=add_pair(concepts[1],concepts[2],11,9,'source-A.csv')
    pb1=add_pair(concepts[0],concepts[2],14,6,'source-B.csv')
    return sid,concepts,pa1,pa2,pb1

def _queue_run(client,h,sid,name):
    import uuid
    r=client.post('/runs',headers=h,json={'study_id':sid,'name':f'{name}-{uuid.uuid4().hex[:8]}','ridge':1.0,'repeats':50,'seed':42})
    assert r.status_code==201,r.text
    return r.json()

def test_full_withdrawal_lifecycle(client,analyst,admin,viewer,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha,hm,hv=auth(analyst),auth(admin),auth(viewer)

    # 1) 排队并真实完成一项研究
    run=_queue_run(client,ha,sid,'撤回前完成研究')
    from src.services.run_service import execute_run
    with TestSession() as db:execute_run(db,run['id'])
    r=client.get(f"/runs/{run['id']}",headers=ha).json()
    assert r['status']=='completed'
    assert len(r['snapshot']['pairs'])==3
    assert all('quarantined' in p for p in r['snapshot']['pairs'])

    # 2) 分析员提出提案，负责人批准，viewer 可下载
    p=client.post('/proposals',headers=ha,json={'run_id':run['id'],'name':'撤回前提案-'+uuid.uuid4().hex[:8],
        'left_id':concepts[0],'right_id':concepts[1],'extra_votes':30,'rationale':'名次范围重叠需要补票验证依据'})
    assert p.status_code==201,p.text
    pid=p.json()['id']
    rv=client.post(f'/proposals/{pid}/review',headers=hm,json={'status':'approved','reviewer_note':'同意安排补充评议五字'})
    assert rv.status_code==200,rv.text
    assert client.get(f'/proposals/{pid}/export',headers=hv).status_code==200

    # 3) 撤回来源 A
    w=client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'source-A.csv','reason':'上游批次作废'})
    assert w.status_code==200,w.text
    wd=w.json()
    assert wd['repeated'] is False
    assert sorted(wd['quarantined_pair_ids'])==sorted([pa1['id'],pa2['id']])
    assert wd['quarantined_votes']==40  # (12+8)+(11+9)
    assert wd['invalidated_run_ids']==[run['id']]
    assert wd['halted_proposal_ids']==[pid]

    # 4) 台账：A 行隔离，B 行保留
    pairs=client.get(f'/pairs?study_id={sid}',headers=ha).json()
    by_id={p['id']:p for p in pairs}
    assert by_id[pa1['id']]['quarantined'] is True
    assert by_id[pa2['id']]['quarantined'] is True
    assert by_id[pb1['id']]['quarantined'] is False
    assert by_id[pb1['id']]['source']=='source-B.csv'

    # 5) 研究失效，提案停发，导出被拒
    r2=client.get(f"/runs/{run['id']}",headers=ha).json()
    assert r2['status']=='invalidated' and 'source-A.csv' in r2['invalidated_reason']
    p2=client.get('/proposals',headers=ha).json()
    prop={x['id']:x for x in p2}[pid]
    assert prop['status']=='halted' and prop['halt_reason']
    assert client.get(f'/proposals/{pid}/export',headers=hv).status_code==409
    # 失效研究不能新建提案，也不能再审阅停发提案
    assert client.post('/proposals',headers=ha,json={'run_id':run['id'],'name':'不应成立',
        'left_id':concepts[0],'right_id':concepts[1],'extra_votes':30,'rationale':'失效依据上的提案必须被拒绝'}).status_code==409
    assert client.post(f'/proposals/{pid}/review',headers=hm,json={'status':'rejected','reviewer_note':'停发后不可覆盖决定'}).status_code==409

    # 6) 重复撤回幂等：不重复扣票
    w2=client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'source-A.csv','reason':''})
    assert w2.status_code==200
    assert w2.json()['repeated'] is True
    assert w2.json()['quarantined_pairs']==0 and w2.json()['invalidated_run_ids']==[]
    pairs_again=client.get(f'/pairs?study_id={sid}',headers=ha).json()
    assert sum(1 for p in pairs_again if p['quarantined'])==2

    # 7) 撤回后的新研究：快照只含 B，隔离行不成为旧依据
    run2=_queue_run(client,ha,sid,'撤回后新研究')
    assert len(run2['snapshot']['pairs'])==1
    assert run2['snapshot']['pairs'][0]['source']=='source-B.csv'

    # 8) 撤回来源禁录、隔离行禁编辑
    bad=client.post('/pairs',headers=ha,json={'study_id':sid,'left_id':concepts[1],'right_id':concepts[2],
                                              'left_wins':5,'right_wins':5,'source':'source-A.csv'})
    assert bad.status_code==409
    edit=client.put(f"/pairs/{pa1['id']}",headers=ha,json={'study_id':sid,'left_id':pa1['left_id'],'right_id':pa1['right_id'],
                                                            'left_wins':1,'right_wins':1,'source':'source-A.csv'})
    assert edit.status_code==409

    # 9) 影响面清单
    impact=client.get(f'/withdrawals/impact?study_id={sid}',headers=ha).json()
    assert {x['id'] for x in impact['quarantined_pairs']}=={pa1['id'],pa2['id']}
    assert [x['id'] for x in impact['invalidated_runs']]==[run['id']]
    assert [x['id'] for x in impact['halted_proposals']]==[pid]
    listing=client.get('/withdrawals',headers=ha).json()
    src={x['source']:x for x in listing if x['study_id']==sid}
    assert src['source-A.csv']['withdrawn'] is True and src['source-B.csv']['withdrawn'] is False

    # 10) 权限：viewer 不能撤回
    assert client.post('/withdrawals',headers=hv,json={'study_id':sid,'source':'source-B.csv','reason':''}).status_code==403

def test_queued_run_invalidated_and_worker_skips(client,analyst,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    run=_queue_run(client,ha,sid,'排队后被撤回')
    # 撤回发生在 worker 执行之前
    w=client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'source-A.csv','reason':''})
    assert w.json()['invalidated_run_ids']==[run['id']]
    from src.services.run_service import execute_run
    with TestSession() as db:execute_run(db,run['id'])  # 不应产生结果
    got=client.get(f"/runs/{run['id']}",headers=ha).json()
    assert got['status']=='invalidated' and got['result'] in ({},None)

def test_concurrent_withdrawal_during_execution_discards_result(client,analyst,study_setup,monkeypatch):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    run=_queue_run(client,ha,sid,'计算中并发撤回')
    import src.services.run_service as svc
    original=svc.analyze_ranking
    def withdrawing_analyze(*a,**k):
        result=original(*a,**k)
        # 模拟计算完成、提交前撤回到达
        with TestSession() as db2:
            from src.services.withdrawal_service import withdraw_source
            withdraw_source(db2,sid,'source-A.csv','计算期间撤回')
        return result
    monkeypatch.setattr(svc,'analyze_ranking',withdrawing_analyze)
    from src.services.run_service import execute_run
    with TestSession() as db:execute_run(db,run['id'])
    got=client.get(f"/runs/{run['id']}",headers=ha).json()
    assert got['status']=='invalidated'
    assert got['result'] in ({},None)
    assert not os.path.exists(f'{os.environ["ARTIFACTS_DIR"]}/run-{run["id"]}.json')

def test_withdrawal_after_refresh_before_commit_keeps_invalidated(client,analyst,study_setup,monkeypatch):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    run=_queue_run(client,ha,sid,'提交前瞬间撤回')
    from src.models import RankingRun
    from src.services.run_service import execute_run
    from src.services.withdrawal_service import withdraw_source
    from sqlalchemy.orm import Session as OrmSession
    original_refresh=OrmSession.refresh
    def racing_refresh(self,instance,*a,**k):
        original_refresh(self,instance,*a,**k)
        # 模拟 refresh 检查通过后、条件 UPDATE 提交前撤回到达（同一连接内完成）
        if isinstance(instance,RankingRun) and instance.id==run['id']:
            withdraw_source(self,sid,'source-A.csv','复查与提交之间撤回')
    monkeypatch.setattr(OrmSession,'refresh',racing_refresh)
    with TestSession() as db:execute_run(db,run['id'])
    got=client.get(f"/runs/{run['id']}",headers=ha).json()
    assert got['status']=='invalidated'
    assert got['result'] in ({},None)
    assert not os.path.exists(f'{os.environ["ARTIFACTS_DIR"]}/run-{run["id"]}.json')

def test_mixed_legacy_row_quarantined_whole_no_split(client,analyst,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    # 三角中 concepts[1]-concepts[2] 已被 A 占用；新增第四项作品构造不冲突的混合来源行
    c4=client.post('/concepts',headers=ha,json={'study_id':sid,'code':'M'+uuid.uuid4().hex[:5].upper(),'title':'混合旧票侧','medium':''})
    assert c4.status_code==201
    mixed=client.post('/pairs',headers=ha,json={'study_id':sid,'left_id':concepts[0],'right_id':c4.json()['id'],
        'left_wins':4,'right_wins':6,'source':'mixed-legacy.csv'})
    assert mixed.status_code==201,mixed.text
    w=client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'mixed-legacy.csv','reason':''})
    assert w.json()['quarantined_pairs']==1
    row=client.get(f'/pairs?study_id={sid}',headers=ha).json()
    m=[p for p in row if p['id']==mixed.json()['id']][0]
    assert m['quarantined'] is True  # 整票隔离，票数未被部分扣减
    assert m['left_wins']==4 and m['right_wins']==6
    # 同次撤回不应影响 A/B 来源的既有行
    assert {p['id']:p['quarantined'] for p in row if p['source']=='source-B.csv'}=={pb1['id']:False}

def test_other_study_untouched(client,analyst,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    s2=client.post('/studies',headers=ha,json={'code':f'T-WD-2-{uuid.uuid4().hex[:8]}','name':'另一研究','source_file':'x.csv','context':''}).json()
    c1=client.post('/concepts',headers=ha,json={'study_id':s2['id'],'code':'D'+uuid.uuid4().hex[:6].upper(),'title':'丁一','medium':''}).json()['id']
    c2=client.post('/concepts',headers=ha,json={'study_id':s2['id'],'code':'E'+uuid.uuid4().hex[:6].upper(),'title':'丁二','medium':''}).json()['id']
    client.post('/pairs',headers=ha,json={'study_id':s2['id'],'left_id':c1,'right_id':c2,'left_wins':9,'right_wins':11,'source':'source-A.csv'})
    w=client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'source-A.csv','reason':''})
    assert w.status_code==200
    other=client.get(f'/pairs?study_id={s2["id"]}',headers=ha).json()
    assert all(p['quarantined'] is False for p in other)
    # 同名来源在另一研究仍可正常撤回（按研究隔离）
    w2=client.post('/withdrawals',headers=ha,json={'study_id':s2['id'],'source':'source-A.csv','reason':''})
    assert w2.json()['quarantined_pairs']==1

def test_blank_source_rejected(client,analyst,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    c4=client.post('/concepts',headers=ha,json={'study_id':sid,'code':'B'+uuid.uuid4().hex[:5].upper(),'title':'无来源侧','medium':''})
    r=client.post('/pairs',headers=ha,json={'study_id':sid,'left_id':concepts[0],'right_id':c4.json()['id'],
                                            'left_wins':5,'right_wins':5,'source':'   '})
    assert r.status_code==422

def test_all_pairs_quarantined_blocks_new_run(client,analyst,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha=auth(analyst)
    for src in ('source-A.csv','source-B.csv'):
        client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':src,'reason':''})
    r=client.post('/runs',headers=ha,json={'study_id':sid,'name':'无有效票研究','ridge':1.0,'repeats':50,'seed':1})
    assert r.status_code==422

def test_rejected_proposal_kept_on_withdrawal(client,analyst,admin,study_setup):
    sid,concepts,pa1,pa2,pb1=study_setup
    ha,hm=auth(analyst),auth(admin)
    run=_queue_run(client,ha,sid,'被退回提案的研究')
    from src.services.run_service import execute_run
    with TestSession() as db:execute_run(db,run['id'])
    p=client.post('/proposals',headers=ha,json={'run_id':run['id'],'name':'将被退回-'+uuid.uuid4().hex[:8],
        'left_id':concepts[0],'right_id':concepts[1],'extra_votes':30,'rationale':'先提交一份待审阅的补票提案'}).json()
    client.post(f"/proposals/{p['id']}/review",headers=hm,json={'status':'rejected','reviewer_note':'依据不足予以退回处理'})
    client.post('/withdrawals',headers=ha,json={'study_id':sid,'source':'source-A.csv','reason':''})
    after={x['id']:x for x in client.get('/proposals',headers=ha).json()}[p['id']]
    assert after['status']=='rejected'  # 历史退回决定不被撤回覆盖
