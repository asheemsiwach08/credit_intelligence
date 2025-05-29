import uuid
import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Union, List, Dict, Any

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def safe_get(d, key, default="{}"):
    return d.get(key, default)

def generate_file_name(pan: str, unique_id:str, extension:str) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds') \
                .replace(":", "").replace(".", "") + "Z"
    return f"{pan.upper()}_{timestamp}_{unique_id}.{extension}"

def try_parse_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def calculate_recent_payments(json_data: Union[str, List[Dict[str, Any]]], months_back: int) -> Dict[str, float]:
    """
    Calculate total last payment amounts for Credit Card and other loan types in the last `months_back` months.

    Args:
        json_data (str or list of dict): JSON string or loaded JSON list of dictionaries representing account data.
        months_back (int): Number of months to look back from today for filtering last payment dates. Default is 6.

    Returns:
        dict: Totals keyed by 'credit_card' and 'other_loans'.
    """
    try:
        if isinstance(json_data, str):
            try:
                df = pd.read_json(json_data)
            except ValueError as e:
                logging.error(f"Failed to parse JSON string: {e}")
                return {"credit_cards_count": 0,"credit_card_total": 0.0,"other_loans_count": 0, "other_loans_total": 0.0}
        elif isinstance(json_data, list):
            df = pd.DataFrame(json_data)
        else:
            logging.error("Invalid input type. Expected str or list of dictionaries.")
            return {"credit_cards_count": 0,"credit_card_total": 0.0,"other_loans_count": 0, "other_loans_total": 0.0}

        # Filter only active accounts
        df = df[df['account_status'] == 'Active']

        # Convert last_payment_date to datetime, coerce errors
        df['last_payment_date'] = pd.to_datetime(df['last_payment_date'], errors='coerce')
        df['last_payment_amount'] = pd.to_numeric(df['last_payment_amount'], errors='coerce').fillna(0)

        # Calculate cutoff date
        today = pd.Timestamp.today()
        cutoff_date = today - pd.DateOffset(months=months_back)
        recent_payments = df[df['last_payment_date'] >= cutoff_date]

        # Separate by account type
        credit_cards = recent_payments[recent_payments['account_type'].isin(['Credit Card'])]
        other_loans = recent_payments[recent_payments['account_type'] != 'Credit Card']

        # Sum amounts
        total_credit_card_amount = credit_cards['last_payment_amount'].sum()
        total_other_loans_amount = other_loans['last_payment_amount'].sum()

        # Total counts of credit cards and other loans
        total_credit_cards = credit_cards['account_number'].nunique()
        total_other_loans = other_loans['account_number'].nunique()

        return {
            "credit_cards_count": total_credit_cards,
            "credit_card_total": float(total_credit_card_amount) if not pd.isna(total_credit_card_amount) else 0.0,
            "other_loans_count": total_other_loans,
            "other_loans_total": float(total_other_loans_amount) if not pd.isna(total_other_loans_amount) else 0.0
        }
    except Exception as e:
        logging.exception("An unexpected error occurred during calculation")
        return {"credit_cards_count": 0,"credit_card_total": 0.0,"other_loans_count": 0, "other_loans_total": 0.0}


def calculate_recent_payments_by_lender(
    json_data: Union[str, List[Dict[str, Any]]],
    months_back: int
) -> List[Dict[str, Any]]:
    """
    Aggregate recent payment metrics per lender for the past `months_back` months.

    Parameters
    ----------
    json_data : str | list[dict]
        Either:
        • A JSON string representing a list of account dictionaries, **or**
        • A Python list of those dictionaries.

        Every account dict must include **all** of these keys (case-sensitive):
            - "account_status"         : str   ("Active", "Closed", …)
            - "last_payment_date"      : str | datetime-like
            - "last_payment_amount"    : str | int | float
            - "account_type"           : str   (e.g., "Credit Card", "Home Loan")
            - "account_number"         : str | int
            - "lender_name"            : str

    months_back : int, default 6
        How far back (in months) to look when filtering `last_payment_date`.

    Returns
    -------
    list[dict]
        One dictionary for **each (lender_name, is_credit_card) pair** that
        survives the filters.Each item has this shape:

        ```
        {
            "lender_name"   : str,
            "is_credit_card": bool,
            "total_amount"  : float,   # Σ last_payment_amount
            "account_count" : int      # distinct account_number count
        }
        ```

        If validation fails or no rows qualify, **an empty list `[]` is returned**.

    Notes
    -----
    • Only rows where `account_status == "Active"` **and**
      `last_payment_date >= today - months_back` are considered.
    • `is_credit_card` is `True` when `account_type == "Credit Card"`, else `False`.
    """
    try:
        # 1. Load JSON -> DataFrame
        if isinstance(json_data, str):
            df = pd.read_json(json_data)
        elif isinstance(json_data, list):
            df = pd.DataFrame(json_data)
        else:
            logging.error("Invalid input type; expected JSON string or list of dicts.")
            return []

        # 2. Basic validation
        expected_cols = {
            "account_status", "last_payment_date", "last_payment_amount",
            "account_type", "account_number", "lender_name"
        }
        if not expected_cols.issubset(df.columns):
            missing = expected_cols - set(df.columns)
            logging.error(f"Missing required columns: {missing}")
            return []

        # 3. Clean & filter rows
        df = df[df["account_status"] == "Active"]
        df["last_payment_date"] = pd.to_datetime(
            df["last_payment_date"], errors="coerce")
        df["last_payment_amount"] = (
            pd.to_numeric(df["last_payment_amount"], errors="coerce").fillna(0)
        )
        cutoff = pd.Timestamp.today() - pd.DateOffset(months=months_back)
        df = df[df["last_payment_date"] >= cutoff]

        if df.empty:
            return []


        grouped = (
            df.groupby(["lender_name", "account_type"])
              .agg(
                  total_amount=("last_payment_amount", "sum"),
                  account_count=("account_number", "nunique")
              )
              .reset_index()
        )

        result = grouped.to_dict(orient="records")
        return result

    except Exception as exc:
        logging.exception("calculate_recent_payments_by_lender failed with: %s", exc)
        return []
