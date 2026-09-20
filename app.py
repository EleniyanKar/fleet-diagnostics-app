import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

st.set_page_config(page_title="AI Fleet Diagnostics Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ AI Fleet Diagnostics Dashboard")
st.write("Upload a device CSV report to generate a full fleet analysis.")

NETWORK_PREFIXES = {
    "MTN": ["0803", "0806", "0703", "0706", "0813", "0816", "0810", "0814", "0903", "0906", "0913", "0916", "0704"],
    "Airtel": ["0802", "0808", "0708", "0812", "0701", "0902", "0901", "0904", "0907", "0912"],
    "Glo": ["0805", "0807", "0705", "0815", "0811", "0905", "0915"],
    "9mobile": ["0809", "0817", "0818", "0908", "0909"],
}
PREFIX_TO_NETWORK = {}
for net, prefixes in NETWORK_PREFIXES.items():
    for p in prefixes:
        PREFIX_TO_NETWORK[p] = net

ADMIN_EMAILS = {
    "hello@cartracker.com.ng",
    "oluwafemi.a@cartracker.com",
    "ayo.a@cartracker.com",
    "inyang@cartracker.com",
    "rukayat@cartracker.com.ng",
    "temitayo.o@cartracker.com",
    "gideon.onyebuchi@cartracker.com",
    "oyindaabegunde@yahoo.com",
    "abasifrekeekanem1@cartracker.com",
    "andrew@cartracker.com.ng",
    "ifeoluwa@cartracker.ng",
    "james@cartracker.com.org",
    "blessing@catracker.com.ng",
    "damilola@catracker.com.ng",
    "dammylola@catracker.com.ng",
    "blessing@catracker.ng",
    "dammylola@catracker.ng",
}


def sim_network(sim, airtel_set):
    sim_clean = str(sim).strip().replace(".0", "")
    if not sim_clean or sim_clean.lower() == "nan":
        return "Missing"
    if sim_clean in airtel_set:
        return "Airtel (verified)"
    prefix = None
    if len(sim_clean) >= 3:
        prefix = "0" + sim_clean[:3]
    if prefix and prefix in PREFIX_TO_NETWORK:
        return PREFIX_TO_NETWORK[prefix]
    return "Unknown/Other (guessed)"


def valid_imei(v):
    v = str(v).replace(".00", "").strip()
    return v.isdigit() and len(v) == 15


def extract_customer_emails(users_list_value):
    raw = str(users_list_value)
    parts = raw.split(",")
    result = []
    for p in parts:
        p = p.strip()
        if "@" in p and p.lower() not in ADMIN_EMAILS:
            result.append(p)
    return result


uploaded_file = st.file_uploader("Choose your fleet CSV file", type="csv")
airtel_file = st.file_uploader("Upload Airtel SIM list (optional, for accurate network ID)", type=["csv", "xlsx"])

airtel_numbers = set()
if airtel_file is not None:
    if airtel_file.name.endswith(".xlsx"):
        airtel_df = pd.read_excel(airtel_file)
    else:
        airtel_df = pd.read_csv(airtel_file, sep=None, engine="python")
    airtel_df.columns = airtel_df.columns.str.replace("\ufeff", "", regex=False).str.strip()

    if "MSISDN" not in airtel_df.columns:
        st.error("Couldn't find an 'MSISDN' column. Found these instead: " + str(list(airtel_df.columns)))
    else:
        cleaned = airtel_df["MSISDN"].astype(str).str.strip().str.replace(r"\D", "", regex=True)
        airtel_numbers = set(cleaned)
        st.write("Loaded " + str(len(airtel_numbers)) + " Airtel numbers for cross-reference.")


if uploaded_file is not None:
    df = pd.read_csv(uploaded_file, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = df.columns.str.replace("\ufeff", "", regex=False).str.strip()

    st.write("Loaded " + str(len(df)) + " rows")
    st.dataframe(df.head(10))

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["last_connect_time"] = pd.to_datetime(df["last_connect_time"], errors="coerce")
    df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce")

    st.write("Sample last_connect_time values:", df["last_connect_time"].head(5).tolist())
    st.write("Non-null last_connect_time count:", df["last_connect_time"].notna().sum())

    now = pd.Timestamp.now()
    df["hours_offline"] = (now - df["last_connect_time"]).dt.total_seconds() / 3600
    df["days_to_expiry"] = (df["expiration_date"] - now).dt.total_seconds() / 86400

    df["user_emails"] = df["users_list"].apply(extract_customer_emails)
    df["primary_email"] = df["user_emails"].apply(lambda emails: emails[0] if len(emails) > 0 else "")

    run_clicked = st.button("Run Full Diagnostic Assessment")

    if run_clicked:
        with st.spinner("Analyzing " + str(len(df)) + " rows..."):

            reporting_24h = df[df["hours_offline"] <= 24]
            not_reporting = df[df["hours_offline"] > 24]

            expired_24h = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -1)]
            expired_30d = df[(df["days_to_expiry"] < 0) & (df["days_to_expiry"] >= -30)]
            expired_total = df[df["days_to_expiry"] < 0]

            expiring_24h = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 1)]
            expiring_30d = df[(df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30)]

            active_vehicles = df[df["active"] == 1]
            active_but_offline = active_vehicles[active_vehicles["hours_offline"] > 24]

            df["sim_network"] = df["sim_number"].apply(lambda x: sim_network(x, airtel_numbers))
            network_breakdown = df["sim_network"].value_counts()
            offline_only = df[df["hours_offline"] > 24]
            offline_by_network = offline_only["sim_network"].value_counts()

            missing_sim = df[df["sim_number"].isna() | (df["sim_number"].astype(str).str.strip() == "")]
            sim_counts = df["sim_number"].astype(str).value_counts()
            duplicate_sims = sim_counts[sim_counts > 1].index.tolist()
            sim_is_dup = df["sim_number"].astype(str).isin(duplicate_sims)
            sim_not_nan = df["sim_number"].astype(str) != "nan"
            duplicate_sim_rows = df[sim_is_dup & sim_not_nan]

            df["imei_clean"] = df["imei"].astype(str).str.replace(".00", "", regex=False).str.strip()
            invalid_imei = df[~df["imei"].apply(valid_imei)]
            imei_counts = df["imei_clean"].value_counts()
            duplicate_imeis = imei_counts[imei_counts > 1].index.tolist()
            duplicate_imei_rows = df[df["imei_clean"].isin(duplicate_imeis)]

            df["install_month"] = df["created_at"].dt.to_period("M").astype(str)
            install_trend = df.groupby("install_month").size()

            renewal_mask = (df["days_to_expiry"] >= 0) & (df["days_to_expiry"] <= 30) & (df["hours_offline"] <= 24)
            renewal_opportunity = df[renewal_mask].sort_values("days_to_expiry")

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

            st.session_state["last_stats"] = stats
            st.session_state["last_df"] = df

        st.success("Analysis Complete!")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reporting (24h)", stats["reporting_24h"])
        c2.metric("Not Reporting", stats["not_reporting"])
        c3.metric("Expired (total)", stats["expired_total"])
        c4.metric("Active but Offline", stats["active_but_offline"])

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Expired (last 24h)", stats["expired_last_24h"])
        c6.metric("Expired (last 30d)", stats["expired_last_30d"])
        c7.metric("Expiring (next 24h)", stats["expiring_next_24h"])
        c8.metric("Expiring (next 30d)", stats["expiring_next_30d"])

        st.subheader("Network Breakdown (SIM)")
        st.bar_chart(network_breakdown)

        st.subheader("Offline Devices by Network")
        st.bar_chart(offline_by_network)

        st.subheader("Airtel SIMs Offline 48+ Hours")
        airtel_mask = (df["sim_network"] == "Airtel (verified)") & (df["hours_offline"] >= 48)
        airtel_offline_cols = ["id", "name", "plate_number", "sim_number", "last_connect_time", "hours_offline"]
        airtel_offline_48h = df.loc[airtel_mask, airtel_offline_cols]
        airtel_offline_48h = airtel_offline_48h.sort_values("hours_offline", ascending=False)
        st.write(str(len(airtel_offline_48h)) + " Airtel SIMs have not reported in 48+ hours.")
        st.dataframe(airtel_offline_48h, use_container_width=True)
        st.download_button(
            "Download Airtel Offline 48h+ List (CSV)",
            airtel_offline_48h.to_csv(index=False),
            "airtel_offline_48h.csv",
            "text/csv",
        )

        st.subheader("SIM & IMEI Data Quality")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Missing SIM", stats["missing_sim"])
        d2.metric("Duplicate SIMs", stats["duplicate_sim_count"])
        d3.metric("Invalid IMEI", stats["invalid_imei"])
        d4.metric("Duplicate IMEIs", stats["duplicate_imei_count"])

        st.subheader("Installation Trend")
        st.bar_chart(install_trend)

        st.subheader("Renewal Opportunity (active, reporting, expiring within 30 days)")
        st.write(str(stats["renewal_opportunity_count"]) + " vehicles are easiest to renew since they're currently reporting.")
        renewal_cols = ["id", "name", "plate_number", "sim_number", "expiration_date", "days_to_expiry"]
        st.dataframe(renewal_opportunity[renewal_cols], use_container_width=True)
        st.download_button(
            "Download Renewal Opportunity List (CSV)",
            renewal_opportunity.to_csv(index=False),
            "renewal_opportunity.csv",
            "text/csv",
        )

        st.subheader("Renewal Opportunity - By Customer Email")
        renewal_with_email = renewal_opportunity.copy()
        renewal_with_email["primary_email"] = df.loc[renewal_with_email.index, "primary_email"]
        has_email = renewal_with_email["primary_email"] != ""
        email_groups = renewal_with_email[has_email].groupby("primary_email")

        for email, group in email_groups:
            label = email + " - " + str(len(group)) + " vehicle(s) expiring soon"
            with st.expander(label):
                group_cols = ["id", "name", "plate_number", "expiration_date", "days_to_expiry"]
                st.dataframe(group[group_cols])
                vehicle_list = ", ".join(group["name"].astype(str))
                body_text = (
                    "Dear Customer,%0A%0AThe following vehicles on your account are expiring soon: "
                    + vehicle_list.replace(" ", "%20")
                    + ".%0A%0APlease renew to avoid service interruption."
                )
                mailto_link = "mailto:" + email + "?subject=Vehicle%20Subscription%20Renewal%20Reminder&body=" + body_text
                st.markdown("[Send renewal email](" + mailto_link + ")")

        st.subheader("Download Customer Contact List")
        has_primary_email = df["primary_email"] != ""
        contact_cols = ["id", "name", "plate_number", "sim_number", "primary_email", "expiration_date", "days_to_expiry"]
        contact_export = df.loc[has_primary_email, contact_cols].copy()
        st.download_button(
            "Download Full Customer Email List (CSV)",
            contact_export.to_csv(index=False),
            "customer_email_list.csv",
            "text/csv",
        )

        if GEMINI_API_KEY:
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                prompt = (
                    "You are analyzing a fleet tracking dataset. Use ONLY these verified numbers, do not recalculate:\n"
                    + json.dumps(stats, indent=2, default=str)
                    + "\n\nReturn ONLY valid JSON with keys: summary (one paragraph), "
                    + "insights (4-6 bullet strings), actions (list of objects with task and detail)."
                )
                response = client.models.generate_content(model="models/gemini-3.6-flash", contents=prompt)
                raw = response.text.strip()
                raw = raw.strip("`")
                raw = raw.replace("json", "", 1).strip()
                result = json.loads(raw)

                st.subheader("AI Summary")
                st.write(result.get("summary", ""))

                st.subheader("Insights")
                for i in result.get("insights", []):
                    st.markdown("- " + str(i))

                st.subheader("Recommended Actions")
                for a in result.get("actions", []):
                    task = a.get("task", "")
                    detail = a.get("detail", "")
                    st.markdown("- **" + task + "**: " + detail)
            except Exception as e:
                st.warning("AI summary unavailable right now (Gemini may be busy). The numbers above are still accurate. Error: " + str(e))

if "last_stats" in st.session_state:
    st.divider()
    st.subheader("Ask a question about this fleet data")
    question = st.text_input("e.g. How many vehicles are expiring next week? or Which network has the most offline devices?")

    ask_clicked = st.button("Ask")

    if ask_clicked and question.strip() != "":
        with st.spinner("Thinking..."):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                qa_prompt = (
                    "You are answering a question about a fleet tracking dataset.\n"
                    "Use ONLY the numbers below - do not invent figures.\n\n"
                    "Fleet stats:\n"
                    + json.dumps(st.session_state["last_stats"], indent=2, default=str)
                    + "\n\nQuestion: " + question + "\n\n"
                    "Answer concisely and directly. If the question needs data not present in the "
                    "stats above, say so clearly rather than guessing."
                )
                answer = client.models.generate_content(model="models/gemini-3.6-flash", contents=qa_prompt)
                st.write(answer.text)
            except Exception as e:
                st.warning("Couldn't get an answer right now (Gemini may be busy). Error: " + str(e))
