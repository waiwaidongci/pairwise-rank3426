from enum import StrEnum
class Role(StrEnum):
    ADMIN='admin'; ANALYST='analyst'; VIEWER='viewer'
class RunStatus(StrEnum):
    QUEUED='queued'; RUNNING='running'; COMPLETED='completed'; FAILED='failed'; INVALIDATED='invalidated'
class ProposalStatus(StrEnum):
    DRAFT='draft'; APPROVED='approved'; REJECTED='rejected'; HALTED='halted'
