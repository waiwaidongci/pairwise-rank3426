import {createStore} from '../utils/store';import * as withdrawals from '../api/withdrawals';import type {WithdrawalSource,WithdrawalImpact} from '../types/domain';
export const withdrawalStore=createStore<{sources:WithdrawalSource[];impact:WithdrawalImpact|null}>({sources:[],impact:null});
export async function loadWithdrawals(studyId?:number){
  const [sources,impact]=await Promise.all([withdrawals.list(studyId),withdrawals.impact(studyId)]);
  withdrawalStore.set({sources,impact});
}
