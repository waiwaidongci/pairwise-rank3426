from fastapi import APIRouter,Depends
from src.config.database import get_db
from src.utils.auth import current_user,editor
from src.schemas.withdrawal import WithdrawInput,WithdrawOut,WithdrawalSource
from src.controllers import withdrawal_controller as controller
router=APIRouter(prefix='/withdrawals',tags=['withdrawals'])
@router.get('',response_model=list[WithdrawalSource])
def index(study_id:int|None=None,db=Depends(get_db),user=Depends(current_user)):return controller.index(db,study_id)
@router.get('/impact')
def impact(study_id:int|None=None,db=Depends(get_db),user=Depends(current_user)):
    data=controller.impact(db,study_id)
    return {'quarantined_pairs':[{'id':p.id,'study_id':p.study_id,'left_id':p.left_id,'right_id':p.right_id,
                                  'left_wins':p.left_wins,'right_wins':p.right_wins,'source':p.source} for p in data['quarantined_pairs']],
            'invalidated_runs':[{'id':r.id,'study_id':r.study_id,'name':r.name,'invalidated_reason':r.invalidated_reason} for r in data['invalidated_runs']],
            'halted_proposals':[{'id':p.id,'name':p.name,'run_id':p.run_id,'halt_reason':p.halt_reason} for p in data['halted_proposals']]}
@router.post('',response_model=WithdrawOut)
def withdraw(data:WithdrawInput,db=Depends(get_db),user=Depends(editor)):return controller.withdraw(db,data)
