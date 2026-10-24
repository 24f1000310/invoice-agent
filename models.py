
from typing import Literal
from pydantic import BaseModel, Field


InvoiceAction = Literal[
    "settle_invoice",
    "request_approval",
    "hold_invoice",
    "reject_duplicate",
    "open_exception"
]


class InvoiceFacts(BaseModel):
    vendorName: str
    invoiceNumber: str
    amountMinor: int
    currency: str


class InvoiceProposal(BaseModel):
    packageId: str
    actionId: str = Field(min_length=12)
    action: InvoiceAction
    facts: InvoiceFacts
    evidenceRefs: list[str] = Field(min_length=3, max_length=3)
    rationale: str = Field(min_length=60, max_length=1500)


class ProposalBatch(BaseModel):
    batchId: str
    proposals: list[InvoiceProposal]


class InvoiceExecution(BaseModel):
    packageId: str
    actionId: str
    action: InvoiceAction
    receiptNonce: str
    facts: InvoiceFacts
    evidenceRefs: list[str]


class ReceiptBatch(BaseModel):
    batchId: str
    executions: list[InvoiceExecution]
