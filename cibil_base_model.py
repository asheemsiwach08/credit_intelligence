from pydantic import BaseModel, Field
from typing import List, Optional

# Define a strict schema for dpd_30_60_90_plus with additionalProperties set to false
class PaymentHistorySummary(BaseModel):
    dpd_30_60_90_plus: dict
    recent_dpd_flag: bool  # Flag to indicate if recent DPD is a concern

    class Config:
        extra = 'forbid'  # Ensure no extra properties in the PaymentHistorySummary

    # Explicitly define dpd_30_60_90_plus schema with additionalProperties set to false
    # @property
    def dpd_30_60_90_plus(self):
        return {
            "type": "object",
            "properties": {
                "30_days": { "type": "integer" },
                "60_days": { "type": "integer" },
                "90_plus_days": { "type": "integer" }
            },
            "additionalProperties": False  # Ensure no extra properties allowed here
        }

class AccountDetail(BaseModel):
    account_type: str  # e.g., "Credit Card", "Personal Loan", etc.
    account_number: str  # masked string
    ownership: str  # "Individual", "Joint", etc.
    opened_date: str  # YYYY-MM-DD format
    last_payment_date: Optional[str]  # YYYY-MM-DD format, Optional
    current_balance: float  # Balance remaining in the account
    sanctioned_amount: float  # Total sanctioned amount for the account
    repayment_tenure: Optional[int]  # in months
    account_status: str  # "Active", "Closed", etc.
    # payment_history_summary: PaymentHistorySummary  # Detailed history of payments

    class Config:
        extra = 'forbid'

class EnquiryDetail(BaseModel):
    date: str  # Date in YYYY-MM-DD format
    enquirer_name: str
    enquiry_purpose: str

    class Config:
        extra = 'forbid'

class UserDetails(BaseModel):
    user_name: str
    date_of_birth: str
    pan: str
    report_generated_date: str
    cibil_score: Optional[int]
    score_status: str  # "Available", "Not Available", "NA"

    class Config:
        extra = 'forbid'

class RiskAnalysis(BaseModel):
    risk_category: str  # "Low", "Moderate", "High"
    score_interpretation: str  # Interpretation of the CIBIL score
    suggested_action: str  # Suggest action like "Approved", "Under Review", "Reject"

    class Config:
        extra = 'forbid'

class AccountSummary(BaseModel):
    total_accounts: int
    active_accounts: int
    closed_accounts: int
    overdue_accounts: int
    written_off_accounts: int

    class Config:
        extra = 'forbid'

class CreditEnquiries(BaseModel):
    total_enquiries_last_6_months: int
    high_frequency_flag: bool  # Flag if there are frequent enquiries
    enquiry_details: List[EnquiryDetail]  # List of detailed enquiries

    class Config:
        extra = 'forbid'

class Remarks(BaseModel):
    critical_flags: List[str]  # List of critical flags like "Frequent Enquiries"
    general_observations: str  # Other observations or remarks

    class Config:
        extra = 'forbid'

class Cibil_Report_Format(BaseModel):
    user_details: UserDetails
    risk_analysis: RiskAnalysis
    account_summary: AccountSummary
    credit_enquiries: CreditEnquiries
    account_details: List[AccountDetail]
    remarks: Remarks
    summary_report: str

    class Config:
        extra = 'forbid'

    def generate_summary_report(self) -> str:
        """Return a human‑readable one‑pager summarising the bureau data."""
        rs, ra, acc, ce, rem = (
            self.report_summary,
            self.risk_analysis,
            self.account_summary,
            self.credit_enquiries,
            self.remarks,
        )

        summary = (
            f"--- CIBIL Report Summary ---\n"
            f"1. **CIBIL Score**: {rs.cibil_score} ({rs.score_status})\n"
            f"   • Falls in the **{ra.risk_category}** bucket.\n"
            f"2. **Risk Analysis**\n"
            f"   • Interpretation : {ra.score_interpretation}\n"
            f"   • Suggested action: {ra.suggested_action}\n"
            f"3. **Accounts**\n"
            f"   • Total   : {acc.total_accounts}\n"
            f"   • Active  : {acc.active_accounts}\n"
            f"   • Overdue : {acc.overdue_accounts}\n"
            f"4. **Credit Enquiries (6 mo)**\n"
            f"   • Count   : {len(ce.enquiry_details)}\n"
            f"   • High frequency flag: {ce.high_frequency_flag}\n"
            f"5. **Remarks**\n"
            f"   • Critical flags    : {', '.join(rem.critical_flags) or 'None'}\n"
            f"   • Observations      : {rem.general_observations}\n"
        )
        return summary

