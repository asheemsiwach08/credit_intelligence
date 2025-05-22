cibil_report_insert_query = """INSERT INTO cibil_intelligence (
                pan, user_name,date_of_birth, report_generated_date, cibil_score,
                score_status, risk_category, score_interpretation, suggested_action, total_accounts, active_accounts,
                closed_accounts, overdue_accounts, written_off_accounts, total_enquiries_last_6_months,
                high_frequency_flag, enquiry_details, critical_flags, general_observations, summary_report
            )
            VALUES (
                %s,  -- pan
                %s,  -- user_name
                %s,  -- date_of_birth
                %s,  -- report_generated_date
                %s,  -- cibil_score
                %s,  -- score_status
            
                %s,  -- risk_category
                %s,  -- score_interpretation
                %s,  -- suggested_action
            
                %s,  -- total_accounts
                %s,  -- active_accounts
                %s,  -- closed_accounts
                %s,  -- overdue_accounts
                %s,  -- written_off_accounts
            
                %s,  -- total_enquiries_last_6_months
                %s,  -- high_frequency_flag
                %s,  -- enquiry_details (stringified JSON/list)
            
                %s,  -- critical_flags (stringified JSON/list)
                %s,  -- general_observations
            
                %s   -- summary_report (text)
                );"""

UPDATE_CIBIL_REPORT = """UPDATE cibil_intelligence SET
    user_name = %s,
    date_of_birth = %s,
    report_generated_date = %s,
    cibil_score = %s,
    score_status = %s,
    risk_category = %s,
    score_interpretation = %s,
    suggested_action = %s,
    total_accounts = %s,
    active_accounts = %s,
    closed_accounts = %s,
    overdue_accounts = %s,
    written_off_accounts = %s,
    total_enquiries_last_6_months = %s,
    high_frequency_flag = %s,
    enquiry_details = %s,
    critical_flags = %s,
    general_observations = %s,
    summary_report = %s
    WHERE pan = %s;
    """

CHECK_EXISTING_PAN = "SELECT 1 FROM cibil_intelligence WHERE pan = %s;"