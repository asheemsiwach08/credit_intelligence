from pydantic import BaseModel, Field
from typing import List, Optional


class DPD306090Plus(BaseModel):
    days_30: int
    days_60: int
    days_90_plus: int

    class Config:
        extra = 'forbid'  # No additional properties allowed


class PaymentHistorySummary(BaseModel):
    dpd_30_60_90_plus: DPD306090Plus
    recent_dpd_flag: bool

    class Config:
        extra = 'forbid'

class UniqueAccountType(BaseModel):
    unique_account_type: str
    total_number_of_accounts: int
    total_credit_or_sanctioned_limit_amount: float
    overdue_amount: float
    credit_exposure: float

class AccountDetail(BaseModel):
    lender_name: str
    account_type: str  # e.g., "Credit Card", "Personal Loan", etc.
    account_number: str  # masked string
    ownership: str  # "Individual", "Joint", etc.
    opened_date: str  # YYYY-MM-DD format
    last_payment_date: Optional[str]  # YYYY-MM-DD format, Optional
    last_payment_amount: Optional[float]
    upcoming_payment_date: Optional[str]  # YYYY-MM-DD format, Optional
    upcoming_payment_amount: Optional[float]
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

class CreditCardAge(BaseModel):
    oldest_account_age: str
    newest_account_age: str
    average: str

class LimitsOnCreditCards(BaseModel):
    highest_credit_available: str
    lowest_credit_available: str
    average_credit_available: str

class AddressDetails(BaseModel):
    address: str
    state: str
    pincode: str
    date: str

class UserDetails(BaseModel):
    user_name: str = Field(default="",description="Name of the user mentioned in the credit report or data source")
    gender: str = Field(default="",description="Gender of the user mentioned in the credit report or data source")
    age: int = Field(default=0,description="Age of the user mentioned in the credit report or data source")
    date_of_birth: str = Field(default="",description="Date of birth of the user mentioned in the credit report or data source")
    phone_number: str = Field(default="",description="Phone number of the user mentioned in the credit report or data source")
    email_address: str = Field(default="",description="Email address of the user mentioned in the credit report or data source")
    pan: str = Field(default="",description="PAN(Permanent Account Number) number of the user,it should be a combination of10 digits with a mix of 5 alphabets then 4 digits and then 1 alphabet.")
    passport_number: str = Field(default="",description="Passport number of the user mentioned in the credit report or data source")
    driving_license_number: str = Field(default="",description="Driving license number of the user mentioned in the credit report or data source")
    voter_id: str = Field(default="",description="Voter id of the user mentioned in the credit report or data source")
    ration_card_id: str = Field(default="",description="Ration card id of the user mentioned in the credit report or data source")
    address_history: List[AddressDetails]

    class Config:
        extra = 'forbid'

class CreditScore(BaseModel):
    credit_score: int
    score_status: str
    report_generated_date: str

class RiskAnalysis(BaseModel):
    risk_category: str  # "Low", "Moderate", "High"
    score_interpretation: str  # Interpretation of the CREDIT score
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

class Credit_Report_Format(BaseModel):
    user_details: UserDetails
    credit_card_age_details: CreditCardAge
    credit_card_limits: LimitsOnCreditCards
    credit_score: CreditScore
    risk_analysis: RiskAnalysis
    account_summary: AccountSummary
    unique_account_types: List[UniqueAccountType]
    credit_enquiries: CreditEnquiries
    account_details: List[AccountDetail]
    remarks: Remarks
    summary_report: str

    class Config:
        extra = 'forbid'

    def generate_summary_report(self) -> str:
        """Return a human‑readable one‑pager summarising the bureau data."""
        cs, ra, acc, ce, rem = (
            self.credit_score,
            self.risk_analysis,
            self.account_summary,
            self.credit_enquiries,
            self.remarks,
        )

        summary = (
            f"--- CREDIT Report Summary ---\n"
            f"1. **CREDIT Score**: {cs.credit_score} ({cs.score_status})\n"
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

