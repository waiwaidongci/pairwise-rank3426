from datetime import datetime
from sqlalchemy import String,ForeignKey,DateTime
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class ReviewProposal(Base):
    __tablename__='review_proposals'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(140),unique=True)
    run_id:Mapped[int]=mapped_column(ForeignKey('ranking_runs.id'))
    left_id:Mapped[int]=mapped_column(ForeignKey('concepts.id'))
    right_id:Mapped[int]=mapped_column(ForeignKey('concepts.id'))
    extra_votes:Mapped[int]=mapped_column(default=30)
    rationale:Mapped[str]=mapped_column(String(1600))
    status:Mapped[str]=mapped_column(String(20),default='draft')
    reviewer_note:Mapped[str]=mapped_column(String(1000),default='')
    reviewed_by:Mapped[str]=mapped_column(String(140),default='')
    # 依据来源撤回后停止分发的留痕；已退回的历史决定不覆盖
    halt_reason:Mapped[str]=mapped_column(String(600),default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
