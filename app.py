# app.py
import streamlit as st
import pandas as pd
import re
from logic import Weights, allocate, explain_allocation
from openai import OpenAI
client = OpenAI(
    api_key="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"
)


st.set_page_config(page_title="Equitable School Pools", layout="wide")

@st.cache_data
def load_schools():
    df = pd.read_csv("/Users/esandem2018/Downloads/schools.csv")
    df["frl_pct"] = df["frl_pct"].astype(float)
    df["enrollment"] = df["enrollment"].astype(int)
    return df

df = load_schools()
counties = sorted(df["county"].unique())

# --- Sidebar controls ---
st.sidebar.title("Navigator")
county = st.sidebar.selectbox("Choose a county", counties, index=0)

st.sidebar.markdown("### Weights (locked for demo)")
w = Weights(enroll=0.40, frl=0.60)
if w.enroll + w.frl == 0:
    st.sidebar.error("Increase at least one weight.")
    st.stop()

# Session state for pools and donation log
if "pools" not in st.session_state:
    st.session_state.pools = {c: 1000.0 for c in counties}  # seed $ for demo
if "donations" not in st.session_state:
    st.session_state.donations = []  # (name, amount, county)

pool = st.session_state.pools[county]

st.title("Equitable Grants for Title I schools")
st.caption("Transparent, explainable distribution of pooled funds by county.")

# --- Header: pool & donate ---
col1, col2, col3 = st.columns([1,1,2], vertical_alignment="center")
with col1:
    st.metric(f"Pool for {county}", f"${pool:,.2f}")

with col2:
    donation = st.number_input("Donate amount ($)", min_value=0.0, value=50.0, step=10.0, key="donation_input")
    donor = st.text_input("Your name (optional)", "")
    if st.button("Donate"):
        if donation > 0:
            st.session_state.pools[county] += donation
            st.session_state.donations.append((donor or "Anonymous", float(donation), county))
            st.success(f"Donation recorded. New {county} pool: ${st.session_state.pools[county]:,.2f}")
        else:
            st.warning("Enter a positive amount.")

with col3:
    st.info("Demo mode: donations update the pool locally. In production we'd use a payment provider in test mode, then sync.", icon="ℹ️")

# --- Compute allocations ---
sub = df[df["county"] == county].copy()
pool = st.session_state.pools[county]
alloc = allocate(pool, sub, w=w, floor=0.00, cap_fraction=None)

# --- Charts & tables ---
st.subheader(f"Allocations in {county}")
st.bar_chart(alloc.set_index("school")["allocation"])

pretty = alloc[["school","enrollment","frl_pct","allocation","need_share"]].rename(columns={
    "school":"School","enrollment":"Enrollment","frl_pct":"FRL %","allocation":"Allocation ($)","need_share":"Need Share"
})
pretty["Need Share"] = (pretty["Need Share"]*100).round(1).astype(str) + "%"

st.dataframe(pretty, use_container_width=True)

# --- Explain per-school ---
st.subheader("Why each amount?")
county_sum_enroll = int(sub["enrollment"].sum())
county_sum_frl = float(sub["frl_pct"].sum())
for _, row in alloc.iterrows():
    with st.expander(row["school"]):
        st.write(explain_allocation(row, pool, w, county_sum_enroll, county_sum_frl))

# --- Download current allocations ---
csv_bytes = pretty.to_csv(index=False).encode("utf-8")
st.download_button("Download allocations (CSV)", data=csv_bytes, file_name=f"allocations_{county}.csv", mime="text/csv")



# --- Transparency drawer ---
with st.sidebar.expander("Transparency"):
    st.write(f"**Weights** — Enrollment: {w.enroll:.2f}, FRL: {w.frl:.2f}")
    st.write("**Recent donations**")
    if st.session_state.donations:
        for name, amt, c in reversed(st.session_state.donations[-5:]):
            st.write(f"- {name} donated ${amt:,.2f} to {c}")
    else:
        st.write("_No donations yet in this session._")


def ai_explain_row(row, county, pool, w_enroll, w_frl):
    if client is None:
        return "AI explainer unavailable (set OPENAI_API_KEY)."

    # Try to get a 'need students' number; fall back to FRL% * enrollment
    try:
        frl_students = float(row.get("frl_students", None))
        if pd.isna(frl_students):
            frl_students = None
    except Exception:
        frl_students = None
    if frl_students is None:
        frl_pct = float(row.get("frl_pct", 0) or 0)
        frl_students = float(row.get("enrollment", 0)) * (frl_pct / 100.0)

    prompt = f"""
    In 2–3 sentences, explain to a donor why {row['school']} in {county} receives ${row['allocation']:,.2f}
    from a ${pool:,.2f} county pool. Facts:
    - Enrollment: {int(row.get('enrollment', 0))}
    - Estimated need (FRL/Title I) students: {int(round(frl_students))}
    - Weights: enrollment={w_enroll:.2f}, need={w_frl:.2f}
    Be clear and encouraging. End with one tangible impact example.
    """.strip()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a concise, trustworthy grants communicator."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=180,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"(AI error: {e})"
# make sure we have weight numbers
try:
    w_enroll_val, w_frl_val = w.enroll, w.frl   # if you use the Weights dataclass
except Exception:
    # or fall back if you just have sliders or nothing
    w_enroll_val, w_frl_val = 0.40, 0.60

sum_enroll = int(sub["enrollment"].sum())
# (optional but fine if you already compute frl_students elsewhere)
if "frl_students" not in sub.columns:
    sub["frl_students"] = sub["enrollment"] * (sub.get("frl_pct", 0) / 100.0)

for idx, row in alloc.iterrows():
    with st.expander(row["school"]):
        if st.button(f"AI explainer", key=f"ai_{idx}"):
            with st.spinner("Generating…"):
                text = ai_explain_row(
                    row=row,
                    county=county,
                    pool=pool,
                    w_enroll=w_enroll_val,
                    w_frl=w_frl_val,
                )
            st.write(text)





