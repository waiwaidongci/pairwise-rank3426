import time
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import RankingRun
from src.services.run_service import execute_run
from src.constants.enums import RunStatus
redis=Redis.from_url(REDIS_URL)
while True:
    Path('/tmp/heartbeat').touch()
    with Session() as db:
        item=db.scalar(select(RankingRun).where(RankingRun.status.in_(['queued','running'])).order_by(RankingRun.id))
        if item:
            # 撤回把状态翻成 invalidated 后，扫描自然跳过；执行内另有并发复查。
            db.refresh(item)
            if item.status in (RunStatus.QUEUED,RunStatus.RUNNING):execute_run(db,item.id)
        else:redis.brpop('pairwise:runs',timeout=2)
    time.sleep(.1)
