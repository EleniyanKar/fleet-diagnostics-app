import json
import os
import re
import glob
from dotenv import load_dotenv
from google import genai
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 1. Page Configuration & Modern Styling
# ==========================================
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(
    page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide"
)

st.markdown(
    """
    <style>
    @keyframes gradientText {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .modern-title {
        font-size: 2.3rem;
        font-weight: 800;
        background: linear-gradient(-45deg, #2563eb, #3b82f6, #06b6d4, #10b981);
        background-size: 300% 300%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: gradientText 6s ease infinite;
        margin-bottom: 0px;
    }
    .modern-subtitle {
        font-size: 1rem;
        color: #64748b;
        margin-bottom: 25px;
    }
    .icon-header {
        font-size: 1.25rem;
        font-weight: 700;
        color: #1e293b;
        margin-top: 20px;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<p class="modern-title">⚡ AI Fleet Diagnostics Dashboard</p>', unsafe_allow_html=True)
st.markdown('<p class="modern-subtitle">Live fleet diagnostics, subscription renewal opportunities, and network analytics.</p>', unsafe_allow_html=True)

# ==========================================
# 2. Administrative & Blacklisted Emails
# ==========================================
EXCLUDED_EMAILS = {
    "hello@cartracker.com.ng", "oluwafemi.a@cartracker.com", "ayo.a@cartracker.com",
    "inyang@cartracker.com", "rukayat@cartracker.com.ng", "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com", "oyindaabegunde@yahoo.com", "abasifrekeekanem1@cartracker.com",
    "andrew@cartracker.com.ng", "ifeoluwa@cartracker.ng", "james@cartracker.com.org",
    "blessing@catracker.com.ng", "damilola@catracker.com.ng", "dammylola@catracker.com.ng",
    "blessing@catracker.ng", "dammylola@catracker.ng", "10device@cartracker.com.ng",
    "ag@cartracker.com.ng", "joyvivian111@gmail.com", "ehonreoluwaseun@icloud.com",
    "obinnaezenwa@gmail.com", "frankcay12345@yahoo.com", "access@hopmobiletransport.com",
    "adadioma@gmail.com", "balogunisiaka38@gmail.com", "gbaguje@yahoo.com",
    "akeemakinwale26@gmail.com", "rhemzy82@gmail.com", "muibihammedaliu@gmail.com",
    "faruqafolabi05@gmail.com", "chuklexy@gmail.com", "uokigbo@gmail.com",
    "ballingtonlogistics@gmail.com",
}

EXCLUDED_KEYWORDS = [
    "cartracker", "catracker", "clicktgi", "gbovo", "hopmobiletransport.com",
]

# ==========================================
# 3. Telecom Network Prefixes (Nigeria)
# ==========================================
NETWORK_PREFIXES = {
    "MTN": ["0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814", "0903", "0906", "0913", "0916", "0704"],
    "Airtel": ["0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904", "0907", "0912", "0911", "0702"],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {p: net for net, prefixes in NETWORK_PREFIXES.items() for p in prefixes}

# ==========================================
# 4. Helper & Data Parsing Functions
# ==========================================
def normalize_number(n):
    if pd.isna(n) or str(n).strip().lower() in ("", "nan", "null", "none"):
        return ""
    s = str(n).strip()
    if s.endswith(".0"):
        s = s[:-2]
    elif s.endswith(".00"):
        s = s[:-3]
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits.startswith("234"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) > 10:
        digits = digits[-10:]
    return digits

def sim_network(sim, airtel_set):
    sim_norm = normalize_number(sim)
    if not sim_norm or str(sim).strip().lower() in ("", "nan", "none"):
        return "Missing"
    if sim_norm in airtel_set:
        return "Airtel (verified)"
    prefix = None
    if len(sim_norm) >= 9:
        prefix = "0" + sim_norm[:3]
    if prefix and prefix in PREFIX_TO_NETWORK:
        return PREFIX_TO_NETWORK[prefix]
    return "Unknown/Other (guessed)"

def valid_imei(v):
    v = str(v).replace(".00", "").strip()
    return v.isdigit() and len(v) == 15

def is_excluded_email(email_str):
    e = str(email_str).strip().lower()
    if e in EXCLUDED_EMAILS:
        return True
    for kw in EXCLUDED_KEYWORDS:
        if kw in e:
            return True
    return False

def extract_customer_emails(users_list_value):
    if pd.isna(users_list_value) or str(users_list_value).strip() == "":
        return []
    found_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", str(users_list_value))
    return [e.strip().lower() for e in found_emails if not is_excluded_email(e.strip().lower())]

def extract_clean_unique_emails(dataframe):
    all_extracted_emails = set()
    target_columns = [col for col in ["users_list", "user_emails", "primary_email"] if col in dataframe.columns]
    for col in target_columns:
        for val in dataframe[col].dropna():
            found = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", str(val))
            for email in found:
                e = email.strip().lower()
                if not is_excluded_email(e):
                    all_extracted_emails.add(e)
    return pd.DataFrame(sorted(list(all_extracted_emails)), columns=["Customer Email"])

def safe_read_file(file_source):
    filename = getattr(file_source, "name", str(file_source))
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_source, dtype=str)
    try:
        return pd.read_csv(file_source, encoding="utf-8-sig", dtype=str)
    except pd.errors.EmptyDataError:
        st.error(f"The file **{filename}** is empty. Please upload a valid report.")
        st.stop()
    except Exception:
        try:
            return pd.read_csv(file_source, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
        except Exception:
            return pd.read_csv(file_source, encoding="latin1", dtype=str)

def first_existing_col(dataframe, candidates):
    """Return the first matching column as a Series, trying each candidate
    name in order. Handles pandas merge suffixes (_deal, _cust, etc.) so a
    merged dataframe doesn't silently return blank data when the original
    unsuffixed column name no longer exists after the merge."""
    for c in candidates:
        if c in dataframe.columns:
            return dataframe[c]
    return pd.Series([""] * len(dataframe), index=dataframe.index)

# ==========================================
# 5. File Selection & Dataset Execution
# ==========================================
uploaded_file = st.file_uploader("Upload new fleet report (Optional)", type=["csv", "xlsx", "xls"])
airtel_file = st.file_uploader("Upload Airtel SIM list (Optional)", type=["csv", "xlsx"])

DEFAULT_FILES = ["devices_report.csv.csv", "devices_report_1789914045.csv", "devices_report.csv"]
default_path = next((f for f in DEFAULT_FILES if os.path.exists(f) and os.path.getsize(f) > 0), None)

airtel_numbers = set()
if airtel_file is not None:
    airtel_df = safe_read_file(airtel_file)
    airtel_df.columns = airtel_df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
    msisdn_col = next((col for col in airtel_df.columns if col.lower() in ["msisdn", "phone", "sim", "sim_number", "mobile"]), None)
    if msisdn_col:
        airtel_numbers = set(airtel_df[msisdn_col].apply(normalize_number))
        airtel_numbers.discard("")

if uploaded_file is not None:
    df = safe_read_file(uploaded_file)
elif default_path:
    df = safe_read_file(default_path)
else:
    st.warning("No fleet dataset found. Please upload a CSV or Excel report.")
    st.stop()

df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()

df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
df["last_connect_time"] = pd.to_datetime(df["last_connect_time"], errors="coerce")
df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce")

now = pd.Timestamp.now()
df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400

if "users_list" in df.columns:
    df["user_emails"] = df["users_list"].apply(extract_customer_emails)
    df["primary_email"] = df["user_emails"].apply(lambda emails: emails[0] if emails else "")
else:
    df["user_emails"] = [[] for _ in range(len(df))]
    df["primary_email"] = ""

reporting_24h = df[df["hours_offline"] <= 24]
not_reporting = df[df["hours_offline"] > 24]
expired_total = df[df["days_to_expiry"] < 0]
expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]

active_vehicles = df[df["active"].astype(str).str.strip() == "1"] if "active" in df.columns else df.head(0)
active_but_offline = active_vehicles[active_vehicles["hours_offline"] > 24]

if "sim_number" in df.columns:
    df["sim_number_norm"] = df["sim_number"].apply(normalize_number)
    df["sim_network"] = df["sim_number"].apply(lambda x: sim_network(x, airtel_numbers))
else:
    df["sim_network"] = "Missing"

network_breakdown = df["sim_network"].value_counts()

missing_sim = df[df["sim_number"].isna() | (df["sim_number"].astype(str).str.strip() == "")] if "sim_number" in df.columns else df
sim_counts = df["sim_number"].astype(str).value_counts() if "sim_number" in df.columns else pd.Series()
duplicate_sims = sim_counts[sim_counts > 1].index.tolist()
duplicate_sim_rows = df[df["sim_number"].astype(str).isin(duplicate_sims) & (df["sim_number"].astype(str) != "nan")] if "sim_number" in df.columns else df.head(0)

if "imei" in df.columns:
    df["imei_clean"] = df["imei"].astype(str).str.replace(".00", "", regex=False).str.strip()
    invalid_imei = df[~df["imei"].apply(valid_imei)]
    imei_counts = df["imei_clean"].value_counts()
    duplicate_imeis = imei_counts[imei_counts > 1].index.tolist()
    duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imeis)]
else:
    invalid_imei = df.head(0)
    duplicate_imei_rows = df.head(0)

renewal_opportunity = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) & (df["hours_offline"] <= 24)].sort_values("days_to_expiry")

stats = {
    "total_vehicles": len(df),
    "reporting_24h": len(reporting_24h),
    "not_reporting": len(not_reporting),
    "expired_last_24h": len(expired_24h),
    "expired_last_30d": len(expired_30d),
    "expired_total": len(expired_total),
    "expiring_next_24h": len(expiring_24h),
    "expiring_next_30d": len(expiring_30d),
    "active_vehicles": len(active_vehicles),
    "active_but_offline": len(active_but_offline),
    "missing_sim": len(missing_sim),
    "duplicate_sim_count": len(duplicate_sim_rows),
    "invalid_imei": len(invalid_imei),
    "duplicate_imei_count": len(duplicate_imei_rows),
    "renewal_opportunity_count": len(renewal_opportunity),
    "network_breakdown": network_breakdown.to_dict(),
}

# ==========================================
# 6. Dashboard UI Metrics Rendering
# ==========================================
st.success("Analysis Complete!")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reporting (24h)", f"{len(reporting_24h):,}")
c2.metric("Not Reporting", f"{len(not_reporting):,}")
c3.metric("Expired (total)", f"{len(expired_total):,}")
c4.metric("Active but Offline", f"{len(active_but_offline):,}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Expired (last 24h)", len(expired_24h))
c6.metric("Expired (last 30d)", len(expired_30d))
c7.metric("Expiring (next 24h)", len(expiring_24h))
c8.metric("Expiring (next 30d)", len(expiring_30d))

# ==========================================
# 7. Automatic Zoho CRM File Linker & Recovery Matcher
# ==========================================
st.subheader("📞 Zoho CRM & Expired Fleet Recovery Linker")

# Pick the most recently exported Deals/Customer CSVs automatically,
# instead of a hardcoded date, so this keeps working on future exports.
deals_candidates = sorted(glob.glob("Deals_*.csv"), reverse=True)
cust_candidates = sorted(glob.glob("Customer_*.csv"), reverse=True)
deals_path = deals_candidates[0] if deals_candidates else None
cust_path = cust_candidates[0] if cust_candidates else None

if deals_path and cust_path:
    st.caption(f"Using Zoho export files: `{deals_path}` and `{cust_path}`")

    deals_df = safe_read_file(deals_path)
    cust_df = safe_read_file(cust_path)

    deals_df.columns = deals_df.columns.astype(str).str.strip()
    cust_df.columns = cust_df.columns.astype(str).str.strip()

    deal_link_col = "Customer Name.id" if "Customer Name.id" in deals_df.columns else "Accounts Name.id"
    cust_link_col = "Record Id" if "Record Id" in cust_df.columns else cust_df.columns[0]

    if deal_link_col in deals_df.columns and cust_link_col in cust_df.columns:
        deals_df["link_id_clean"] = deals_df[deal_link_col].astype(str).str.strip()
        cust_df["link_id_clean"] = cust_df[cust_link_col].astype(str).str.strip()

        zoho_merged = pd.merge(
            deals_df, cust_df,
            left_on="link_id_clean", right_on="link_id_clean",
            how="left", suffixes=("_deal", "_cust")
        )

        expired_units = df[df["days_to_expiry"] < 0].copy()
        expired_units["match_plate"] = (
            expired_units["plate_number"]
            .astype(str).str.replace("-", "", regex=False)
            .str.replace(" ", "", regex=False).str.upper()
        )

        deal_plate_col = next((c for c in ["Plate Number", "Deal Name", "Vehicle Name"] if c in zoho_merged.columns), None)

        if deal_plate_col:
            zoho_merged["match_plate"] = (
                zoho_merged[deal_plate_col]
                .astype(str).str.replace("-", "", regex=False)
                .str.replace(" ", "", regex=False).str.upper()
            )

            final_recovery = pd.merge(expired_units, zoho_merged, on="match_plate", how="inner")

            # Check every likely column name, including merge suffixes,
            # so matches aren't silently lost when both source files
            # share a column name like "Phone" or "Email".
            phone_raw = first_existing_col(
                final_recovery,
                ["Phone", "Phone_cust", "Phone_deal", "Phone Number", "Phone Number_cust", "Phone Number_deal"],
            )
            email_raw = first_existing_col(
                final_recovery,
                ["Email", "Email_cust", "Email_deal", "Customer Email", "Customer Email_cust", "Customer Email_deal"],
            )

            final_recovery["phone_clean"] = phone_raw.apply(normalize_number)
            final_recovery["email_clean"] = email_raw.astype(str).str.strip().str.lower()

            valid_calls = final_recovery[final_recovery["phone_clean"] != ""]
            valid_emails = final_recovery[
                (final_recovery["email_clean"] != "") &
                (final_recovery["email_clean"] != "nan") &
                (~final_recovery["email_clean"].isin(EXCLUDED_EMAILS)) &
                (~final_recovery["email_clean"].str.contains("cartracker.ng", na=False))
            ]

            st.success(f"Successfully auto-matched **{len(final_recovery):,} expired vehicles** to Zoho CRM accounts from repository files!")

            m1, m2, m3 = st.columns(3)
            m1.metric("Matched Expired Units", f"{len(final_recovery):,}")
            m2.metric("Phone Numbers for Calling", f"{len(valid_calls):,}")
            m3.metric("Verified Recovery Emails", f"{len(valid_emails):,}")

            cust_name_col = "Customer Name_cust" if "Customer Name_cust" in final_recovery.columns else "Customer Name"
            preview_cols = [c for c in ["plate_number", "name", "expiration_date", cust_name_col, "phone_clean", "email_clean"] if c in final_recovery.columns]

            st.dataframe(final_recovery[preview_cols], use_container_width=True)

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.download_button(
                    "⬇️ Download Expired Fleet Calling List (CSV)",
                    final_recovery[preview_cols].to_csv(index=False),
                    "zoho_expired_fleet_calling_list.csv",
                    "text/csv",
                    key="dl_btn_calling_list"
                )
            with col_d2:
                st.download_button(
                    "⬇️ Download Expired Fleet Email List (CSV)",
                    valid_emails[preview_cols].to_csv(index=False),
                    "zoho_expired_fleet_email_list.csv",
                    "text/csv",
                    key="dl_btn_email_list"
                )
        else:
            st.error("Could not find 'Plate Number' or 'Deal Name' in the uploaded Deals file.")
    else:
        st.error(f"Could not find a link column. Looked for '{deal_link_col}' in Deals and '{cust_link_col}' in Customer file.")
else:
    st.info("No Zoho export files found in repository root (expected files named like `Deals_YYYY_MM_DD.csv` and `Customer_YYYY_MM_DD.csv`).")

# ==========================================
# 8. IMEI Vehicle & Customer Lookup
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">🔎 IMEI Vehicle & Customer Lookup</div>', unsafe_allow_html=True)
st.caption("Search the fleet report by IMEI, then match the vehicle to Zoho Deals and Customers where a reliable match exists.")

lookup_imei = st.text_input(
    "Enter the 15-digit IMEI",
    placeholder="e.g. 123456789012345",
    key="imei_vehicle_lookup_input",
).strip()

if st.button("Search IMEI", key="imei_vehicle_lookup_button", type="primary"):
    lookup_digits = "".join(ch for ch in lookup_imei if ch.isdigit())
    if not lookup_digits:
        st.warning("Enter an IMEI to search.")
    else:
        # Normalize IMEIs consistently; preserve leading zeroes by treating them as strings.
        fleet_lookup = df.copy()
        imei_col = next((c for c in ["imei", "IMEI", "Imei"] if c in fleet_lookup.columns), None)
        if not imei_col:
            st.error("The fleet report does not contain an IMEI column.")
        else:
            fleet_lookup["_lookup_imei"] = fleet_lookup[imei_col].fillna("").astype(str).str.strip().str.replace(r"\.0+$", "", regex=True).str.replace(r"\D", "", regex=True)
            matches = fleet_lookup[fleet_lookup["_lookup_imei"] == lookup_digits].copy()

            if matches.empty:
                st.warning("No vehicle was found for that IMEI in the current fleet report.")
            else:
                if len(matches) > 1:
                    st.warning(f"Found {len(matches)} fleet rows for this IMEI. Review the records below; duplicate IMEI data may need reconciliation.")

                # Load the latest repository Zoho exports for this lookup section.
                lookup_deals_path = sorted(glob.glob("Deals_*.csv"), reverse=True)
                lookup_customers_path = sorted(glob.glob("Customer_*.csv"), reverse=True)
                lookup_deals = None
                lookup_customers = None
                if lookup_deals_path:
                    try:
                        lookup_deals = safe_read_file(lookup_deals_path[0])
                        lookup_deals.columns = lookup_deals.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
                    except Exception:
                        lookup_deals = None
                if lookup_customers_path:
                    try:
                        lookup_customers = safe_read_file(lookup_customers_path[0])
                        lookup_customers.columns = lookup_customers.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()
                    except Exception:
                        lookup_customers = None

                def _lookup_text(row, candidates):
                    for col in candidates:
                        if col in row.index:
                            value = row.get(col, "")
                            if pd.notna(value) and str(value).strip().lower() not in ("", "nan", "none", "null"):
                                return str(value).strip()
                    return ""

                def _lookup_plate(value):
                    if pd.isna(value):
                        return ""
                    return re.sub(r"[^A-Z0-9]", "", str(value).upper())

                # Find the relevant Zoho Deal by registration/plate number.
                deal_match = None
                customer_match = None
                customer_match_method = "Not matched"
                first_vehicle = matches.iloc[0]
                fleet_plate = _lookup_text(first_vehicle, ["plate_number", "registration_number", "Plate Number", "Registration Number"])
                normalized_fleet_plate = _lookup_plate(fleet_plate)

                if lookup_deals is not None and normalized_fleet_plate:
                    deal_plate_col = next((c for c in ["Plate Number", "plate_number", "Registration Number", "Vehicle Registration Number"] if c in lookup_deals.columns), None)
                    if deal_plate_col:
                        deals_work = lookup_deals.copy()
                        deals_work["_lookup_plate"] = deals_work[deal_plate_col].apply(_lookup_plate)
                        deal_matches = deals_work[deals_work["_lookup_plate"] == normalized_fleet_plate].copy()
                        if not deal_matches.empty:
                            # Prefer the latest installation date; fall back to Modified Time / Created Time.
                            sort_col = next((c for c in ["Installation Date", "Modified Time", "Created Time"] if c in deal_matches.columns), None)
                            if sort_col:
                                deal_matches["_lookup_sort_date"] = pd.to_datetime(deal_matches[sort_col], errors="coerce")
                                deal_matches = deal_matches.sort_values("_lookup_sort_date", ascending=False, na_position="last")
                            deal_match = deal_matches.iloc[0]
                            customer_match_method = "Plate number"

                # Link Deal.Customer Name.id to Customer.Record Id; fall back to exact customer name.
                if deal_match is not None and lookup_customers is not None and not lookup_customers.empty:
                    deal_customer_id = _lookup_text(deal_match, ["Customer Name.id"])
                    if deal_customer_id and "Record Id" in lookup_customers.columns:
                        id_matches = lookup_customers[lookup_customers["Record Id"].fillna("").astype(str).str.strip() == deal_customer_id]
                        if not id_matches.empty:
                            customer_match = id_matches.iloc[0]
                    if customer_match is None:
                        deal_customer_name = _lookup_text(deal_match, ["Customer Name"])
                        if deal_customer_name and "Customer Name" in lookup_customers.columns:
                            name_matches = lookup_customers[lookup_customers["Customer Name"].fillna("").astype(str).str.strip().str.casefold() == deal_customer_name.casefold()]
                            if not name_matches.empty:
                                customer_match = name_matches.iloc[0]

                # Prefer the explicit Customer Name in the Deal if no Customer row was linked.
                deal_customer_name = _lookup_text(deal_match, ["Customer Name"]) if deal_match is not None else ""
                customer_name = ""
                if customer_match is not None:
                    customer_name = _lookup_text(customer_match, ["Customer Name"])
                    if not customer_name:
                        customer_name = " ".join(filter(None, [_lookup_text(customer_match, ["First Name"]), _lookup_text(customer_match, ["Last Name"])]))
                if not customer_name:
                    customer_name = deal_customer_name
                if not customer_name:
                    customer_name = _lookup_text(first_vehicle, ["object_owner", "customer_name", "Customer Name", "name"])
                    if customer_name == _lookup_text(first_vehicle, ["name"]):
                        # Device name is not necessarily the customer's name.
                        customer_name = ""

                customer_phone = _lookup_text(customer_match, ["Phone"]) if customer_match is not None else ""
                customer_email = _lookup_text(customer_match, ["Email"]) if customer_match is not None else ""
                if not customer_phone and deal_match is not None:
                    customer_phone = _lookup_text(deal_match, ["Phone", "Phone Number"])
                if not customer_email and deal_match is not None:
                    customer_email = _lookup_text(deal_match, ["Email", "Customer Email"])

                for idx, vehicle in matches.iterrows():
                    vehicle_name = _lookup_text(vehicle, ["name", "Vehicle Name", "Vehicle Model", "device_model"])
                    vehicle_model = _lookup_text(vehicle, ["device_model", "Vehicle Model", "Vehicle Name"])
                    plate = _lookup_text(vehicle, ["plate_number", "registration_number", "Plate Number", "Registration Number"])
                    sim = _lookup_text(vehicle, ["sim_number", "sim_num", "Sim Number", "sim_numbe"])
                    last_conn = vehicle.get("last_connect_time", "")
                    expiry = vehicle.get("expiration_date", "")
                    last_conn_display = "Not available"
                    if pd.notna(last_conn) and str(last_conn).strip() and str(last_conn).lower() != "nat":
                        last_conn_display = pd.to_datetime(last_conn, errors="coerce")
                        last_conn_display = last_conn_display.strftime("%d %b %Y, %I:%M %p") if pd.notna(last_conn_display) else str(last_conn)
                    expiry_display = "Not available"
                    days_left = None
                    if pd.notna(expiry) and str(expiry).strip() and str(expiry).lower() != "nat":
                        expiry_dt = pd.to_datetime(expiry, errors="coerce")
                        if pd.notna(expiry_dt):
                            expiry_display = expiry_dt.strftime("%d %b %Y")
                            days_left = (expiry_dt.normalize() - pd.Timestamp.now().normalize()).days
                    hours_offline = vehicle.get("hours_offline", float("nan"))
                    if pd.notna(hours_offline):
                        reporting_status = "Reporting (within 30 hours)" if float(hours_offline) <= 30 else "Not reporting (over 30 hours)"
                    else:
                        reporting_status = "Last connection unavailable"

                    st.markdown(f"#### Vehicle result {idx + 1 if isinstance(idx, int) else ''}".strip())
                    c1, c2, c3 = st.columns(3)
                    c1.metric("IMEI", lookup_digits)
                    c2.metric("Plate Number", plate or "Not available")
                    c3.metric("Subscription Expiry", expiry_display)
                    d1, d2, d3 = st.columns(3)
                    d1.write("**Vehicle / Device**")
                    d1.write(vehicle_name or "Not available")
                    d2.write("**Vehicle Model**")
                    d2.write(vehicle_model or "Not available")
                    d3.write("**SIM Number**")
                    d3.write(sim or "Not available")
                    e1, e2 = st.columns(2)
                    e1.write("**Last Connection**")
                    e1.write(last_conn_display)
                    e2.write("**Reporting Status**")
                    e2.write(reporting_status)
                    st.markdown("**Customer Details**")
                    x1, x2, x3 = st.columns(3)
                    x1.write("**Customer Name**")
                    x1.write(customer_name or "No reliable Zoho customer match found")
                    x2.write("**Phone**")
                    x2.write(customer_phone or "Not available")
                    x3.write("**Email**")
                    x3.write(customer_email or "Not available")
                    if deal_match is not None:
                        st.caption(f"Zoho match: {customer_match_method}. Deal: {_lookup_text(deal_match, ['Deal Name']) or 'Not specified'}.")
                    else:
                        st.info("No Zoho Deal matched this vehicle's plate number. Vehicle details above are from the fleet report; customer details may be incomplete.")
                    if days_left is not None:
                        if days_left < 0:
                            st.warning(f"Subscription expired {abs(days_left)} day(s) ago.")
                        elif days_left == 0:
                            st.warning("Subscription expires today.")
                        elif days_left <= 30:
                            st.warning(f"Subscription expires in {days_left} day(s).")

# ==========================================
# 8. Clean Customer Email Campaign Exporter
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">✉️ Deduplicated Clean Customer Emails</div>', unsafe_allow_html=True)
clean_emails_df = extract_clean_unique_emails(df)

st.write(f"Total Clean Customer Emails: **{len(clean_emails_df):,}** *(1 email per row, deduplicated, excluding internal `@cartracker` addresses and blacklisted emails)*")
st.dataframe(clean_emails_df, use_container_width=True)
st.download_button(
    label="⬇️ Download Clean Unique Emails (CSV)",
    data=clean_emails_df.to_csv(index=False).encode("utf-8"),
    file_name="deduplicated_customer_emails.csv",
    mime="text/csv",
)

# ==========================================
# 9. Network Analytics, Data Quality & Airtel 48h Offline Report
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">📡 Network Breakdown</div>', unsafe_allow_html=True)
st.bar_chart(network_breakdown)

st.markdown('<div class="icon-header">📊 Detailed SIM Network Diagnosis</div>', unsafe_allow_html=True)
net_df = pd.DataFrame({
    "Network Operator": network_breakdown.index,
    "Device Count": network_breakdown.values,
    "Percentage (%)": (network_breakdown.values / stats["total_vehicles"] * 100).round(2)
})
st.dataframe(net_df, use_container_width=True, hide_index=True)

st.markdown('<div class="icon-header">📡 Airtel SIMs Offline (48h+)</div>', unsafe_allow_html=True)
# Verified-only match, since contacting a customer based on a guessed
# network (rather than the confirmed Airtel list) risks acting on a
# wrong assumption.
airtel_48h_offline = df[
    (df["sim_network"] == "Airtel (verified)") &
    (df["hours_offline"] >= 48)
].sort_values("hours_offline", ascending=False)

st.write(f"Found **{len(airtel_48h_offline):,} verified Airtel units** offline for 48 hours or more.")
if not airtel_48h_offline.empty:
    preview_cols_airtel = [c for c in ["id", "name", "plate_number", "sim_number", "hours_offline", "expiration_date"] if c in airtel_48h_offline.columns]
    st.dataframe(airtel_48h_offline[preview_cols_airtel], use_container_width=True)
    st.download_button(
        "⬇️ Download Airtel 48h Offline List (CSV)",
        airtel_48h_offline[preview_cols_airtel].to_csv(index=False),
        "airtel_48h_offline_fleet.csv",
        "text/csv",
        key="dl_btn_airtel_48h"
    )

st.markdown('<div class="icon-header">🔍 SIM & IMEI Data Quality</div>', unsafe_allow_html=True)
d1, d2, d3, d4 = st.columns(4)
d1.metric("Missing SIM", stats["missing_sim"])
d2.metric("Duplicate SIMs", stats["duplicate_sim_count"])
d3.metric("Invalid IMEI", stats["invalid_imei"])
d4.metric("Duplicate IMEIs", stats["duplicate_imei_count"])

# ==========================================
# 10. Renewal Opportunities & Expired List
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">💰 Renewal Opportunities</div>', unsafe_allow_html=True)
st.write(f"Found **{len(renewal_opportunity):,} vehicles** ready for renewal.")
st.dataframe(renewal_opportunity[["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date"]], use_container_width=True)

st.markdown('<div class="icon-header">⚠️ Expired Vehicles List (All Units)</div>', unsafe_allow_html=True)
expired_df = df[df["days_to_expiry"] < 0]
st.write(f"Found **{len(expired_df):,} total expired vehicles**.")
st.download_button(
    "⬇️ Download Expired Vehicles List (CSV)",
    expired_df.to_csv(index=False),
    "expired_vehicles_list.csv",
    "text/csv",
)

# ==========================================
# 11. AI Intelligence via Gemini API
# ==========================================
st.write("---")
st.markdown('<div class="icon-header">🤖 AI Fleet Intelligence</div>', unsafe_allow_html=True)

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "You are analyzing a fleet tracking dataset. Use ONLY these verified numbers:\n"
            + json.dumps(stats, indent=2, default=str)
            + "\n\nReturn valid JSON with keys: summary, insights, actions."
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        raw = response.text.strip().strip("`").replace("json", "", 1).strip()
        result = json.loads(raw)

        st.subheader("📋 AI Executive Summary")
        st.write(result.get("summary", ""))

        st.subheader("💡 Insights")
        for i in result.get("insights", []):
            st.markdown(f"- {i}")

        st.subheader("🛠️ Recommended Actions")
        for a in result.get("actions", []):
            st.markdown(f"- **{a.get('task', '')}**: {a.get('detail', '')}")
    except Exception:
        st.info("AI summary engine standby or API rate limit reached.")
