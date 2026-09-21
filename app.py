import os
import pandas as pd
import streamlit as st

# 1. UI File Uploaders (MUST BE DEFINED FIRST)
uploaded_file = st.file_uploader(
    "Choose your fleet CSV file", type=["csv", "xlsx", "xls"]
)

airtel_file = st.file_uploader(
    "Upload Airtel SIM list (optional)", type=["csv", "xlsx"]
)

# 2. Process Airtel File (NOW airtel_file IS DEFINED)
airtel_numbers = set()

if airtel_file is not None:
  airtel_df = safe_read_file(airtel_file)
  airtel_df.columns = (
      airtel_df.columns.astype(str)
      .str.replace("\ufeff", "", regex=False)
      .str.strip()
  )

  msisdn_col = next(
      (
          col
          for col in airtel_df.columns
          if col.lower()
          in [
              "msisdn",
              "phone",
              "phone number",
              "phonenumber",
              "sim",
              "sim number",
              "sim_number",
              "mobile",
          ]
      ),
      None,
  )

  if not msisdn_col:
    st.error(
        "Couldn't find an 'MSISDN' column. Found these instead: "
        + str(list(airtel_df.columns))
    )
  else:
    airtel_numbers = set(airtel_df[msisdn_col].apply(normalize_number))
    airtel_numbers.discard("")
    st.write(
        f"Loaded {len(airtel_numbers):,} Airtel numbers for cross-reference."
    )
