import {request,post} from './client';import type {WithdrawalSource,WithdrawalImpact,WithdrawResult} from '../types/domain';
export const list=(study_id?:number)=>request<WithdrawalSource[]>('/withdrawals'+(study_id?`?study_id=${study_id}`:''));
export const impact=(study_id?:number)=>request<WithdrawalImpact>('/withdrawals/impact'+(study_id?`?study_id=${study_id}`:''));
export const withdraw=(data:{study_id:number;source:string;reason:string})=>post<WithdrawResult>('/withdrawals',data);
