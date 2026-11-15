from sqlalchemy import String,ForeignKey,UniqueConstraint,Boolean
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class PairCount(Base):
    __tablename__='pair_counts'
    id:Mapped[int]=mapped_column(primary_key=True)
    study_id:Mapped[int]=mapped_column(ForeignKey('comparison_studies.id'))
    left_id:Mapped[int]=mapped_column(ForeignKey('concepts.id'))
    right_id:Mapped[int]=mapped_column(ForeignKey('concepts.id'))
    left_wins:Mapped[int]=mapped_column()
    right_wins:Mapped[int]=mapped_column()
    source:Mapped[str]=mapped_column(String(160),default='')
    # 来源撤回后整行隔离；混合旧票无法按来源拆分时不猜分摊，整票保留但不再可用
    quarantined:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    __table_args__=(UniqueConstraint('study_id','left_id','right_id'),)
