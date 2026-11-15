from src.services import withdrawal_service as service
def index(db,study_id=None):
    if study_id is None:return service.list_withdrawals(db)
    return [w for w in service.list_withdrawals(db) if w['study_id']==study_id]
def impact(db,study_id=None):return service.withdrawal_impact(db,study_id)
def withdraw(db,data):return service.withdraw_source(db,data.study_id,data.source,data.reason)
