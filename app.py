import os
import re
import json
import glob
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

try:
    from google import genai
except Exception:
    genai = None

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ AI Fleet Diagnostics Dashboard")
st.caption("Fleet diagnostics, subscription renewal opportunities, SIM analytics and customer recovery.")

REPORTING_HOURS = 30
ROOT = Path(__file__).resolve().parent

EXCLUDED_EMAILS = {
    "hello@cartracker.com.ng", "oluwafemi.a@cartracker.com", "ayo.a@cartracker.com",
    "inyang@cartracker.com", "rukayat@cartracker.com.ng", "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com", "oyindaabegunde@yahoo.com",
    "abasifrekeekanem1@cartracker.com", "andrew@cartracker.com.ng",
    "ifeoluwa@cartracker.ng", "james@cartracker.com.org",
    "blessing@catracker.com.ng", "damilola@catracker.com.ng",
    "dammylola@catracker.com.ng", "blessing@catracker.ng",
    "dammylola@catracker.ng", "10device@cartracker.com.ng",
    "ag@cartracker.com.ng", "joyvivian111@gmail.com",
    "ehonreoluwaseun@icloud.com", "obinnaezenwa@gmail.com",
    "frankcay12345@yahoo.com", "access@hopmobiletransport.com",
    "adadioma@gmail.com", "balogunisiaka38@gmail.com", "gbaguje@yahoo.com",
    "akeemakinwale26@gmail.com", "rhemzy82@gmail.com",
    "muibihammedaliu@gmail.com", "faruqafolabi05@gmail.com",
    "chuklexy@gmail.com", "uokigbo@gmail.com", "ballingtonlogistics@gmail.com",
}
EXCLUDED_KEYWORDS = ["cartracker", "catracker", "clicktgi", "gbovo", "hopmobiletransport.com"]

NETWORK_PREFIXES = {
    "MTN": ["0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814", "0903", "0906", "0913", "0916", "0704"],
    "Airtel": ["0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904", "0907", "0912", "0911", "0702"],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes}


def is_missing(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    try:
        result = pd.isna(value)
        return bool(result) if not hasattr(result, "__len__") else False
    except (TypeError, ValueError):
        return False


def normalize_text(value):
    if is_missing(value):
        return ""
    return str(value).strip()


def normalize_number(value):
    if is_missing(value):
        return ""
    s = str(value).strip()
    if s.lower() in {"", "nan", "null", "none", "n/a"}:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits.startswith("234") and len(digits) >= 13:
        digits = digits[3:]
    if digits.startswith("0") and len(digits) >= 11:
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits


def extract_emails(value):
    if is_missing(value):
        return []
    if isinstance(value, (list, tuple, set)):
        text = " ".join(str(x) for x in value if not is_missing(x))
    else:
        text = str(value)
    found = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    result = []
    for email in found:
        e = email.strip().lower()
        if e not in EXCLUDED_EMAILS and not any(k in e for k in EXCLUDED_KEYWORDS):
            result.append(e)
    return result


def valid_imei(value):
    s = normalize_text(value)
    if s.endswith(".0"):
        s = s[:-2]
    return s.isdigit() and len(s) == 15


def clean_columns(frame):
    frame = frame.copy()
    frame.columns = [str(c).replace("\ufeff", "").strip() for c in frame.columns]
    return frame


def read_data(path):
    suffix = Path(path).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return clean_columns(pd.read_excel(path, dtype=str))
    try:
        return clean_columns(pd.read_csv(path, dtype=str, encoding="utf-8-sig", low_memory=False))
    except Exception:
        return clean_columns(pd.read_csv(path, dtype=str, encoding="latin1", low_memory=False))


def find_file(patterns, exclude=None):
    exclude = set(exclude or [])
    candidates = []
    for pattern in patterns:
        candidates.extend(ROOT.glob(pattern))
        candidates.extend(ROOT.glob(f"**/{pattern}"))
    candidates = [p for p in set(candidates) if p.is_file() and p not in exclude and p.stat().st_size > 0]
    # Prefer root-level and then latest modified.
    candidates.sort(key=lambda p: (len(p.relative_to(ROOT).parts), -p.stat().st_mtime, p.name.lower()))
    return candidates[0] if candidates else None


def find_col(frame, candidates):
    lowered = {str(c).strip().lower(): c for c in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    # fallback: normalised names
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", str(s).lower())
    norm_cols = {norm(c): c for c in frame.columns}
    for candidate in candidates:
        if norm(candidate) in norm_cols:
            return norm_cols[norm(candidate)]
    return None


def normalize_plate(value):
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value).upper())


def network_for_number(value, verified_airtel):
    number = normalize_number(value)
    if not number:
        return "Missing"
    if number in verified_airtel:
        return "Airtel (verified)"
    # number is stored as national significant number without leading 0
    full_prefix = "0" + number[:3] if len(number) >= 10 else ""
    if full_prefix in PREFIX_TO_NETWORK:
        network = PREFIX_TO_NETWORK[full_prefix]
        if network == "Airtel":
            return "Airtel (prefix estimate)"
        return f"{network} (prefix estimate)"
    return "Unknown/Other"


def read_phone_list(frame):
    phone_col = find_col(frame, [
        "msisdn", "phone", "phone number", "mobile", "mobile number", "sim number",
        "sim_number", "sim_num", "line", "line number", "number", "subscriber number",
    ])
    # If headers are unusual, use a column with the most values resembling phone numbers.
    if phone_col is None:
        best_col, best_score = None, 0
        for col in frame.columns:
            sample = frame[col].dropna().astype(str).head(500)
            score = sum(1 for x in sample if len(re.sub(r"\D", "", x)) in (10, 11, 12, 13))
            if score > best_score:
                best_col, best_score = col, score
        phone_col = best_col if best_score >= 3 else None
    if phone_col is None:
        return set(), None
    nums = {normalize_number(x) for x in frame[phone_col].tolist()}
    nums.discard("")
    return nums, phone_col


# -------------------- Load committed repository data --------------------
fleet_path = find_file(["devices_report.csv", "devices_report.csv.csv", "devices_report_*.csv", "devices_report*.xlsx", "devices_report*.xls"])
if fleet_path is None:
    st.error("Fleet report was not found in the GitHub repository. Commit devices_report.csv beside app.py.")
    st.stop()

df = read_data(fleet_path)
st.caption(f"Fleet data source: `{fleet_path.relative_to(ROOT)}` (loaded from the GitHub repository)")
st.caption(f"Reporting threshold: last {REPORTING_HOURS} hours. The dashboard uses the app server's current time.")

# Normalize common source column variations without discarding original data.
rename_map = {}
aliases = {
    "sim_number": ["sim_number", "sim_num", "sim number", "sim", "phone", "phone_number", "msisdn", "mobile"],
    "imei": ["imei", "device_imei", "imei_number"],
    "plate_number": ["plate_number", "plate number", "registration_number", "registration number", "vehicle_registration", "registration"],
    "last_connect_time": ["last_connect_time", "last report", "last_reporting", "last_report_time", "last connection", "last_connect", "last_reported_at"],
    "expiration_date": ["expiration_date", "expiration date", "expire_date", "expiry date", "subscription_expiry", "expires_at"],
    "created_at": ["created_at", "created at", "created"],
    "users_list": ["users_list", "user_emails", "user email", "customer email", "email"],
    "active": ["active", "is_active", "status_active"],
    "name": ["name", "vehicle name", "object name"],
    "id": ["id", "device id", "object id"],
}
for standard, options in aliases.items():
    found = find_col(df, options)
    if found and found != standard and standard not in df.columns:
        rename_map[found] = standard
if rename_map:
    df = df.rename(columns=rename_map)

for col in ["created_at", "last_connect_time", "expiration_date"]:
    if col not in df.columns:
        df[col] = pd.NaT
    df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=False)

if "active" not in df.columns:
    df["active"] = "1"
if "sim_number" not in df.columns:
    df["sim_number"] = ""
if "imei" not in df.columns:
    df["imei"] = ""
for col in ["id", "name", "plate_number", "users_list"]:
    if col not in df.columns:
        df[col] = ""

now = pd.Timestamp.now()
df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400
df["report_status"] = "Not reporting / unknown"
df.loc[df["last_connect_time"].notna() & (df["hours_offline"] <= REPORTING_HOURS), "report_status"] = f"Reporting (last {REPORTING_HOURS}h)"
df.loc[df["last_connect_time"].notna() & (df["hours_offline"] > REPORTING_HOURS), "report_status"] = f"Offline {REPORTING_HOURS}h+"

df["user_emails"] = df["users_list"].apply(extract_emails)
df["primary_email"] = df["user_emails"].apply(lambda items: items[0] if items else "")

# Automatically discover the Airtel SIM inventory anywhere in the repository.
airtel_path = find_file(["*airtel*.csv", "*airtel*.xlsx", "*airtel*.xls", "*sim*list*.csv", "*sim*list*.xlsx", "*sim*list*.xls"], exclude=[fleet_path])
airtel_numbers = set()
airtel_col = None
if airtel_path:
    try:
        airtel_df = read_data(airtel_path)
        airtel_numbers, airtel_col = read_phone_list(airtel_df)
        st.caption(f"Airtel inventory: `{airtel_path.relative_to(ROOT)}`; loaded {len(airtel_numbers):,} normalized numbers from `{airtel_col or 'no phone column detected'}`.")
    except Exception as exc:
        st.warning(f"Could not read Airtel inventory: {exc}")
else:
    st.warning("No Airtel SIM inventory found in the repository. Prefix classification is only an estimate; verified Airtel matching is unavailable.")

df["sim_number_norm"] = df["sim_number"].apply(normalize_number)
df["sim_network"] = df["sim_number"].apply(lambda x: network_for_number(x, airtel_numbers))
df["active_flag"] = df["active"].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "active", "enabled"})
df["imei_clean"] = df["imei"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()

reporting = df[df["last_connect_time"].notna() & (df["hours_offline"] <= REPORTING_HOURS)]
not_reporting = df[df["last_connect_time"].isna() | (df["hours_offline"] > REPORTING_HOURS)]
expired = df[df["days_to_expiry"] < 0]
expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]
active_vehicles = df[df["active_flag"]]
active_offline = active_vehicles[active_vehicles["last_connect_time"].isna() | (active_vehicles["hours_offline"] > REPORTING_HOURS)]
renewal = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) & df["last_connect_time"].notna() & (df["hours_offline"] <= REPORTING_HOURS)].sort_values("days_to_expiry")

sim_blank = df["sim_number_norm"].eq("")
sim_counts = df.loc[~sim_blank, "sim_number_norm"].value_counts()
duplicate_sim_values = set(sim_counts[sim_counts > 1].index)
duplicate_sim_rows = df[df["sim_number_norm"].isin(duplicate_sim_values)]
invalid_imei = df[~df["imei"].apply(valid_imei)]
imei_counts = df.loc[df["imei_clean"].str.fullmatch(r"\d{15}", na=False), "imei_clean"].value_counts()
duplicate_imei_values = set(imei_counts[imei_counts > 1].index)
duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imei_values)]

network_breakdown = df["sim_network"].value_counts()
airtel_offline = df[(df["sim_network"] == "Airtel (verified)") & (df["last_connect_time"].isna() | (df["hours_offline"] >= REPORTING_HOURS))].copy()
airtel_offline = airtel_offline.sort_values("hours_offline", ascending=False, na_position="first")

# -------------------- KPI dashboard --------------------
st.success("Analysis complete")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(f"Reporting (last {REPORTING_HOURS}h)", f"{len(reporting):,}")
kpi2.metric("Not Reporting / Unknown", f"{len(not_reporting):,}")
kpi3.metric("Expired (total)", f"{len(expired):,}")
kpi4.metric("Active but Offline", f"{len(active_offline):,}")
kpi5, kpi6, kpi7, kpi8 = st.columns(4)
kpi5.metric("Expired (last 24h)", f"{len(expired_24h):,}")
kpi6.metric("Expired (last 30d)", f"{len(expired_30d):,}")
kpi7.metric("Expiring (next 24h)", f"{len(expiring_24h):,}")
kpi8.metric("Expiring (next 30d)", f"{len(expiring_30d):,}")

# -------------------- Zoho exports: auto-discovery and safer matching --------------------
st.divider()
st.subheader("📞 Zoho CRM & Expired Fleet Recovery Linker")
deals_path = find_file(["Deals_*.csv", "Deals_*.xlsx", "Deals_*.xls"])
customers_path = find_file(["Customer_*.csv", "Customers_*.csv", "Accounts_*.csv", "Customer_*.xlsx", "Customers_*.xlsx", "Accounts_*.xlsx"])
final_recovery = pd.DataFrame()
zoho_merged = pd.DataFrame()
zoho_diagnostics = {}

if deals_path and customers_path:
    st.caption(f"Using repository files: `{deals_path.relative_to(ROOT)}` and `{customers_path.relative_to(ROOT)}`")
    try:
        deals = read_data(deals_path)
        customers = read_data(customers_path)
        # Detect customer foreign key on Deals and record ID on Customers.
        deal_link = find_col(deals, [
            "Customer Name.id", "Customer Name Id", "Customer ID", "Customer Id",
            "Accounts Name.id", "Account Name.id", "Account ID", "Account Id",
            "Contact Name.id", "Contact ID", "Contact Id",
        ])
        customer_id = find_col(customers, ["Record Id", "Record ID", "id", "Customer ID", "Account ID"])
        deal_plate = find_col(deals, ["Plate Number", "Vehicle Plate Number", "Registration Number", "Vehicle Registration", "Deal Name", "Vehicle Name", "Name"])
        fleet_plate = find_col(df, ["plate_number", "registration_number", "name"])
        customer_phone = find_col(customers, ["Phone", "Phone Number", "Mobile", "Mobile Number", "Telephone", "Contact Number", "Mobile Phone", "Other Phone"])
        customer_email = find_col(customers, ["Email", "Email Address", "Primary Email", "Customer Email", "E-mail"])
        deal_phone = find_col(deals, ["Phone", "Phone Number", "Mobile", "Mobile Number", "Contact Number"])
        deal_email = find_col(deals, ["Email", "Email Address", "Customer Email", "E-mail"])

        # Join Deals to Customers using Zoho IDs if available; don't silently join on the wrong columns.
        if deal_link and customer_id:
            deals["_join_id"] = deals[deal_link].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            customers["_join_id"] = customers[customer_id].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
            zoho_merged = pd.merge(deals, customers, on="_join_id", how="left", suffixes=("_deal", "_cust"))
            zoho_diagnostics["Join method"] = f"Zoho ID: Deals `{deal_link}` → Customers `{customer_id}`"
        else:
            zoho_merged = deals.copy()
            zoho_diagnostics["Join method"] = "No reliable customer ID relationship detected; deal-only contact details will be used."
        zoho_diagnostics["Deals rows"] = len(deals)
        zoho_diagnostics["Customer rows"] = len(customers)
        zoho_diagnostics["Deal plate column"] = deal_plate or "Not detected"
        zoho_diagnostics["Customer phone column"] = customer_phone or "Not detected"
        zoho_diagnostics["Customer email column"] = customer_email or "Not detected"
        zoho_diagnostics["Deal phone column"] = deal_phone or "Not detected"
        zoho_diagnostics["Deal email column"] = deal_email or "Not detected"

        if deal_plate and fleet_plate:
            zoho_merged["_match_plate"] = zoho_merged[deal_plate].apply(normalize_plate)
            expired_units = df[df["days_to_expiry"] < 0].copy()
            expired_units["_match_plate"] = expired_units[fleet_plate].apply(normalize_plate)
            expired_units = expired_units[expired_units["_match_plate"] != ""]
            zoho_merged = zoho_merged[zoho_merged["_match_plate"] != ""]
            final_recovery = pd.merge(expired_units, zoho_merged, on="_match_plate", how="inner", suffixes=("", "_zoho"))

            # Pull contact details from both the customer and deal exports, handling suffixes.
            def pick_series(frame, names):
                col = find_col(frame, names)
                if col:
                    return frame[col]
                # Check suffixes for merged fields.
                for name in names:
                    for suffix in ["_cust", "_deal", "_zoho"]:
                        col2 = name + suffix
                        if col2 in frame.columns:
                            return frame[col2]
                return pd.Series([""] * len(frame), index=frame.index)

            phone_candidates = [
                "Phone_cust", "Phone Number_cust", "Mobile_cust", "Mobile Number_cust",
                "Phone", "Phone Number", "Mobile", "Mobile Number", "Telephone",
                "Contact Number", "Phone_deal", "Phone Number_deal", "Mobile_deal",
            ]
            email_candidates = [
                "Email_cust", "Email Address_cust", "Primary Email_cust", "Customer Email_cust",
                "Email", "Email Address", "Primary Email", "Customer Email", "E-mail",
                "Email_deal", "Email Address_deal", "Customer Email_deal",
            ]
            # Exact column search first; explicitly use suffix columns if merge generated them.
            phone_raw = pick_series(final_recovery, phone_candidates)
            email_raw = pick_series(final_recovery, email_candidates)
            final_recovery["customer_phone"] = phone_raw.apply(normalize_number)
            final_recovery["customer_emails"] = email_raw.apply(lambda v: ", ".join(extract_emails(v)))
            # If the linked customer export didn't supply contacts, retain deal-level contact values.
            for col in ["Phone_deal", "Phone Number_deal", "Mobile_deal", "Mobile Number_deal"]:
                if col in final_recovery.columns:
                    mask = final_recovery["customer_phone"].eq("")
                    final_recovery.loc[mask, "customer_phone"] = final_recovery.loc[mask, col].apply(normalize_number)
            for col in ["Email_deal", "Email Address_deal", "Customer Email_deal"]:
                if col in final_recovery.columns:
                    mask = final_recovery["customer_emails"].eq("")
                    final_recovery.loc[mask, "customer_emails"] = final_recovery.loc[mask, col].apply(lambda v: ", ".join(extract_emails(v)))

            final_recovery = final_recovery.drop_duplicates(subset=["id", "_match_plate"] if "id" in final_recovery.columns else ["_match_plate"])
            calls = final_recovery[final_recovery["customer_phone"] != ""]
            recovery_emails = final_recovery[final_recovery["customer_emails"] != ""]
            zoho_diagnostics["Plate matches"] = len(final_recovery)
            zoho_diagnostics["Matches with phone"] = len(calls)
            zoho_diagnostics["Matches with email"] = len(recovery_emails)

            a, b, c = st.columns(3)
            a.metric("Matched expired vehicles", f"{len(final_recovery):,}")
            b.metric("With phone numbers", f"{len(calls):,}")
            c.metric("With customer emails", f"{len(recovery_emails):,}")
            display_cols = [c for c in ["plate_number", "name", "expiration_date", "customer_phone", "customer_emails"] if c in final_recovery.columns]
            if display_cols:
                st.dataframe(final_recovery[display_cols], use_container_width=True, hide_index=True)
            if not calls.empty:
                st.download_button("⬇️ Download expired fleet calling list", calls[display_cols].to_csv(index=False).encode("utf-8"), "zoho_expired_fleet_calling_list.csv", "text/csv")
            if not recovery_emails.empty:
                st.download_button("⬇️ Download expired fleet email list", recovery_emails[display_cols].to_csv(index=False).encode("utf-8"), "zoho_expired_fleet_email_list.csv", "text/csv")
            with st.expander("Zoho matching diagnostics"):
                st.write(zoho_diagnostics)
                st.caption("A plate match confirms the vehicle link only. Contact counts depend on actual values in the linked Zoho exports.")
        else:
            st.warning("Could not confidently identify the vehicle plate column in both the fleet report and Zoho Deals export.")
            with st.expander("Zoho matching diagnostics"):
                st.write(zoho_diagnostics)
    except Exception as exc:
        st.error(f"Zoho matching could not be completed: {type(exc).__name__}: {exc}")
        with st.expander("Zoho matching diagnostics"):
            st.write(zoho_diagnostics)
else:
    st.warning("Zoho exports were not found automatically. Commit Deals_*.csv and Customer_*.csv (or Customers_*.csv / Accounts_*.csv) beside app.py or in a repository subfolder.")

# -------------------- Customer emails --------------------
st.divider()
st.subheader("✉️ Deduplicated Clean Customer Emails")
all_emails = set()
for value in df["users_list"].tolist():
    all_emails.update(extract_emails(value))
clean_emails_df = pd.DataFrame(sorted(all_emails), columns=["Customer Email"])
st.write(f"Total clean unique customer emails: **{len(clean_emails_df):,}**")
st.dataframe(clean_emails_df, use_container_width=True, hide_index=True)
st.download_button("⬇️ Download clean unique customer emails", clean_emails_df.to_csv(index=False).encode("utf-8"), "deduplicated_customer_emails.csv", "text/csv")

# -------------------- Network and SIM troubleshooting --------------------
st.divider()
st.subheader("📡 Network Breakdown")
st.bar_chart(network_breakdown)
network_table = pd.DataFrame({
    "Network": network_breakdown.index,
    "Device count": network_breakdown.values,
    "Percentage (%)": (network_breakdown.values / max(len(df), 1) * 100).round(2),
})
st.dataframe(network_table, use_container_width=True, hide_index=True)
st.caption("Prefix-based classifications are estimates. Only an exact normalized match in the Airtel inventory is marked verified.")

st.subheader(f"📡 Verified Airtel SIMs offline for {REPORTING_HOURS}+ hours")
st.write(f"Found **{len(airtel_offline):,} verified Airtel devices** with no report in the last {REPORTING_HOURS} hours.")
if not airtel_offline.empty:
    airtel_cols = [c for c in ["id", "name", "plate_number", "sim_number", "imei", "last_connect_time", "hours_offline", "expiration_date"] if c in airtel_offline.columns]
    st.dataframe(airtel_offline[airtel_cols], use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download verified Airtel offline list", airtel_offline[airtel_cols].to_csv(index=False).encode("utf-8"), "airtel_offline_30h.csv", "text/csv")

st.subheader("🔍 SIM & IMEI Data Quality")
q1, q2, q3, q4 = st.columns(4)
q1.metric("Missing SIM", f"{int(sim_blank.sum()):,}")
q2.metric("Rows with duplicate SIMs", f"{len(duplicate_sim_rows):,}")
q3.metric("Invalid IMEI", f"{len(invalid_imei):,}")
q4.metric("Rows with duplicate IMEIs", f"{len(duplicate_imei_rows):,}")

st.subheader("🛠️ SIM & Device Troubleshooting Workbench")
issues = df.copy()
issues["issue_reason"] = ""
issues["priority"] = "Low"
issues.loc[issues["last_connect_time"].isna(), "issue_reason"] += "No last-report timestamp; "
issues.loc[issues["last_connect_time"].notna() & (issues["hours_offline"] >= REPORTING_HOURS), "issue_reason"] += f"Offline {REPORTING_HOURS}h+; "
issues.loc[sim_blank, "issue_reason"] += "Missing SIM; "
issues.loc[issues.index.isin(duplicate_sim_rows.index), "issue_reason"] += "Duplicate SIM; "
issues.loc[issues.index.isin(invalid_imei.index), "issue_reason"] += "Invalid IMEI; "
issues.loc[issues.index.isin(duplicate_imei_rows.index), "issue_reason"] += "Duplicate IMEI; "
high_mask = issues["last_connect_time"].isna() | (issues["hours_offline"] >= 72) | issues.index.isin(invalid_imei.index) | issues.index.isin(duplicate_imei_rows.index)
medium_mask = (issues["hours_offline"] >= REPORTING_HOURS) | sim_blank | issues.index.isin(duplicate_sim_rows.index)
issues.loc[medium_mask, "priority"] = "Medium"
issues.loc[high_mask, "priority"] = "High"
issues = issues[issues["issue_reason"] != ""].copy()
priority_filter = st.multiselect("Filter troubleshooting priority", ["High", "Medium", "Low"], default=["High", "Medium"])
issue_filter = st.selectbox("Show devices with", ["Any flagged issue", "Offline 30h+", "Missing SIM", "Duplicate SIM", "Invalid IMEI", "Duplicate IMEI", "Verified Airtel"])
filtered_issues = issues[issues["priority"].isin(priority_filter)]
if issue_filter == "Offline 30h+":
    filtered_issues = filtered_issues[filtered_issues["hours_offline"].ge(REPORTING_HOURS) | filtered_issues["last_connect_time"].isna()]
elif issue_filter == "Missing SIM":
    filtered_issues = filtered_issues[filtered_issues["sim_number_norm"].eq("")]
elif issue_filter == "Duplicate SIM":
    filtered_issues = filtered_issues[filtered_issues.index.isin(duplicate_sim_rows.index)]
elif issue_filter == "Invalid IMEI":
    filtered_issues = filtered_issues[filtered_issues.index.isin(invalid_imei.index)]
elif issue_filter == "Duplicate IMEI":
    filtered_issues = filtered_issues[filtered_issues.index.isin(duplicate_imei_rows.index)]
elif issue_filter == "Verified Airtel":
    filtered_issues = filtered_issues[filtered_issues["sim_network"].eq("Airtel (verified)")]
st.write(f"Devices in troubleshooting view: **{len(filtered_issues):,}**")
st.write(f"High priority: **{int((filtered_issues['priority'] == 'High').sum()):,}** · Offline/unknown: **{int((filtered_issues['last_connect_time'].isna() | (filtered_issues['hours_offline'] >= REPORTING_HOURS)).sum()):,}**")
issue_cols = [c for c in ["id", "name", "plate_number", "sim_number", "sim_network", "imei", "last_connect_time", "hours_offline", "expiration_date", "priority", "issue_reason"] if c in filtered_issues.columns]
if not filtered_issues.empty:
    st.dataframe(filtered_issues[issue_cols], use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download troubleshooting report", filtered_issues[issue_cols].to_csv(index=False).encode("utf-8"), "fleet_troubleshooting_report.csv", "text/csv")
else:
    st.info("No devices match the selected troubleshooting filters.")

with st.expander("Suggested field troubleshooting checklist"):
    st.markdown("""
    1. Confirm the SIM is active and has a valid data plan with the telecom provider.
    2. Check device power, ignition wiring, antenna and installation condition.
    3. Confirm APN and server address/port match the device configuration.
    4. Compare the IMEI and SIM number on the physical device with the fleet record.
    5. Check network coverage and last known GPS/GSM signal on the tracking platform.
    6. Record the technician, action taken, test result and resolution time.

    These are diagnostic leads, not proof that the SIM or tracker is faulty.
    """)

# -------------------- Renewals and expired fleet --------------------
st.divider()
st.subheader("💰 Renewal Opportunities")
st.write(f"Found **{len(renewal):,} vehicles** reporting within {REPORTING_HOURS} hours and expiring within 30 days.")
renewal_cols = [c for c in ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date", "last_connect_time"] if c in renewal.columns]
st.dataframe(renewal[renewal_cols], use_container_width=True, hide_index=True)
if not renewal.empty:
    st.download_button("⬇️ Download renewal opportunities", renewal[renewal_cols].to_csv(index=False).encode("utf-8"), "renewal_opportunities.csv", "text/csv")
st.subheader("⚠️ Expired Vehicles List")
st.write(f"Found **{len(expired):,} expired vehicles**.")
expired_cols = [c for c in ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date", "last_connect_time"] if c in expired.columns]
st.dataframe(expired[expired_cols].head(500), use_container_width=True, hide_index=True)
st.download_button("⬇️ Download all expired vehicles", expired.to_csv(index=False).encode("utf-8"), "expired_vehicles_list.csv", "text/csv")

# -------------------- Data definitions and references --------------------
st.divider()
with st.expander("📚 Data sources, definitions & references"):
    st.markdown(f"""
    **Data sources**
    - Fleet report: `{fleet_path.relative_to(ROOT)}` from the GitHub repository.
    - Airtel inventory: `{airtel_path.relative_to(ROOT) if airtel_path else 'Not found'}`.
    - Zoho exports: Deals and Customer/Customers/Accounts files discovered in the repository.

    **Definitions**
    - Reporting: a valid `last_connect_time` within the last {REPORTING_HOURS} hours.
    - Not reporting / unknown: last report is older than {REPORTING_HOURS} hours or missing.
    - Expired: expiration date is before the dashboard server's current time.
    - Verified Airtel: normalized SIM number exactly matches a number in the discovered Airtel inventory.
    - Prefix estimate: network inferred from Nigerian mobile prefix; mobile number portability can make this incorrect.
    - Zoho plate match: normalized plate text matches between an expired fleet record and a Zoho Deals record. Contact details are shown only when found in exported columns.

    **Technical references**
    - [Streamlit documentation](https://docs.streamlit.io/)
    - [pandas documentation](https://pandas.pydata.org/docs/)
    - [Google Gemini API documentation](https://ai.google.dev/gemini-api/docs)
    - [Nigerian Communications Commission](https://www.ncc.gov.ng/)
    """)

# -------------------- Optional Gemini AI --------------------
st.divider()
st.subheader("🤖 AI Fleet Intelligence")
if not GEMINI_API_KEY:
    st.info("AI summary is disabled because GEMINI_API_KEY is not configured in Streamlit secrets or environment variables.")
elif genai is None:
    st.info("The Google GenAI package is unavailable. Check requirements.txt for google-genai.")
else:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        ai_stats = {
            "total_records": len(df),
            "reporting_last_30h": len(reporting),
            "not_reporting_or_unknown": len(not_reporting),
            "expired_total": len(expired),
            "active_but_offline": len(active_offline),
            "expiring_next_30d": len(expiring_30d),
            "renewal_opportunities": len(renewal),
            "missing_sim": int(sim_blank.sum()),
            "duplicate_sim_rows": len(duplicate_sim_rows),
            "invalid_imei": len(invalid_imei),
            "duplicate_imei_rows": len(duplicate_imei_rows),
            "verified_airtel_offline_30h": len(airtel_offline),
            "zoho_expired_plate_matches": len(final_recovery),
        }
        prompt = (
            "You are an operations analyst for a vehicle tracking fleet. Use only these verified counts. "
            "Do not claim that offline devices are definitely faulty. Return concise sections: Executive summary, "
            "Key insights, Recommended actions.\n\n" + json.dumps(ai_stats, indent=2)
        )
        response = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        st.markdown(response.text or "The AI model returned an empty response.")
    except Exception as exc:
        st.warning(f"AI summary could not be generated. The rest of the dashboard is still available. Details: {type(exc).__name__}: {exc}")
