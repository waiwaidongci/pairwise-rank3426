from pydantic import BaseModel,Field
class WithdrawInput(BaseModel):
    study_id:int
    source:str=Field(min_length=1,max_length=160)
    reason:str=Field(default='',max_length=600)
class WithdrawOut(BaseModel):
    study_id:int
    source:str
    reason:str
    repeated:bool
    quarantined_pair_ids:list[int]
    quarantined_pairs:int
    quarantined_votes:int
    invalidated_run_ids:list[int]
    halted_proposal_ids:list[int]
class WithdrawalSource(BaseModel):
    study_id:int
    source:str
    pair_count:int
    votes:int
    withdrawn:bool
